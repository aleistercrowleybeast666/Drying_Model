"""Physical routing, weighted response timing and final publication regression."""
from pathlib import Path
import numpy as np
from drying.studies.cross_spec import Cross_GetPlan
from drying.studies import trajectory

ROOT = Path(__file__).resolve().parents[1]


def test_cross_has_independent_identity_and_own_refinements():
    production, reference, half = Cross_GetPlan(ROOT)
    assert production['case'] == 'q23' and production['material_appendix'] == 3
    assert production['shrink'] and production['mode'] == 'M00'
    assert all(2*a['nr'] == b['nr'] and a['t_start'] == b['t_start']
               and a['t_end'] == b['t_end'] for a, b in zip(production['schedule'], reference['schedule']))
    assert half['replay'] == production['experiment_id']
    assert half['dt_max_s'] == .125 and production['dt_max_s'] == .25
    assert len({s['experiment_id'] for s in [production, reference, half]}) == 3


def test_cross_parameters_reach_real_original_kernel(monkeypatch):
    spec = Cross_GetPlan(ROOT)[0]
    mesh = trajectory.Trajectory_GetMesh(ROOT, spec, spec['schedule'][0])
    state = np.empty((2, len(mesh[0])-1, 1))
    state[0] = spec['physics']['T0_K']
    state[1] = spec['physics']['C0']
    real = trajectory.Rk4_Advance
    observed = []
    def Capture(*args):
        observed.append(args)
        return real(*args)
    monkeypatch.setattr(trajectory, 'Rk4_Advance', Capture)
    result = trajectory.Trajectory_GetAdvance(ROOT, spec, mesh)(state, 0., 1.)
    assert observed[0][4] == 3 and observed[0][8] is True
    assert observed[0][9] is False and result[1] == 1. and result[4] == 0
    assert not np.array_equal(result[0], state)
    wrong = list(observed[0]);wrong[4] = 4
    assert not np.allclose(result[0], real(*wrong)[0], rtol=0., atol=1e-10)
from drying.studies.kinetics import Kinetics_GetVolumeMeans, Kinetics_GetHalfResponse, Kinetics_GetRadiusPeaks
from drying.studies.technical_analysis import Technical_GetQualifiedFraction


def test_volume_mean_uses_annular_and_axial_volumes_at_actual_radius():
    state=np.array([[[10.,20.],[30.,40.]],[[1.,2.],[3.,4.]]])
    mesh=(np.array([0.,.5,1.]),np.array([0.,.2,1.]))
    weights=np.array([[.05,.2],[.15,.6]])
    expected=(state*weights[None,:,:]).sum(axis=(1,2))
    for radius in [.02,.012]:
        assert np.allclose(Kinetics_GetVolumeMeans(state,mesh,radius),expected)
    assert not np.allclose(expected,state.mean(axis=(1,2)))


def test_half_response_uses_earliest_crossing_and_handles_zero_change():
    t=np.array([0.,2.,4.,6.]);y=np.array([0.,6.,2.,10.])
    result=Kinetics_GetHalfResponse(t,y,0.,10.)
    assert np.isclose(result['time_s'],5/3) and result['bracket_s']==[0.,2.]
    descending=Kinetics_GetHalfResponse(t,10-y,10.,0.,True)
    assert descending['time_s']==result['time_s']
    assert Kinetics_GetHalfResponse(t,np.ones(4),1.,1.)['time_s'] is None


def test_radius_maximum_keeps_full_disjoint_intervals_and_clips_window():
    source=np.array([[0.,10.],[1.,8.],[2.,6.],[3.,5.],[4.,3.]])
    rate,intervals=Kinetics_GetRadiusPeaks(source,3.5)
    assert rate==2. and intervals==[[0.,2.],[3.,3.5]]


def test_qualified_fraction_is_strict_and_integrates_multiple_crossings():
    r=np.array([0.,.5,1.])
    assert Technical_GetQualifiedFraction(r,np.full(3,.15))==0.
    assert Technical_GetQualifiedFraction(r,np.full(3,.149))==1.
    # Crossings at r=.25 and .75 give a qualifying annulus of volume fraction .5.
    assert np.isclose(Technical_GetQualifiedFraction(r,np.array([.2,.1,.2])),.5)
    # Exactly-threshold plateau carries finite volume and must remain excluded.
    assert np.isclose(Technical_GetQualifiedFraction(r,np.array([.15,.15,.1])),.75)


def test_legacy_refresh_forwards_to_narrow_technical_export(monkeypatch):
    from types import SimpleNamespace
    from drying.studies import scheduler,technical_run,plot_contract,cache
    spec=dict(experiment_id='kept',fingerprint='same')
    manifest=dict(specs={'kept':spec},statuses={'kept':dict(fingerprint='same')})
    monkeypatch.setattr(plot_contract,'StudyPlot_ReadManifest',lambda *a,**k:manifest)
    monkeypatch.setattr(scheduler,'Trajectory_GetSpec',lambda *a,**k:spec)
    checked=[];forwarded=[]
    monkeypatch.setattr(cache,'Cache_SealExperiment',lambda root,spec,status:checked.append(spec['experiment_id']))
    monkeypatch.setattr(technical_run,'Technical_Run',lambda root,args:forwarded.append(args) or technical_run.TechnicalRunResult.COMPLETE)
    args=SimpleNamespace(group='thermal',payload_only=True,resume=True)
    scheduler.Studies_RefreshFrozenExtension(ROOT,args,[dict(case='q4',kind='production')])
    assert checked==['kept'] and forwarded[0].group=='geometry_cross' and forwarded[0].payload_only
    assert args.group=='thermal'


def test_legacy_refresh_rejects_changed_base_before_export(monkeypatch):
    import pytest
    from types import SimpleNamespace
    from drying.studies import scheduler,technical_run,plot_contract
    monkeypatch.setattr(plot_contract,'StudyPlot_ReadManifest',lambda *a,**k:dict(statuses={}))
    monkeypatch.setattr(scheduler,'Trajectory_GetSpec',lambda *a,**k:dict(experiment_id='changed',fingerprint='new'))
    monkeypatch.setattr(technical_run,'Technical_Run',lambda *a:pytest.fail('must not overwrite an unmatched publication'))
    with pytest.raises(RuntimeError,match='FROZEN_STUDY_SOURCE_CHANGED'):
        scheduler.Studies_RefreshFrozenExtension(ROOT,SimpleNamespace(),[dict(case='q4',kind='production')])


def test_optional_refinement_payload_only_never_solves(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import pytest
    from drying.studies import refinement2d
    from drying.storage import Storage_WriteJson
    path=tmp_path/'work/studies/technical/refinement2d/index.json';Storage_WriteJson(path,dict(status='PARTIAL_2D'))
    monkeypatch.setattr(refinement2d,'Baseline_ReadJson',lambda path:dict(status='PARTIAL_2D'))
    monkeypatch.setattr(refinement2d,'Case_LoadConfig',lambda root:{})
    monkeypatch.setattr(refinement2d,'Case_Solve',lambda *a,**k:pytest.fail('payload-only must not solve'))
    assert int(refinement2d.Refinement_Run(tmp_path,SimpleNamespace(payload_only=True)))==0
