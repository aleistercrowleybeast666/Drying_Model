"""Acceptance, evidence completeness, conservative transfer and mesh provenance."""
import json
from pathlib import Path
import numpy as np
import pytest
from drying.validation import Validation_AssessSpatial, Validation_ProjectAverages, Validation_SaveEntry
from drying.geometry import Geometry_GetCells
from drying.mesh import Mesh_GetHash
from drying.cases import Case_ReadStatus, Case_GetSourceHash
from drying.storage import Storage_WriteJson, Storage_WriteArray


def test_strict_official_spatial_points_and_event_are_distinct_from_full_field_metric():
    tolerance = dict(temperature_abs_K=.01,moisture_abs=.01,drying_time_relative=.002)
    value = dict(reference_complete=True,official_temperature=dict(value=.009),
        official_moisture=dict(value=.0099),event_relative_difference=.0019,
        maxima_moisture=dict(value=.4))
    assert Validation_AssessSpatial(value,tolerance,True)['passed']
    value['event_relative_difference'] = .00201
    assert not Validation_AssessSpatial(value,tolerance,True)['passed']
    value['event_relative_difference'] = None
    assert 'SPATIAL_REFERENCE_INCOMPLETE' in Validation_AssessSpatial(value,tolerance,True)['failure_reasons'][0]
    assert Validation_AssessSpatial(value,tolerance,False)['passed']
    value['reference_complete'] = False
    assert not Validation_AssessSpatial(value,tolerance,False)['passed']


def test_projection_conserves_volume_integrals_and_constants():
    coarse = (np.array([0,.1,.35,.6,1]),np.array([0,.2,.7,1]))
    fine = (np.array([0,.08,.25,.4,.75,.9,1]),np.array([0,.15,.5,.8,1]))
    state = np.random.default_rng(491).uniform(.1,3,(2,4,3))
    projected = Validation_ProjectAverages(state,coarse,fine)
    va = Geometry_GetCells(4,3,.017,mesh=coarse)[2]
    vb = Geometry_GetCells(6,4,.017,mesh=fine)[2]
    np.testing.assert_allclose((state*va).sum(axis=(1,2)),(projected*vb).sum(axis=(1,2)),rtol=3e-15)
    np.testing.assert_allclose(Validation_ProjectAverages(np.ones_like(state),coarse,fine),1.,atol=3e-16)


def test_independent_case_summaries_preserve_completed_evidence(tmp_path):
    Validation_SaveEntry(tmp_path,'q1_1d',dict(spatial_passed=False))
    Validation_SaveEntry(tmp_path,'q23_2d',dict(spatial_passed=False,coverage='partial'))
    result = Validation_SaveEntry(tmp_path,'q1_1d',dict(spatial_passed=False,time_passed=True))
    assert result['q23_2d']['coverage'] == 'partial'
    assert result['q1_1d']['time_passed']
    assert not (tmp_path/'work/validation/summary.lock').exists()


def test_mesh_and_monitor_tampering_invalidates_current_cache(tmp_path):
    source = tmp_path/'src/drying'; source.mkdir(parents=True)
    for name in ['materials.py','boundaries.py','operators.py','rk4.py','sampling.py','inputs.py','events.py','geometry.py']:
        (source/name).write_text('# fixture',encoding='utf-8')
    Storage_WriteJson(tmp_path/'data/input_manifest.json',dict(hash='input'))
    xi,eta = np.linspace(0,1,5),np.array([0.,1.])
    x,monitor = np.linspace(0,1,9),np.linspace(1,2,9)
    folder = tmp_path/'work/cache/example'
    metadata = dict(input_hash='input',source_hash=Case_GetSourceHash(tmp_path),case='q1',
        mesh_mode='adaptive',mesh_profile_hash=Mesh_GetHash(xi,eta),
        radial_monitor_hash=Mesh_GetHash(x,monitor),axial_monitor_hash=None)
    Storage_WriteJson(folder/'status.json',metadata)
    Storage_WriteArray(folder/'mesh.npz',xi_faces=xi,eta_faces=eta)
    target = tmp_path/'work/validation/mesh_profiles/q1_radial_monitor.npz'
    Storage_WriteArray(target,x=x,monitor=monitor)
    assert Case_ReadStatus(tmp_path,'example')['mesh_profile_hash'] == metadata['mesh_profile_hash']
    xi[1] += .01
    Storage_WriteArray(folder/'mesh.npz',xi_faces=xi,eta_faces=eta)
    with pytest.raises(RuntimeError,match='mesh profile changed'): Case_ReadStatus(tmp_path,'example')
    xi[1] -= .01
    Storage_WriteArray(folder/'mesh.npz',xi_faces=xi,eta_faces=eta)
    monitor[-1] += .01
    Storage_WriteArray(target,x=x,monitor=monitor)
    with pytest.raises(RuntimeError,match='frozen monitor changed'): Case_ReadStatus(tmp_path,'example')


def test_internal_excess_and_incomplete_audit_do_not_veto_formal_acceptance():
    tol = dict(temperature_abs_K=.01,moisture_abs=.01,drying_time_relative=.002)
    value = dict(reference_complete=True,official_temperature=dict(value=20.),
        official_moisture=dict(value=2.),event_relative_difference=.001,
        official_output_times_max_error=dict(temperature=dict(value=.009),moisture=dict(value=.008),complete=True),
        all_internal_times_max_error=dict(complete=False,temperature=dict(value=20.),moisture=dict(value=2.)))
    result = Validation_AssessSpatial(value,tol,True)
    assert result['passed'] and not result['internal_audit_veto']
    assert len(result['audit_warnings']) == 3 and not result['failure_reasons']
    value['reference_complete'] = False  # Missing non-formal saved rows cannot veto complete official coverage.
    assert Validation_AssessSpatial(value,tol,True)['passed']
    value['official_output_times_max_error']['complete'] = False
    assert not Validation_AssessSpatial(value,tol,True)['passed']
    value['official_output_times_max_error']['complete'] = True
    value['official_output_times_max_error']['moisture']['value'] = .0101
    assert not Validation_AssessSpatial(value,tol,True)['passed']


def test_both_drying_endpoint_fields_are_formal_even_between_output_rows(monkeypatch,tmp_path):
    import drying.validation as module
    statuses = {key:dict(case='q4',cap=180.,complete=True,fingerprint=key,
        event=dict(report_s=endpoint,raw_event_s=endpoint)) for key,endpoint in [('a',75.),('b',95.)]}
    monkeypatch.setattr(module,'Case_ReadStatus',lambda root,key:statuses[key])
    mesh = (np.linspace(0,1,5),np.array([0.,1.]))
    monkeypatch.setattr(module,'Case_LoadMesh',lambda *args:mesh)
    def State(key,t):
        value=np.ones((2,4,1)); value[0]=301.15
        if key=='a' and t==95.: value[1]+=.02
        return value
    monkeypatch.setattr(module,'Case_IterFields',lambda root,key:iter((t,State(key,t)) for t in [0.,60.,120.,180.]))
    monkeypatch.setattr(module,'Validation_GetEndpointState',lambda root,key,t:State(key,t))
    root=Path(__file__).resolve().parents[1]
    value,rows=module.Validation_CompareCaches(root,'a','b')
    formal=value['official_output_times_max_error']
    assert formal['complete'] and formal['endpoint_times_s']==[75.,95.]
    assert formal['sample_count']==4
    assert formal['moisture']['time_s']==95. and formal['moisture']['value']>.01
    assert 75. in [row[0] for row in rows] and 95. in [row[0] for row in rows]
    assert not module.Validation_AssessSpatial(value,dict(temperature_abs_K=.01,moisture_abs=.01,drying_time_relative=.002),False)['passed']
