"""Build explicit scientific payloads from complete, identified trajectories."""
import hashlib
import json
from itertools import chain
from pathlib import Path
import numpy as np
from ..geometry import Geometry_GetCells
from ..inputs import Input_AtTime
from ..materials import Material_Evaluate
from ..sampling import Sampling_GetNodes
from ..storage import Storage_WriteArray, Storage_WriteJson
from .baseline import Baseline_ReadJson, Baseline_HashFile
from .trajectory import (Trajectory_GetSpec,Trajectory_Iter,Trajectory_IterBaseline,Trajectory_GetNodes,
    Trajectory_GetInputs,Trajectory_GetState,Trajectory_GetAdvance)
from .metrics import (Metrics_GetFront,Metrics_GetTies,Metrics_GetDerivative,Metrics_GetClock,
    Metrics_GetDrivers,Metrics_GetThermalTime,Metrics_GetEndEffects,Metrics_GetEventSensitivity)


def Analysis_ExtractSeries(root,spec,baseline=False,extra_times=()):
    root=Path(root);source_id=spec['experiment_id'];folder=root/'work/studies/plot_payload';folder.mkdir(parents=True,exist_ok=True)
    file=folder/f'{source_id}_series.npz';meta=file.with_suffix('.json')
    extra_times=sorted(set(float(t) for t in extra_times))
    analysis_hash=Baseline_HashFile(Path(__file__)) + Baseline_HashFile(Path(__file__).with_name('metrics.py')) + json.dumps(extra_times)
    if file.exists() and meta.exists():
        saved=Baseline_ReadJson(meta)
        if saved['analysis_hash']==analysis_hash and saved['sha256']==Baseline_HashFile(file):return saved
    source=Trajectory_IterBaseline(root,spec['case']) if baseline else Trajectory_Iter(root,source_id)
    def EventStates():
        for target in extra_times:
            state,mesh=Analysis_GetExactState(root,spec,target,baseline)
            yield target,state,mesh
    source=chain(source,EventStates())
    inputs=Trajectory_GetInputs(root,spec);model={'q1':1,'q23':3,'q4':4}[spec['case']]
    records={};profiles={};radial={};fronts={};front_status={};tie_rows={};stages={}
    for t,state,mesh in source:
        r,z,values=Trajectory_GetNodes(state,t,model,inputs,mesh,spec)
        weights=np.diff(mesh[0]**2);D=np.array([Material_Evaluate(model,T,C)[3] for T,C in zip(state[0,:,0],state[1,:,0])])
        C=values[1,:,0];T=values[0,:,0];ties=Metrics_GetTies(r,C)
        center_D=Material_Evaluate(model,T[0],C[0])[3]
        records[t]=[t,r[-1],T.min(),T.max(),C.max(),np.dot(weights,state[1,:,0]),np.dot(weights,D),center_D,
                    T[0],C[0],np.interp(.5*r[-1],r,T),np.interp(.5*r[-1],r,C)]
        if spec['kind']=='production':
            xi=np.linspace(0,1,201);profiles[t]=np.array([np.interp(xi*r[-1],r,field) for field in [T,C]])
        positions=np.r_[np.arange(21)*.001,r[-1]];positions[positions>r[-1]+1e-14]=np.nan
        radial[t]=np.array([np.interp(positions,r,field) for field in [T,C]])
        f=[Metrics_GetFront(r,C,threshold) for threshold in [2.,1.,.5,.15]]
        fronts[t]=[[row['radius_m'],row['relative_radius'],np.nan if row['wet_volume_fraction'] is None else row['wet_volume_fraction']] for row in f]
        front_status[t]=[row['status'] for row in f];tie_rows[t]=[ties['count'],ties['r_min_m'],ties['r_max_m']]
        stages[t]=state.shape[1]
    times=np.array(sorted(records));data=np.array([records[t] for t in times])
    names=['time_s','radius_m','Tmin_K','Tmax_K','Cmax','Cmean','Dmean_m2_s','Dcenter_m2_s','Tcenter_K','Ccenter','Tmid_K','Cmid']
    arrays={name:data[:,i] for i,name in enumerate(names)}
    arrays.update(radial=np.array([radial[t] for t in times]),
        fronts=np.array([fronts[t] for t in times]),front_status=np.array([front_status[t] for t in times]),
        ties=np.array([tie_rows[t] for t in times]),stage_nr=np.array([stages[t] for t in times]),xi=np.linspace(0,1,201))
    if profiles:arrays['profile']=np.array([profiles[t] for t in times])
    for key in ['Cmax','Cmean']:arrays['loss_'+key+'_s']= -Metrics_GetDerivative(times,arrays[key],arrays['stage_nr'])
    arrays['theta_V'],clock=Metrics_GetClock(times,arrays['Dmean_m2_s'],arrays['radius_m'])
    arrays['theta_c'],clock_center=Metrics_GetClock(times,arrays['Dcenter_m2_s'],arrays['radius_m'])
    driver_error=0.
    if model!=1:
        for place in ['center','mid']:
            bt,bc,br,err=Metrics_GetDrivers(arrays[f'T{place}_K'],arrays[f'C{place}'],arrays['radius_m'],model)
            arrays['drivers_'+place]=np.c_[bt,bc,br];driver_error=max(driver_error,err)
            T=arrays[f'T{place}_K'];C=arrays[f'C{place}'];R=arrays['radius_m'];a=.45 if model==3 else .30
            direct=(-a/C-3850./T)-(-a/C[0]-3850./T[0])+2*np.log(R[0]/R)
            arrays['drivers_residual_'+place]=bt+bc+br-direct
    radius_input=inputs[1];slopes=np.diff(radius_input[:,1])/np.diff(radius_input[:,0])
    interval=np.clip(np.searchsorted(radius_input[:,0],times,side='right')-1,0,len(slopes)-1)
    arrays['radius_rate_m_s']=slopes[interval] if spec['shrink'] else np.zeros(len(times))
    Storage_WriteArray(file,**arrays)
    tt=Metrics_GetThermalTime(times,arrays['Tmin_K'],arrays['Tmax_K'],inputs[2][0]) if spec['mode']=='M00' else None
    metadata=dict(experiment_id=source_id,case=spec['case'],mode=spec['mode'],kind=spec['kind'],baseline=baseline,
        path=file.relative_to(root).as_posix(),sha256=Baseline_HashFile(file),analysis_hash=analysis_hash,
        time_range_s=[float(times[0]),float(times[-1])],sample_count=len(times),clock_quadrature=clock,clock_center_quadrature=clock_center,
        drivers_identity_error=driver_error,thermal_equilibration_time_s=tt,
        thermal_equilibration_status='REACHED' if tt is not None else 'NOT_REACHED_IN_OBSERVATION' if spec['mode']=='M00' else 'NOT_APPLICABLE_TO_HEATED_MODES',
        thermal_equilibration_scope='whole valid observation through cap; env criterion M00 only',
        derivative_method='np.gradient on real timestamps separately within each grid stage; no display smoothing',
        front_thresholds=[2.,1.,.5,.15],front_volume_meaning='wet geometric volume for monotone core; not water mass',
        exact_event_times_s=extra_times,event_state_source='genuine state/reintegration; no time interpolation or endpoint freezing',
        tied_maximum_tolerance=1e-9,profile_resampling='201 xi points for visualization only; metrics on full FV/reconstructed nodes')
    Storage_WriteJson(meta,metadata);return metadata


def Analysis_LoadSeries(root,entry):
    with np.load(Path(root)/entry['path']) as data:return {k:data[k].copy() for k in data.files}


def Analysis_GetBaselineSpec(root,case):
    frozen=Baseline_ReadJson(Path(root)/'work/baseline_snapshot/baseline_manifest.json')
    selected=frozen['selected'][case+'_1d'];spec=Trajectory_GetSpec(root,case)
    adapter=spec['source']
    spec.update(experiment_id=selected['case_id'],fingerprint=selected['fingerprint'],
        source=dict(frozen_numerical_core_hash=frozen['numerical_core_hash']),analysis_adapter_source=adapter,
        origin='frozen original production; adapter does not define the original solve identity')
    return spec


def Analysis_DescribePayload(root,manifest):
    entries=list(manifest['series'].values())+manifest['end_effects']+manifest.get('counterfactuals',[])+manifest.get('interactions',[])
    entries += [dict(path=c['series_path'],sha256=c['series_sha256']) for c in manifest['checks']]
    result={}
    for entry in entries:
        if entry['path'] in result:continue
        arrays={}
        with np.load(Path(root)/entry['path']) as data:
            for name in data.files:
                a=data[name];unit='dimensionless'
                if name=='time_s':unit='s'
                elif name in ['radial','profile']:unit=['K','kg/kg']
                elif name=='fronts':unit=['m','dimensionless','dimensionless']
                elif name=='ties':unit=['count','m','m']
                elif name.endswith('_m_s'):unit='m/s'
                elif name.endswith('_m2_s'):unit='m²/s'
                elif name.endswith('_m'):unit='m'
                elif name.endswith('_K') or name=='abs_T_K' or name.endswith('_T'):unit='K'
                elif name.startswith('loss_'):unit='(kg/kg)/s'
                elif name.startswith(('Cmax','Cmean','Ccenter','Cmid','base_C','control_C','delta_C')) or name in ['abs_C','max_abs_C','official_1d_vs_2d_max_C']:unit='kg/kg'
                elif name in ['front_status']:unit='categorical'
                axes=['time'] if a.ndim==1 and name!='xi' else ['xi'] if name=='xi' else ['time','field(T,C)','radial_position'] if name in ['profile','radial'] else ['time','threshold','front_metric'] if name=='fronts' else ['time','component']
                arrays[name]=dict(shape=list(a.shape),dtype=str(a.dtype),units=unit,axes=axes)
        result[entry['path']]=dict(path=entry['path'],sha256=entry['sha256'],arrays=arrays)
    return list(result.values())


def Analysis_GetBaselineState(root,case,target):
    previous=None
    for t,state,mesh in Trajectory_IterBaseline(root,case):
        if t>target+1e-8:break
        previous=(t,state,mesh)
        if abs(t-target)<1e-8:return state,mesh
    if previous is None:raise RuntimeError('STUDY_REFERENCE_INCOMPLETE')
    t,state,mesh=previous;spec=Analysis_GetBaselineSpec(root,case)
    return Trajectory_GetAdvance(root,spec,mesh)(state,t,target)[0],mesh


def Analysis_GetExactState(root,spec,target,baseline=False):
    """Use the exact saved Event_Locate state at an own event; integrate other times."""
    root=Path(root)
    if baseline:
        frozen=Baseline_ReadJson(root/'work/baseline_snapshot/baseline_manifest.json')
        key=frozen['selected'][spec['case']+'_1d']['case_id'];folder=root/'work/cache'/key
    else:folder=root/'work/studies/experiments'/spec['experiment_id']
    event_file=folder/'event.npz'
    if event_file.exists():
        with np.load(event_file) as data:
            if abs(float(data['time_s'])-target)<1e-8:
                state=data['state'].copy()
                if 'xi_faces' in data:mesh=(data['xi_faces'].copy(),data['eta_faces'].copy())
                else:
                    from ..cases import Case_LoadMesh
                    mesh=Case_LoadMesh(root,key,target)
                return state,mesh
    return Analysis_GetBaselineState(root,spec['case'],target) if baseline else Trajectory_GetState(root,spec,target)


def Analysis_Compare(root,left_spec,right_spec,left_entry,right_entry,left_status,right_status,left_baseline=False):
    left=Analysis_LoadSeries(root,left_entry);right=Analysis_LoadSeries(root,right_entry)
    common,li,ri=np.intersect1d(left['time_s'],right['time_s'],return_indices=True)
    delta=np.abs(left['radial'][li]-right['radial'][ri])
    row_T=np.nanmax(delta[:,0,:],axis=1);row_C=np.nanmax(delta[:,1,:],axis=1)
    event_rows=[];model={'q1':1,'q23':3,'q4':4}[left_spec['case']]
    for event in [left_status.get('event'),right_status.get('event')]:
        if not event:continue
        target=event['report_s'];states=[];maximums=[]
        for spec,is_baseline in [(left_spec,left_baseline),(right_spec,False)]:
            state,mesh=Analysis_GetExactState(root,spec,target,is_baseline)
            r,z,node=Trajectory_GetNodes(state,target,model,Trajectory_GetInputs(root,spec),mesh,spec)
            maximums.append(float(np.max(node[1])))
            positions=np.r_[np.arange(21)*.001,r[-1]];positions=positions[positions<=r[-1]+1e-14]
            states.append(np.array([np.interp(positions,r,node[f,:,0]) for f in [0,1]]))
        errors=np.max(np.abs(states[0]-states[1]),axis=1)
        event_rows.append(dict(time_s=target,T_K=float(errors[0]),C=float(errors[1]),
            Cmax=float(abs(maximums[0]-maximums[1])),
            source='genuine reintegration to exact common physical time'))
    maxT=max([float(np.max(row_T))]+[v['T_K'] for v in event_rows]);maxC=max([float(np.max(row_C))]+[v['C'] for v in event_rows])
    lt=left_status.get('drying_time_h');rt=right_status.get('drying_time_h')
    event_relative=abs(lt-rt)/rt if lt is not None and rt is not None else None
    event_delta_s=abs(lt-rt)*3600 if event_relative is not None else None
    half=right_spec['kind']=='time_half';threshold_T=.001 if half else .01;threshold_C=1e-5 if half else .01
    time_ok=(event_delta_s<=1.) if half and event_delta_s is not None else (event_relative<=.002) if event_relative is not None else left_spec['case']=='q1'
    grid_factor=1 if half else 2
    pair_ok=len(left_spec['schedule'])==len(right_spec['schedule']) and all(
        a['t_start']==b['t_start'] and a['t_end']==b['t_end'] and grid_factor*a['nr']==b['nr']
        for a,b in zip(left_spec['schedule'],right_spec['schedule']))
    pair_ok=pair_ok and all(left_spec[k]==right_spec[k] for k in ['case','mode','physics','tail_minutes','shrink','monitor_hash'])
    if half:pair_ok=pair_ok and right_spec['replay']==left_spec['experiment_id']
    history_ok=right_status.get('full_history_verified',False) and common[0]==0. and common[-1]==right_spec['schedule'][-1]['t_end'] and pair_ok
    passed=maxT<=threshold_T and maxC<=threshold_C and time_ok and history_ok
    check=dict(case=left_spec['case'],mode=left_spec['mode'],reference_id=right_spec['experiment_id'],production_id=left_spec['experiment_id'],
        status='PASS' if passed else 'FAIL',full_schedule_reference_passed=bool(passed) if not half else None,
        time_half_passed=bool(passed) if half else None,max_abs_T_K=maxT,max_abs_C=maxC,
        max_abs_Cmax=max([float(np.max(np.abs(left['Cmax'][li]-right['Cmax'][ri])))]+[e['Cmax'] for e in event_rows]),
        event_relative=event_relative,event_delta_s=event_delta_s,
        thresholds=dict(T_K=threshold_T,C=threshold_C,event_s=1. if half else None,event_relative=None if half else .002),
        common_output_count=len(common),common_time_range_s=[float(common[0]),float(common[-1])],events=event_rows,
        full_history_verified=right_status.get('full_history_verified',False),reference_pairing_verified=bool(pair_ok),
        reference_schedule=right_spec['schedule'],production_schedule=left_spec['schedule'],
        scope='formal output times plus both genuinely integrated event times; internal audit is diagnostic only',
        official_M00_status_unchanged=True)
    path=Path(root)/'work/studies/validation'/f"{right_spec['experiment_id']}_comparison.npz"
    Storage_WriteArray(path,time_s=common,abs_T_K=row_T,abs_C=row_C)
    check['series_path']=path.relative_to(root).as_posix();check['series_sha256']=Baseline_HashFile(path)
    Storage_WriteJson(path.with_suffix('.json'),check)
    return check


def Analysis_EndEffects(root,case,matched_spec,matched_entry,official_entry):
    model={'q1':1,'q23':3,'q4':4}[case];inputs=Trajectory_GetInputs(root,matched_spec)
    matched_states={t:(state,mesh) for t,state,mesh in Trajectory_Iter(root,matched_spec['experiment_id'])}
    official_states={t:(state,mesh) for t,state,mesh in Trajectory_IterBaseline(root,case)}
    baseline=Baseline_ReadJson(Path(root)/'work/baseline_snapshot/baseline_manifest.json')
    selected_2d=baseline['selected'][case+'_2d'];event=selected_2d.get('event');event_samples=[]
    if event:
        from ..cases import Case_LoadMesh
        target=event['report_s'];path=Path(root)/'work/cache'/selected_2d['case_id']/'event.npz'
        with np.load(path) as data:
            if abs(float(data['time_s'])-target)>1e-8:raise RuntimeError('STUDY_REFERENCE_INCOMPLETE: mismatched frozen 2D event')
            event_samples.append((target,data['state'].copy(),Case_LoadMesh(root,selected_2d['case_id'])))
        matched_states[target]=Analysis_GetExactState(root,matched_spec,target)
        official_states[target]=Analysis_GetBaselineState(root,case,target)
    rows=[]
    for t,state,mesh in chain(Trajectory_IterBaseline(root,case,2),event_samples):
        if t not in matched_states:continue
        one,one_mesh=matched_states[t];R=Input_AtTime(t,*inputs,case=='q4')[2]
        rc,zc,volumes=Geometry_GetCells(state.shape[1],state.shape[2],R,mesh=mesh)
        # Same radial FV grid: no interpolation of the matched cell averages.
        if not np.array_equal(mesh[0],one_mesh[0]):raise RuntimeError('MATCHED_DIMENSION_REFERENCE_MISSING')
        errors=state-one[:,:,:1];metrics=Metrics_GetEndEffects(errors[0],errors[1],volumes,zc)
        # Midplane is reconstructed explicitly for detecting no unaffected middle.
        r,z,nodes=Sampling_GetNodes(state,t,model,inputs,mesh)
        tied=np.argwhere(np.abs(nodes[1]-np.max(nodes[1]))<=1e-9)
        metrics.update(Cmax=float(np.max(nodes[1])),max_tie_count=len(tied),max_r_min_m=float(r[tied[:,0]].min()),
            max_r_max_m=float(r[tied[:,0]].max()),max_z_min_m=float(z[tied[:,1]].min()),max_z_max_m=float(z[tied[:,1]].max()))
        rr,zz,onodes=Trajectory_GetNodes(one,t,model,inputs,one_mesh,matched_spec)
        for field,key,eps in [(0,'T',.2),(1,'C',.003)]:
            if np.any(np.abs(nodes[field,:,0]-onodes[field,:,0])>eps):
                metrics[f'depth_{key}_m']=.125;metrics[f'middle_affected_{key}']=True
        if t in official_states:
            high_state,high_mesh=official_states[t]
            high_r,_,high_nodes=Trajectory_GetNodes(high_state,t,model,inputs,high_mesh,matched_spec)
            for f,key in [(0,'T'),(1,'C')]:
                high=np.interp(rc,high_r,high_nodes[f,:,0])
                metrics[f'official_1d_vs_2d_max_{key}']=float(np.max(np.abs(state[f]-high[:,None])))
        rows.append(dict(case=case,time_s=t,**metrics))
    rows=sorted({row['time_s']:row for row in rows}.values(),key=lambda row:row['time_s'])
    path=Path(root)/f'work/studies/plot_payload/{case}_end_effects.npz'
    numeric={key:np.array([r.get(key,np.nan) for r in rows]) for key in rows[0] if key!='case'}
    Storage_WriteArray(path,**numeric)
    nearby=[row for row in rows if event and event['report_s']-1800<=row['time_s']<=event['report_s']]
    control=dict(control_tolerance_kg_kg=1e-9,control_representative_rule='full tied coordinate range; z=0 is midplane',
        event_control_status='STABLE_MIDPLANE_CENTER' if nearby and all(row['max_r_max_m']<=1e-6 and row['max_z_max_m']<=1e-6 for row in nearby) else 'TIED_OR_NOT_CENTER' if nearby else 'NO_EVENT_NEIGHBORHOOD',
        control_check_window_s=1800.,control_checked_samples=len(nearby))
    result=dict(case=case,question='Q1' if case=='q1' else 'Q3' if case=='q23' else 'Q4',
        path=path.relative_to(root).as_posix(),sha256=Baseline_HashFile(path),status='PARTIAL_2D',
        matched_1d_id=matched_entry['experiment_id'],official_1d_id=official_entry['experiment_id'],frozen_2d_id=selected_2d['case_id'],
        resolution=dict(nr=len(mesh[0])-1,nz=len(mesh[1])-1),thresholds=dict(T_K=.2,C=.003),
        time_range_s=[rows[0]['time_s'],rows[-1]['time_s']],**control,
        exact_event_times_s=[event['report_s']] if event else [],event_source='frozen true 2D event field plus genuine matched 1D state',
        max_depth_T_m=max(r['depth_T_m'] for r in rows),max_depth_C_m=max(r['depth_C_m'] for r in rows),
        max_volume_fraction_T=max(r['volume_fraction_T'] for r in rows),max_volume_fraction_C=max(r['volume_fraction_C'] for r in rows),
        interpretation='dimension difference at matched radial FV resolution; not experimental validation; 2D refinement remains partial')
    for key in ['depth_T_m','depth_C_m','volume_fraction_T','volume_fraction_C']:
        result['peak_'+key+'_time_s']=max(rows,key=lambda row:row[key])['time_s']
    return result


def Analysis_GetExpectedIds(root):
    """Resolve the explicit current plan, including source/config fingerprints."""
    from types import SimpleNamespace
    from .scheduler import Studies_GetPlan
    expected=[]
    for job in Studies_GetPlan(SimpleNamespace(group='all',case=None,mode=None)):
        job=dict(job)
        try:
            if job['kind']=='time_half':
                job['replay']=Trajectory_GetSpec(root,job['case'],job.get('mode','M00'),factor=job.get('factor',1))['experiment_id']
            expected.append(Trajectory_GetSpec(root,**job)['experiment_id'])
        except (ImportError,FileNotFoundError,RuntimeError):
            expected.append(f"{job['case']}_{job.get('mode','M00')}_{job['kind']}_SPEC_FAILED")
    return expected


def Studies_Summarize(root,index):
    root=Path(root);baseline=Baseline_ReadJson(root/'work/baseline_snapshot/baseline_manifest.json')
    manifest=dict(schema_version=2,baseline_id=baseline['baseline_id'],series={},checks=[],end_effects=[],thermal_audits=[],remesh_front_audits=[],experiments=index['experiments'])
    specs={};statuses={};baseline_keys={}
    for case in ['q1','q23','q4']:
        spec=Analysis_GetBaselineSpec(root,case)
        key=spec['experiment_id'];baseline_keys[case]=key;specs[key]=spec;statuses[key]=baseline['selected'][case+'_1d']
        from .audit import Audit_CheckBaselineRemesh
        manifest['remesh_front_audits'].append(Audit_CheckBaselineRemesh(root,spec,statuses[key]))
    # Only explicit current-code/config identities are exposed; old complete caches remain history.
    expected=Analysis_GetExpectedIds(root)
    current={}
    for key,result in index['experiments'].items():
        if key not in expected or not result.get('complete'):continue
        spec=Baseline_ReadJson(root/'work/studies/experiments'/key/'spec.json')
        from .cache import Cache_SealExperiment
        result=Cache_SealExperiment(root,spec,result);index['experiments'][key]=result
        if spec['mode']!='M00':
            from .selection import Selection_GetFactor
            factor=Selection_GetFactor(root,spec['case'],spec['mode'])*(2 if spec['kind']=='full_reference' else 1)
            source_schedule=baseline['selected'][spec['case']+'_1d']['schedule']
            if any(a['nr']!=b['nr']*factor for a,b in zip(spec['schedule'],source_schedule)):continue
        identity=(spec['case'],spec['mode'],spec['kind'],spec['tail_minutes'])
        current[identity]=(key,spec,result)
    events={case:[] for case in baseline_keys}
    for key,status in statuses.items():
        if status.get('event'):events[specs[key]['case']].append(status['event']['report_s'])
    for key,spec,result in current.values():
        if spec['kind'] in ['production','fixed_radius','tail','matched'] and result.get('event'):events[spec['case']].append(result['event']['report_s'])
    for case,key in baseline_keys.items():
        print('STUDY_SERIES frozen '+case,flush=True)
        manifest['series'][key]=Analysis_ExtractSeries(root,specs[key],baseline=True,extra_times=events[case])
    for key,spec,result in current.values():
        print('STUDY_SERIES '+key,flush=True)
        own_events=[result['event']['report_s']] if result.get('event') else []
        specs[key]=spec;statuses[key]=result
        common_event_times=events[spec['case']] if spec['kind'] in ['production','fixed_radius','tail'] else own_events
        manifest['series'][key]=Analysis_ExtractSeries(root,spec,extra_times=common_event_times)
    for key,spec,result in current.values():
        case=spec['case'];mode=spec['mode'];kind=spec['kind']
        print('STUDY_EVIDENCE '+key,flush=True)
        if mode!='M00':
            from .audit import Audit_CheckThermal
            try:manifest['thermal_audits'].append(Audit_CheckThermal(root,spec))
            except Exception as exc:
                import traceback
                failure=dict(experiment_id=key,case=case,mode=mode,status='THERMAL_BALANCE_CHECK_FAILED',error=str(exc),traceback=traceback.format_exc())
                manifest['thermal_audits'].append(failure)
                Storage_WriteJson(root/'work/studies/diagnostics'/f'{key}_audit_failure.json',failure)
        if kind in ['full_reference','time_half']:
            target=baseline_keys[case] if mode=='M00' else current.get((case,mode,'production',60),(None,))[0]
            if target:
                manifest['checks'].append(Analysis_Compare(root,specs[target],spec,manifest['series'][target],manifest['series'][key],
                    statuses[target],result,left_baseline=mode=='M00'))
        if kind=='matched':
            effect=Analysis_EndEffects(root,case,spec,manifest['series'][key],manifest['series'][baseline_keys[case]])
            manifest['end_effects'].append(effect)
            if case=='q23':
                q2=dict(effect,question='Q2',time_range_s=[0.,10800.],event_control_status='NO_DRYING_EVENT_REQUIRED',control_checked_samples=0,exact_event_times_s=[])
                with np.load(root/effect['path']) as data:
                    keep=data['time_s']<=10800
                    for metric in ['depth_T_m','depth_C_m','volume_fraction_T','volume_fraction_C']:
                        q2['max_'+metric]=float(np.max(data[metric][keep]))
                        q2['peak_'+metric+'_time_s']=float(data['time_s'][keep][np.argmax(data[metric][keep])])
                manifest['end_effects'].append(q2)
    manifest['specs']=specs;manifest['statuses']=statuses;manifest['baseline_keys']=baseline_keys
    manifest['official_status']=baseline['status'];manifest['render_status']='OWNED_BY_RENDER_RECEIPT'
    manifest['render_receipt_path']='work/studies/diagnostics/render_manifest.json'
    # Preserve prior failed attempts as history, while current state follows exact current identities.
    for key,value in index['experiments'].items():value['role']='current' if key in expected else 'historical / superseded attempt'
    manifest['historical_checks']=[]
    for key,value in index['experiments'].items():
        path=root/'work/studies/validation'/f'{key}_comparison.json'
        if key not in expected and path.is_file():
            record=Baseline_ReadJson(path);record['role']='historical / diagnostic only; superseded supplemental mesh'
            manifest['historical_checks'].append(record)
    index['expected_experiment_ids']=expected
    index['current_complete_count']=sum(index['experiments'].get(k,{}).get('complete',False) for k in expected)
    index['expected_experiment_count']=len(expected)
    index['all_experiments_computed']=index['current_complete_count']==len(expected)
    manifest['generation_stage']='COMPUTE_PAYLOAD'
    manifest['generation_status']='COMPUTED' if index['all_experiments_computed'] else 'PARTIAL_COMPUTE'
    failed=any(c['status']!='PASS' for c in manifest['checks']+manifest['thermal_audits']+manifest['remesh_front_audits'])
    manifest['validation_status']='FAIL' if failed else 'PASS' if len(manifest['checks'])==21 and len(manifest['thermal_audits'])==27 else 'INCOMPLETE'
    Storage_WriteJson(root/'results/studies/study_index.json',index)
    # Writers may add synthesis/exports but never start a trajectory.
    from .synthesis import Synthesis_Build
    print('STUDY_SYNTHESIS_AND_EXPORT',flush=True)
    Synthesis_Build(root,manifest)
    manifest['data_files']=Analysis_DescribePayload(root,manifest)
    manifest['coordinate_definitions']=dict(radial='21 fixed positions 0..0.02 m at 0.001 m intervals plus true surface; outside material NaN',
        profile='201 uniform xi=r/R nodes, visualization only',fronts='thresholds 2,1,0.5,0.15; components rf,rf/R,wet geometric fraction',
        dimension='1D radial production/extensions; frozen 2D only for EndEffects; z=0 midplane, L=0.25 m')
    path=root/'work/studies/plot_payload/study_manifest.json'
    manifest['seal']=hashlib.sha256(json.dumps(manifest,sort_keys=True,allow_nan=False).encode()).hexdigest()
    Storage_WriteJson(path,manifest)
    Storage_WriteJson(root/'results/studies/validation_summary.json',dict(baseline_id=manifest['baseline_id'],
        generation_status=manifest['generation_status'],validation_status=manifest['validation_status'],
        current_experiment_ids=expected,checks=manifest['checks'],thermal_audits=manifest['thermal_audits'],
        remesh_front_audits=manifest['remesh_front_audits'],end_effects=manifest['end_effects'],
        historical_checks=manifest['historical_checks'],historical_role='legacy / diagnostic only'))
    from ..auxiliary2d import Auxiliary_ReadSummary, KEY
    auxiliary = Auxiliary_ReadSummary(root)
    if auxiliary:
        summary_path = root/'results/studies/validation_summary.json'
        summary = json.loads(summary_path.read_text(encoding='utf-8'))
        summary[KEY] = auxiliary
        Storage_WriteJson(summary_path,summary)
    print(f"STUDY_PAYLOAD_READY {len(manifest['series'])} trajectories, {len(manifest['checks'])} checks",flush=True)
