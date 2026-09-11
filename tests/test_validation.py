"""Acceptance, evidence completeness, conservative transfer and mesh provenance."""
import json
import numpy as np
import pytest
from drying.validation import Validation_AssessSpatial, Validation_ProjectAverages, Validation_SaveEntry
from drying.geometry import Geometry_GetCells
from drying.mesh import Mesh_GetHash
from drying.cases import Case_ReadStatus, Case_GetSourceHash
from drying.storage import Storage_WriteJson, Storage_WriteArray


def test_official_samples_and_event_control_acceptance_not_internal_spike():
    tolerance = dict(temperature_abs_K=.01,moisture_abs=.002,drying_time_relative=.001)
    value = dict(reference_complete=True,official_temperature=dict(value=.009),
        official_moisture=dict(value=.0019),event_relative_difference=.0009,
        maxima_moisture=dict(value=.4))
    assert Validation_AssessSpatial(value,tolerance,True)['passed']
    value['event_relative_difference'] = .00101
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
