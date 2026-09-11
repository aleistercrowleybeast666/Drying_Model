import numpy as np
from drying.audit import Audit_ReplayInterval, Audit_MeasureStates, Audit_ReconstructRadial
from drying.rk4 import Rk4_Advance
from drying.cases import Case_LoadInputs
from drying.validation import Validation_AssessSpatial, Validation_AssessTrend
from drying.stages import Stage_AssessTransfers, Stage_LoadSchedule
from drying.boundaries import Boundary_Reconstruct
from drying.sampling import Sampling_Reconstruct
from drying.materials import Material_Evaluate
from pathlib import Path


def test_replay_matches_actual_accepted_rk4_history_including_input_jump():
    root=Path(__file__).resolve().parents[1]; inputs=Case_LoadInputs(root)
    xi=np.array([0.,.12,.35,.7,1.]); eta=np.array([0.,1.])
    state=np.empty((2,4,1)); state[0]=310.; state[1]=1.5
    for start,stop in [(0.,.8),(14399.8,14400.2)]:
        result=Rk4_Advance(state,start,stop,.25,3,*inputs,False,False,.5,1e-8,20,1000,280.,340.,
            np.empty(0),xi_faces=xi,eta_faces=eta)
        assert result[4]==0
        replay=Audit_ReplayInterval(state,start,result[2],xi,3,*inputs)
        np.testing.assert_allclose(replay[-1],result[0],rtol=0,atol=1e-13)


def test_initial_surface_audit_exposes_subsecond_difference():
    inputs=Case_LoadInputs(Path(__file__).resolve().parents[1])
    a=np.empty((2,4,1)); a[0]=301.15; a[1]=2.55
    b=np.empty((2,8,1)); b[0]=301.15; b[1]=2.55
    xa=np.linspace(0,1,5); xb=np.linspace(0,1,9)
    assert Audit_MeasureStates(a,b,0.,xa,xb,1,*inputs)[3,0]==0
    peak=Audit_MeasureStates(a,b,.001,xa,xb,1,*inputs)[3]
    assert peak[0]>0 and peak[2]>=.018 and peak[1]==.001


def test_strict_trend_and_transfer_checks_cannot_be_overridden_by_small_error():
    tol=dict(temperature_abs_K=.01,moisture_abs=.01,drying_time_relative=.002)
    old=dict(official_temperature=dict(value=.001),official_moisture=dict(value=.002),event_relative_difference=.0004)
    new=dict(reference_complete=True,official_temperature=dict(value=.0005),official_moisture=dict(value=.003),event_relative_difference=.0003)
    assert Validation_AssessSpatial(new,tol,True)['passed']
    assert not Validation_AssessTrend(new,old,tol)['passed']
    assert 'SPATIAL_ERROR_NOT_DECREASING' in new['failure_reasons']
    transfer=Stage_AssessTransfers([dict(switch_time=60,projection_max_abs_T=.001,projection_max_abs_C=.011)],tol)
    assert transfer['assessment']=='AUDIT_ONLY' and transfer['threshold_exceeded'] and not transfer['acceptance_veto']


def test_conservative_schedule_keeps_early_200_160_then_80():
    root=Path(__file__).resolve().parents[1]
    for case,end in [('q1',60),('q23',300),('q4',600)]:
        default=Stage_LoadSchedule(root,case); conservative=Stage_LoadSchedule(root,case,True)
        assert [s['nr'] for s in default]==[200,160,80,40]
        assert [s['nr'] for s in conservative]==[200,160,80]
        assert default[0]['t_end']==end and conservative[-1]['t_end']==default[-1]['t_end']


def test_nonuniform_surface_reconstruction_uses_actual_center_distance():
    xi=np.array([0.,.3,.6,.91,1.]); eta=np.array([0.,1.]); R=.017
    u=np.empty((2,4,1)); u[0]=310.; u[1]=1.3
    field=Sampling_Reconstruct(u,R,320.,.1,4,ends=False,xi_faces=xi,eta_faces=eta)
    properties=Material_Evaluate(4,310.,1.3); distance=R-R*(xi[-2]+xi[-1])/2
    for p,ambient,exchange in [(0,320.,25.),(1,.1,8e-7)]:
        expected=Boundary_Reconstruct(u[p,-1,0],ambient,properties[p+2],distance,exchange)
        np.testing.assert_allclose(field[p,-1,1],expected,rtol=0,atol=1e-13)
    np.testing.assert_array_equal(Audit_ReconstructRadial(u,xi,R,320.,.1,4),field[:,:,0])


def test_radial_audit_specialization_matches_original_for_all_models():
    rng=np.random.default_rng(441)
    for model in [1,3,4]:
        for n in [4,17,80]:
            xi=np.r_[0.,np.sort(rng.uniform(.01,.99,n-1)),1.]; eta=np.array([0.,1.])
            state=np.empty((2,n,1)); state[0]=rng.uniform(301.15,326.15,(n,1)); state[1]=rng.uniform(.15,2.55,(n,1))
            for R in [.02,.013]:
                expected=Sampling_Reconstruct(state,R,321.15,.1,model,ends=False,xi_faces=xi,eta_faces=eta)
                np.testing.assert_array_equal(Audit_ReconstructRadial(state,xi,R,321.15,.1,model),expected[:,:,0])


def test_invalid_transfer_still_stops_despite_audit_only_error_thresholds():
    import pytest
    from drying.stages import Stage_ProjectState
    mesh=(np.linspace(0,1,5),np.array([0.,1.]))
    state=np.ones((2,4,1)); state[0]=301.15; state[1]=-1.
    with pytest.raises(RuntimeError,match='REMESH_TRANSFER_FAILED'):
        Stage_ProjectState(state,mesh,mesh,60.)


def test_audit_policy_edits_preserve_identity_but_numerical_edits_invalidate(tmp_path):
    import shutil
    from drying.audit import Audit_GetSourceIdentity
    root=Path(__file__).resolve().parents[1]
    (tmp_path/'src/drying').mkdir(parents=True); (tmp_path/'configs').mkdir()
    target=tmp_path/'src/drying/audit.py'
    shutil.copy2(root/'src/drying/audit.py',target)
    shutil.copy2(root/'configs/audit_solver_reference.json',tmp_path/'configs/audit_solver_reference.json')
    original=Audit_GetSourceIdentity(tmp_path)
    source=target.read_text(encoding='utf-8')
    target.write_text(source.replace("value['internal_audit_veto']=False","value['internal_audit_veto']=True"),encoding='utf-8')
    assert Audit_GetSourceIdentity(tmp_path)==original
    target.write_text(source.replace('dt/6*','dt/5*'),encoding='utf-8')
    assert Audit_GetSourceIdentity(tmp_path)[0]!=original[0]
    # Aggregation/coverage code is part of the numerical audit identity too.
    target.write_text(source.replace('drift>1e-8','drift>1e-4'),encoding='utf-8')
    assert Audit_GetSourceIdentity(tmp_path)[0]!=original[0]


def test_stage_policy_edits_preserve_identity_but_transfer_edits_invalidate(tmp_path):
    import shutil
    from drying.stages import Stage_GetSourceHash
    root=Path(__file__).resolve().parents[1]
    (tmp_path/'src/drying').mkdir(parents=True); (tmp_path/'configs').mkdir()
    for name in ['stages.py','cases.py']:
        shutil.copy2(root/'src/drying'/name,tmp_path/'src/drying'/name)
    shutil.copy2(root/'configs/stage_solver_reference.json',tmp_path/'configs/stage_solver_reference.json')
    original=Stage_GetSourceHash(tmp_path);target=tmp_path/'src/drying/stages.py';source=target.read_text(encoding='utf-8')
    target.write_text(source.replace("assessment='AUDIT_ONLY',acceptance_veto=False","assessment='OTHER',acceptance_veto=True"),encoding='utf-8')
    assert Stage_GetSourceHash(tmp_path)==original
    target.write_text(source.replace('relative > 1e-12','relative > 1e-6'),encoding='utf-8')
    assert Stage_GetSourceHash(tmp_path)!=original


def test_stage_production_certificate_is_independent_of_failed_fixed_diagnostic():
    from drying.stages import Stage_AssessProduction
    trial=dict(early_reference_passed=True,stage_schedule_accuracy_passed=True,remesh_transfer_passed=True)
    result=Stage_AssessProduction(dict(spatial_passed=False),trial,True)
    assert not result['fixed_grid_spatial_passed']
    assert result['stage_schedule_spatial_passed'] and result['spatial_convergence_passed'] and result['spatial_passed']
    assert not result['candidate_only']
    for gate in trial:
        failed=Stage_AssessProduction(dict(spatial_passed=False),dict(trial,**{gate:False}),True)
        assert not failed['spatial_convergence_passed'] and not failed['stage_schedule_spatial_passed']
    assert not Stage_AssessProduction(dict(spatial_passed=False),trial,False)['spatial_convergence_passed']
    assert Stage_AssessProduction(dict(spatial_passed=True),trial,False)['spatial_convergence_passed']


def test_remesh_integrity_gate_does_not_reintroduce_internal_amplitude_veto():
    from drying.stages import Stage_ProjectState,Stage_AssessProduction
    old=(np.linspace(0,1,9),np.array([0.,1.]));new=(np.linspace(0,1,5),np.array([0.,1.]))
    state=np.stack([np.linspace(301.15,320.,8),np.linspace(2.55,.2,8)])[:,:,None]
    _,metrics=Stage_ProjectState(state,old,new,60.)
    tol=dict(temperature_abs_K=.01,moisture_abs=.01)
    check=Stage_AssessTransfers([metrics],tol)
    assert check['threshold_exceeded'] and check['remesh_transfer_passed'] and not check['acceptance_veto']
    metrics['volume_integral_relative_error_C']=1e-6
    check=Stage_AssessTransfers([metrics],tol)
    assert not check['remesh_transfer_passed']
    result=Stage_AssessProduction(dict(spatial_passed=False),dict(early_reference_passed=True,
        stage_schedule_accuracy_passed=True,remesh_transfer_passed=check['remesh_transfer_passed']),True)
    assert not result['spatial_convergence_passed']
