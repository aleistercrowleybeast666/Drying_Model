"""Scientific identities and isolation contracts for extension experiments."""
import json
from pathlib import Path
import numpy as np
import pytest
from drying.boundaries import Boundary_GetConductance
from drying.materials import Material_Evaluate
from drying.operators import Operator_Evaluate
from drying.rk4 import Rk4_Advance
from drying.stages import Stage_ProjectState
from drying.studies.baseline import Baseline_Check
from drying.studies.metrics import (Metrics_GetFront,Metrics_GetTies,Metrics_GetClock,
    Metrics_GetDrivers,Metrics_GetEndEffects,Metrics_GetDerivative,Metrics_GetThermalTime)
from drying.studies.trajectory import Trajectory_GetSpec,Trajectory_GetMesh,Trajectory_GetAdvance,Trajectory_GetNodes,Trajectory_GetInputs
from drying.studies.water import Water_Prepare,Water_LoadTable,Water_GetValue
from drying.studies.thermal import Thermal_AddOperator,Thermal_SolveBoundary,Thermal_GetKernel

ROOT=Path(__file__).resolve().parents[1]


def test_frozen_official_outputs_and_cache():
    assert Baseline_Check(ROOT)['official_workbooks_unchanged']


def test_front_edge_cases_and_nonmonotone_supremum():
    r=np.linspace(0,1,5)
    assert Metrics_GetFront(r,np.ones(5)*2,1)['status']=='ALL_WET'
    assert Metrics_GetFront(r,np.zeros(5),1)['status']=='ALL_DRY'
    row=Metrics_GetFront(r,np.array([2,1.5,.5,1.5,.5]),1)
    assert row['status']=='MULTIPLE_CROSSINGS' and row['radius_m']==pytest.approx(.875)
    assert row['wet_volume_fraction'] is None
    assert Metrics_GetFront(r,2*(1-r),1)['wet_volume_fraction']==pytest.approx(.25)


def test_uniform_maximum_reports_all_ties():
    result=Metrics_GetTies(np.linspace(0,.02,12),np.ones(12)*2.55)
    assert result['count']==12 and result['r_max_m']==.02 and not result['unique']


def test_annular_volume_fraction_not_cell_count_and_middle_depth():
    volumes=np.diff(np.array([0,.2,.7,1.])**2)[:,None]*np.array([[.03,.07,.025]])
    error=np.zeros((3,3));error[2,1]=1
    row=Metrics_GetEndEffects(error,error,volumes,np.array([.015,.065,.1125]))
    assert row['volume_fraction_T']==pytest.approx(.51*.07/.125)
    assert row['depth_T_m']==pytest.approx(.06)
    assert row['volume_fraction_T']==pytest.approx(Metrics_GetEndEffects(error,error,volumes*.36,np.array([.015,.065,.1125]))['volume_fraction_T'])


def test_clock_units_and_driver_identity():
    t=np.linspace(0,100,21);clock,check=Metrics_GetClock(t,np.ones(21)*4e-9,np.ones(21)*.02)
    assert clock[-1]==pytest.approx(.001)
    T=np.linspace(300,320,21);C=np.linspace(2.55,.2,21);R=np.linspace(.02,.012,21)
    bt,bc,br,error=Metrics_GetDrivers(T,C,R,4)
    assert error<1e-12 and bt[-1]>0 and bc[-1]<0 and br[-1]>0


def test_derivative_does_not_cross_remesh_jump():
    t=np.arange(10.);y=t.copy();y[5:]+=100
    assert np.allclose(Metrics_GetDerivative(t,y,np.r_[np.zeros(5),np.ones(5)]),1)
    assert Metrics_GetThermalTime(t,np.ones(10)*299,np.ones(10)*300,320) is None


def test_remesh_conserves_water_on_nonuniform_mesh():
    old=(np.array([0,.1,.3,.7,1.]),np.array([0,1.]));new=(np.array([0,.2,.8,1.]),old[1])
    state=np.array([[[300],[302],[310],[315]],[[2.55],[2],[1],[.3]]],dtype=float)
    projected,audit=Stage_ProjectState(state,old,new,10.)
    assert audit['volume_integral_relative_error_C']<1e-12
    assert projected[1].min()>=state[1].min()


def test_actual_parameter_kernel_regression():
    spec=Trajectory_GetSpec(ROOT,'q1');mesh=Trajectory_GetMesh(ROOT,spec,spec['schedule'][0]);p=spec['physics'];n=spec['numerics']
    u=np.empty((2,len(mesh[0])-1,1));u[0]=p['T0_K'];u[1]=p['C0']
    result=Trajectory_GetAdvance(ROOT,spec,mesh)(u,0.,.01)
    inputs=Trajectory_GetInputs(ROOT,spec)
    expected=Rk4_Advance(u,0.,.01,.25,1,*inputs,False,False,n['safety'],n['min_dt_s'],n['max_rejections'],2000000,
        min(p['T0_K'],inputs[0][:,1].min()),max(p['T0_K'],inputs[0][:,1].max()),np.empty(0),p['h'],p['hm'],p['threshold'],*mesh)
    assert np.array_equal(result[0],expected[0])
    changed=dict(spec,physics=dict(p,hm=2*p['hm'],h=2*p['h'],T0_K=305.,C0=2.2,threshold=.3))
    changed_state=u.copy();changed_state[0]=305.;changed_state[1]=2.2
    other=Trajectory_GetAdvance(ROOT,changed,mesh)(changed_state,0.,.01)
    assert not np.array_equal(other[0],result[0])
    nodes=Trajectory_GetNodes(other[0],.01,1,inputs,mesh,changed)
    assert nodes[2].shape==(2,u.shape[1]+2,3)


@pytest.fixture(scope='module')
def water():
    meta=Water_Prepare(ROOT)
    return meta,Water_LoadTable(str(ROOT/meta['table_path']),meta['table_sha256'])


def test_water_units_domain_interpolation_and_saturation_derivative(water):
    meta,(grid,hl,Lv)=water
    assert max(meta['interpolation_max_abs_J_kg'].values())<.01
    assert 2.4e6<Water_GetValue(300.,grid,Lv)[0]<2.5e6
    assert 4000<Water_GetValue(300.,grid,hl)[1]<4300
    assert np.isnan(Water_GetValue(270.,grid,hl)[0])


def test_signed_latent_flux_boundary_residual_and_real_cooling(water):
    _,(grid,hl,Lv)=water;k=.3;D=1e-8;b=300.
    for Ci,He in [(2.55,.1),(.1,2.55)]:
        Ts,Cs,jc,residual,code=Thermal_SolveBoundary(301.15,Ci,301.15,He,k,D,.001,25.,8e-7,b,True,grid,Lv)
        assert code==0 and abs(residual)<1e-7
        assert jc==pytest.approx(8e-7*(Cs-He))
        assert (Ts<301.15) if Ci>He else (Ts>301.15)
        assert abs(25*(301.15-Ts)-k*(Ts-301.15)/.001-b*jc*Water_GetValue(Ts,grid,Lv)[0])<1e-7


def test_sensible_uniform_temperature_zero_reference_shift_and_balance(water):
    _,(grid,hl,Lv)=water;nr=5;xi=np.array([0,.1,.3,.5,.8,1.]);eta=np.array([0.,1.]);R=.02
    u=np.empty((2,nr,1));u[0]=301.15;u[1,:,0]=np.linspace(2.55,.5,nr)
    props=np.empty((4,nr,1));out=np.empty_like(u);rows=np.empty_like(u)
    Operator_Evaluate(u,R,301.15,.1,3,25.,8e-7,False,out,props,rows,np.zeros(4),xi,eta)
    initial=out.copy();original_rows=rows.copy()
    Thermal_AddOperator(u,R,301.15,.1,3,25.,8e-7,xi,eta,out,props,rows,False,True,300.,R,grid,hl,Lv)
    assert np.allclose(initial,out,atol=1e-14)
    u[0,:,0]=np.linspace(300,315,nr)
    Operator_Evaluate(u,R,301.15,.1,3,25.,8e-7,False,out,props,rows,np.zeros(4),xi,eta)
    initial=out.copy();original_rows=rows.copy()
    Thermal_AddOperator(u,R,301.15,.1,3,25.,8e-7,xi,eta,out,props,rows,False,True,300.,R,grid,hl,Lv)
    shifted=initial.copy();shifted_rows=original_rows.copy()
    Thermal_AddOperator(u,R,301.15,.1,3,25.,8e-7,xi,eta,shifted,props,shifted_rows,False,True,300.,R,grid,hl+1234567.,Lv)
    assert np.allclose(out,shifted,rtol=1e-10,atol=1e-12)
    volumes=.5*np.diff((R*xi)**2)*.125
    jc=Boundary_GetConductance(props[3,-1,0],R*(1-(xi[-1]+xi[-2])/2),8e-7)*(u[1,-1,0]-.1)
    assert np.dot(volumes,out[1,:,0])==pytest.approx(-R*.125*jc,abs=1e-18)
    # Independent face sum checks the intended gradient-form effective source.
    expected=0.;r=R*xi;rc=(r[:-1]+r[1:])/2
    for i in range(nr-1):
        flux=300*r[i+1]*.125/((r[i+1]-rc[i])/props[3,i,0]+(rc[i+1]-r[i+1])/props[3,i+1,0])*(u[1,i,0]-u[1,i+1,0])
        hi=Water_GetValue(u[0,i,0],grid,hl)[0];hj=Water_GetValue(u[0,i+1,0],grid,hl)[0]
        expected+=flux*(hi-hj)
    assert np.dot(volumes*props[0,:,0]*props[1,:,0],out[0,:,0]-initial[0,:,0])==pytest.approx(expected,rel=1e-10,abs=1e-12)


def test_thermal_kernel_reuses_original_rk4_and_allows_cooling(water):
    spec=Trajectory_GetSpec(ROOT,'q1','M11');mesh=(np.linspace(0,1,9),np.array([0.,1.]))
    kernel=Thermal_GetKernel(spec)
    assert kernel.py_func.__code__ is Rk4_Advance.py_func.__code__
    u=np.empty((2,8,1));u[0]=301.15;u[1]=2.55
    result=Trajectory_GetAdvance(ROOT,spec,mesh)(u,0.,.01)
    assert result[4]==0 and result[0][0].min()<301.15


def test_gui_commands_and_mode_filter_use_actual_cli():
    import importlib.util
    module_spec=importlib.util.spec_from_file_location('drying_app',ROOT/'app.py');app=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(app)
    code,command=app.App_BuildCommand(ROOT,'studies','resume','thermal','q4','M11')
    assert code==app.AppCommandResult.READY
    assert command[2:]==['--group','thermal','--resume','--case','q4','--mode','M11']
    code,command=app.App_BuildCommand(ROOT,'studies','plot')
    assert command[-1].endswith('plot_studies.py')
    code,command=app.App_BuildCommand(ROOT,'studies','compute','geometry','q4','M10')
    assert code==app.AppCommandResult.INVALID_SELECTION and command==[]
    from types import SimpleNamespace
    from drying.studies.scheduler import Studies_GetPlan
    assert Studies_GetPlan(SimpleNamespace(group='thermal',case='q4',mode='M00'))==[]


def test_plot_entry_imports_no_solver_in_fresh_process():
    import subprocess,sys
    result=subprocess.run([sys.executable,'-c',"import plot_studies,sys;assert not any(k in sys.modules for k in ['drying.rk4','drying.cases','drying.operators','drying.studies.trajectory'])"],cwd=ROOT,capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_missing_study_payload_reports_compute_command(tmp_path):
    from drying.studies.plot_contract import StudyPlot_ReadManifest
    with pytest.raises(FileNotFoundError,match='compute_studies.py'):
        StudyPlot_ReadManifest(tmp_path)


def test_common_animation_calendar_has_early_slowdown_and_no_frozen_endpoint():
    from drying.studies.animations import StudyAnimation_GetTimes
    times=np.arange(0.,259201.,60.)
    selected=StudyAnimation_GetTimes({('q23','M00'):dict(time_s=times),('q4','M11'):dict(time_s=times)})
    assert len(selected)==200 and np.all(np.diff(selected)>0)
    assert selected[-1]==259200 and selected[119]<=.06*259200


def test_nondefault_event_threshold_reaches_actual_rk4_detection():
    from drying.sampling import Sampling_MaxMoisture
    spec=Trajectory_GetSpec(ROOT,'q23');mesh=(np.linspace(0,1,5),np.array([0.,1.]))
    u=np.empty((2,4,1));u[0]=301.15;u[1,:,0]=[.16,.15,.14,.13]
    maximum=Sampling_MaxMoisture(u,.05,*mesh)[0]
    altered=dict(spec,physics=dict(spec['physics'],threshold=maximum-1e-8))
    changed=Trajectory_GetAdvance(ROOT,altered,mesh)(u,0.,10.)
    unchanged=Trajectory_GetAdvance(ROOT,spec,mesh)(u,0.,10.)
    assert changed[6]>=0 and unchanged[6]<0


def test_thermal_disabled_flags_and_out_of_domain_boundary(water):
    _,(grid,hl,Lv)=water;u=np.empty((2,5,1));u[0,:,0]=np.linspace(300,315,5);u[1,:,0]=np.linspace(2.55,.5,5)
    xi=np.linspace(0,1,6);eta=np.array([0.,1.]);out=np.empty_like(u);props=np.empty((4,5,1));rows=np.empty_like(u)
    Operator_Evaluate(u,.02,315.,.05,3,25.,8e-7,False,out,props,rows,np.zeros(4),xi,eta);before=out.copy()
    Thermal_AddOperator(u,.02,315.,.05,3,25.,8e-7,xi,eta,out,props,rows,False,False,300.,.02,grid,hl,Lv)
    assert np.array_equal(out,before)
    result=Thermal_SolveBoundary(250.,2.55,250.,.05,.3,1e-8,.001,25.,8e-7,300.,True,grid,Lv)
    assert result[-1]==8 and result[0]<grid[0]


def test_baseline_cli_stops_at_safe_phase_without_touching_overview(tmp_path,monkeypatch):
    import importlib.util
    module_spec=importlib.util.spec_from_file_location('drying_compute',ROOT/'compute.py');compute=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(compute)
    (tmp_path/'work/studies').mkdir(parents=True);(tmp_path/'work/studies/BASELINE_STOP').write_text('test',encoding='utf-8')
    (tmp_path/'results').mkdir();overview=tmp_path/'results/overview.md';overview.write_text('preserved official results',encoding='utf-8')
    monkeypatch.setattr(compute,'_ROOT',tmp_path)
    import sys
    monkeypatch.setattr(sys,'argv',['compute.py'])
    assert compute.Compute_Main()==2
    assert overview.read_text(encoding='utf-8')=='preserved official results'
    assert json.loads((tmp_path/'work/diagnostics/compute_status.json').read_text(encoding='utf-8'))['status']=='STOPPED'


def test_sealed_experiment_rejects_changed_cache(tmp_path):
    from drying.studies.cache import Cache_SealExperiment
    from drying.storage import Storage_WriteJson
    spec=dict(experiment_id='test_cache',fingerprint='full-fingerprint')
    folder=tmp_path/'work/studies/experiments/test_cache';folder.mkdir(parents=True)
    status=dict(fingerprint=spec['fingerprint'],complete=True,chunks=['chunk_0.npz'],event=None)
    Storage_WriteJson(folder/'spec.json',spec);Storage_WriteJson(folder/'status.json',status)
    (folder/'chunk_0.npz').write_bytes(b'original numeric bytes');(folder/'checkpoint.npz').write_bytes(b'checkpoint bytes')
    result=Cache_SealExperiment(tmp_path,spec,status)
    assert result['data_files']
    (folder/'chunk_0.npz').write_bytes(b'changed numeric bytes')
    with pytest.raises(RuntimeError,match='STUDY_CACHE_MISMATCH'):Cache_SealExperiment(tmp_path,spec,status)


def test_stage_classification_does_not_force_three_stages():
    from drying.studies.metrics import Metrics_GetStages
    rule=dict(endpoint_window_fraction=.1,minimum_peak_contrast_fraction=.15,minimum_samples=6)
    t=np.linspace(0,10,101)
    hump=Metrics_GetStages(t,np.exp(-(t-5)**2),rule)
    declining=Metrics_GetStages(t,np.exp(-t),rule)
    assert hump['three_stage'] and hump['peak_time_s']==5
    assert not declining['three_stage'] and not declining['rising_limb_identified']
    assert not Metrics_GetStages(t,np.exp(-(t-5)**2),rule,end_s=3)['three_stage']
    with pytest.raises(ValueError,match='INVALID_STAGE'):Metrics_GetStages(t,t,dict(rule,endpoint_window_fraction=.6))


def test_stage_classification_keeps_short_resolved_rise_before_long_tail():
    from drying.studies.metrics import Metrics_GetStages
    t=np.arange(1001,dtype=float);rate=np.exp(-((t-20)/10)**2)
    result=Metrics_GetStages(t,rate,dict(endpoint_window_fraction=.1,minimum_peak_contrast_fraction=.15,minimum_samples=6))
    assert result['three_stage'] and result['peak_time_s']==20
    assert result['initial_rate_window_end_s']<result['peak_time_s']<result['final_rate_window_start_s']


def test_series_preserves_real_requested_event_state(tmp_path,monkeypatch):
    from drying.studies import analysis
    from drying.studies.trajectory import Trajectory_GetSpec
    spec=Trajectory_GetSpec(ROOT,'q1');spec['experiment_id']='event_sample_test'
    mesh=(np.linspace(0,1,5),np.array([0.,1.]));u=np.empty((2,4,1));u[0]=301.15;u[1]=2.55
    samples=[(float(t),u.copy(),mesh) for t in [0,1,2,3]]
    event_state=u.copy();event_state[0]=300.8;event_state[1]=2.2
    calls=[]
    monkeypatch.setattr(analysis,'Trajectory_Iter',lambda root,key:iter(samples))
    def ActualEvent(root,spec,target):calls.append(target);return event_state,mesh
    monkeypatch.setattr(analysis,'Trajectory_GetState',ActualEvent)
    inputs=analysis.Trajectory_GetInputs(ROOT,spec)
    monkeypatch.setattr(analysis,'Trajectory_GetInputs',lambda root,spec:inputs)
    entry=analysis.Analysis_ExtractSeries(tmp_path,spec,extra_times=[1.5])
    data=analysis.Analysis_LoadSeries(tmp_path,entry);i=np.searchsorted(data['time_s'],1.5)
    assert calls==[1.5] and data['Tcenter_K'][i]==pytest.approx(300.8) and data['Ccenter'][i]==pytest.approx(2.2)
    assert entry['exact_event_times_s']==[1.5]


def test_equivalent_role_reuse_checks_all_effective_settings(tmp_path):
    from drying.studies.cache import Cache_ReuseEquivalent
    from drying.storage import Storage_WriteJson,Storage_WriteArray
    source=dict(experiment_id='reference',fingerprint='old',kind='full_reference',physics=dict(h=25),schedule=[400,320,160,80],source=dict(kernel='same'))
    target=dict(source,experiment_id='production',fingerprint='new',kind='production')
    folder=tmp_path/'work/studies/experiments/reference';folder.mkdir(parents=True)
    status=dict(experiment_id='reference',fingerprint='old',complete=True,chunks=['chunk_0.npz'],event=None,wall_s=12.)
    Storage_WriteJson(folder/'spec.json',source);Storage_WriteJson(folder/'status.json',status)
    fields=np.arange(16,dtype=float).reshape(2,4,2)
    Storage_WriteArray(folder/'chunk_0.npz',fields=fields,time_s=np.array([0.,1.]),fingerprint=np.asarray('old'))
    Storage_WriteArray(folder/'checkpoint.npz',state=fields[-1],time_s=1.)
    assert Cache_ReuseEquivalent(tmp_path,dict(target,physics=dict(h=24)),{'reference':status}) is None
    result=Cache_ReuseEquivalent(tmp_path,target,{'reference':status})
    assert result['reuse']['numerical_arrays_bitwise_equal'] and result['wall_s']==0
    with np.load(tmp_path/'work/studies/experiments/production/chunk_0.npz') as data:
        assert str(data['fingerprint'])=='new' and np.array_equal(data['fields'],fields)


def test_dry_run_lists_missing_inputs_without_creating_cache(tmp_path,capsys):
    from types import SimpleNamespace
    from drying.studies.scheduler import Studies_Run
    Studies_Run(tmp_path,SimpleNamespace(dry_run=True,group='thermal',case='q1',mode='M10'))
    report=json.loads(capsys.readouterr().out)
    assert report['read_only'] and report['missing_inputs'] and len(report['jobs'])==3
    assert not list(tmp_path.iterdir())


def test_exact_own_event_uses_saved_event_locator_state(tmp_path,monkeypatch):
    from drying.studies import analysis
    from drying.storage import Storage_WriteArray
    spec=dict(case='q4',experiment_id='own_event');folder=tmp_path/'work/studies/experiments/own_event';folder.mkdir(parents=True)
    state=np.arange(8.).reshape(2,4,1);xi=np.linspace(0,1,5);eta=np.array([0.,1.])
    Storage_WriteArray(folder/'event.npz',state=state,time_s=12.345,xi_faces=xi,eta_faces=eta)
    def Forbidden(*args):raise AssertionError('own event must not be independently resampled')
    monkeypatch.setattr(analysis,'Trajectory_GetState',Forbidden)
    result,mesh=analysis.Analysis_GetExactState(tmp_path,spec,12.345)
    assert np.array_equal(result,state) and np.array_equal(mesh[0],xi)
