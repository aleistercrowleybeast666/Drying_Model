"""Independent, restartable experiments using the production RK4 and FV transfers.

Numerical configuration is part of the identity. Plot style is deliberately not.
An experiment contains its original initial state and every completed checkpoint;
references cannot be manufactured by restarting a fine mesh from a coarse late state.
"""
import hashlib
import json
import time
import types
from enum import IntEnum
from pathlib import Path
import numpy as np
from ..cases import Case_LoadInputs, Case_GetSchedule, Case_IterFields, Case_LoadMesh
from ..events import Event_Locate
from ..geometry import Geometry_GetGrid
from ..inputs import Input_AtTime
from ..mesh import Mesh_Equidistribute
from ..rk4 import Rk4_Advance
from ..sampling import Sampling_Reconstruct
from ..stages import Stage_ProjectState
from ..storage import Storage_WriteArray, Storage_WriteJson
from .baseline import Baseline_ReadJson, Baseline_HashFile


class StudyRunResult(IntEnum):
    COMPLETE = 0
    STOPPED = 1
    FAILED = 2


def Trajectory_GetSpec(root, case, mode='M00', kind='production', factor=1, tail_minutes=60, replay=None):
    root=Path(root); baseline=Baseline_ReadJson(root/'work/baseline_snapshot/baseline_manifest.json')
    selected=baseline['selected'][f'{case}_1d']
    schedule=[dict(t_start=s['t_start'],t_end=s['t_end'],nr=s['nr']*factor,nz=1) for s in selected['schedule']]
    if kind=='matched':
        schedule=[dict(t_start=0.,t_end=selected['cap'],nr=baseline['selected'][f'{case}_2d']['nr'],nz=1)]
    # Only files defining the numerical experiment belong to this digest.
    modules=['trajectory.py']+(['thermal.py','water.py'] if mode!='M00' else [])
    source={name:Baseline_HashFile(root/'src/drying/studies'/name) for name in modules}
    spec=dict(schema_version=1,baseline_id=baseline['baseline_id'],case=case,mode=mode,kind=kind,
        schedule=schedule,physics=baseline['config']['physics'],numerics=baseline['config']['numerics'],
        dt_max_s=.125 if replay else .25,tail_minutes=tail_minutes,shrink=case=='q4' and kind!='fixed_radius',
        replay=replay,source=source,initial_origin='original_uniform_state' if kind!='tail' else 'frozen_M00_state_at_14400s',
        monitor_hash=baseline['protected_files'][f'work/validation/mesh_profiles/{case}_radial_monitor.npz']['sha256'])
    if kind=='tail':
        spec['schedule']=[dict(s,t_start=max(s['t_start'],14400.)) for s in schedule if s['t_end']>14400.]
    if mode!='M00':
        from .water import Water_Prepare
        spec['water']=Water_Prepare(root)
    fingerprint=hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()
    spec.update(fingerprint=fingerprint,experiment_id=f'{case}_{mode}_{kind}_x{factor}_tail{tail_minutes}_{fingerprint[:12]}')
    return spec


def Trajectory_GetMesh(root, spec, stage):
    if spec['kind']=='matched':
        baseline=Baseline_ReadJson(Path(root)/'work/baseline_snapshot/baseline_manifest.json')
        xi,_=Case_LoadMesh(root,baseline['selected'][spec['case']+'_2d']['case_id'])
    else:
        with np.load(Path(root)/f"work/validation/mesh_profiles/{spec['case']}_radial_monitor.npz") as data:
            xi=Mesh_Equidistribute(data['x'],data['monitor'],stage['nr'])[0]
    return xi,np.array([0.,1.])


def Trajectory_GetInputs(root, spec):
    environment,radius,tail=Case_LoadInputs(root)
    rows=environment[environment[:,0]>=14400-spec['tail_minutes']*60-1e-8]
    if len(rows)!=spec['tail_minutes']+1:raise ValueError('TAIL_WINDOW_SAMPLE_COUNT_FAILED')
    return environment,radius,rows[:,1:].mean(axis=0)


def Trajectory_GetNodes(state,t,model,inputs,mesh,spec):
    Te,He,R=Input_AtTime(t,*inputs,spec['shrink'])
    rf,rc,dr,zf,zc,dz=Geometry_GetGrid(state.shape[1],state.shape[2],R,*mesh)
    values=Sampling_Reconstruct(state,R,Te,He,model,spec['physics']['h'],spec['physics']['hm'],False,*mesh)
    if t==0:values[:]=state[:,0:1,0:1]
    if spec['mode']!='M00' and t>0:
        from .thermal import Thermal_GetSurface
        Ts,Cs=Thermal_GetSurface(state,R,Te,He,model,mesh,spec)
        values[0,-1,:]=Ts;values[1,-1,:]=Cs
    return np.r_[0.,rc,R],np.r_[0.,zc,.125],values


def Trajectory_GetAdvance(root,spec,mesh):
    inputs=Trajectory_GetInputs(root,spec);p=spec['physics'];n=spec['numerics']
    model={'q1':1,'q23':3,'q4':4}[spec['case']]
    kernel=Rk4_Advance
    Tmin=min(p['T0_K'],inputs[0][:,1].min());Tmax=max(p['T0_K'],inputs[0][:,1].max())
    if spec['mode']!='M00':
        from .thermal import Thermal_GetKernel
        kernel=Thermal_GetKernel(spec);Tmin,Tmax=spec['water']['temperature_range_K']
    def Advance(state,t,stop,replay=None):
        result=kernel(state,t,stop,spec['dt_max_s'],model,*inputs,spec['shrink'],False,
            n['safety'],n['min_dt_s'],n['max_rejections'],max(10000,int((stop-t)/n['min_dt_s']) if stop-t<.0001 else 2000000),
            Tmin,Tmax,np.empty(0) if replay is None else replay,p['h'],p['hm'],p['threshold'],*mesh)
        if result[4]:
            detail=dict(experiment_id=spec['experiment_id'],case=spec['case'],mode=spec['mode'],time_s=result[1],
                code=int(result[4]),rejections=result[3].tolist(),dt_max_s=spec['dt_max_s'],mesh_nr=state.shape[1],
                temperature_range_K=[float(result[0][0].min()),float(result[0][0].max())],
                moisture_range=[float(result[0][1].min()),float(result[0][1].max())])
            Storage_WriteJson(Path(root)/'work/studies/diagnostics'/f"{spec['experiment_id']}_failure.json",detail)
            raise RuntimeError(('THERMAL_MODEL_OUT_OF_DOMAIN' if spec['mode']!='M00' else 'STUDY_INTEGRATION_FAILED')+': '+json.dumps(detail))
        return result
    return Advance


def Trajectory_IterBaseline(root,case,dim=1):
    baseline=Baseline_ReadJson(Path(root)/'work/baseline_snapshot/baseline_manifest.json')
    case_id=baseline['selected'][f'{case}_{dim}d']['case_id']
    previous=None;mesh=None
    for t,state in Case_IterFields(root,case_id):
        if state.shape!=previous:
            mesh=Case_LoadMesh(root,case_id,t);previous=state.shape
        yield t,state,mesh


def Trajectory_Iter(root,experiment_id):
    folder=Path(root)/'work/studies/experiments'/experiment_id
    spec=Baseline_ReadJson(folder/'spec.json')
    for path in sorted(folder.glob('chunk_*.npz')):
        with np.load(path) as data:
            if str(data['fingerprint'])!=spec['fingerprint']:raise RuntimeError('STUDY_CACHE_MISMATCH')
            times,fields,mesh=data['time_s'].copy(),data['fields'].copy(),(data['xi_faces'].copy(),data['eta_faces'].copy())
        for t,state in zip(times,fields):yield float(t),state,mesh


def Trajectory_GetState(root,spec,target):
    previous=None
    for row in Trajectory_Iter(root,spec['experiment_id']):
        if row[0]>target+1e-8:break
        previous=row
        if abs(row[0]-target)<1e-8:return row[1],row[2]
    if previous is None:raise RuntimeError('STUDY_REFERENCE_INCOMPLETE: no initial history')
    t,state,mesh=previous
    if target>spec['schedule'][-1]['t_end']+1e-8:raise RuntimeError('STUDY_REFERENCE_INCOMPLETE: beyond physical cap')
    # Every switching state is saved; exact endpoint sampling uses real integration.
    return Trajectory_GetAdvance(root,spec,mesh)(state,t,target)[0],mesh


def Trajectory_Solve(root,spec,resume=True):
    root=Path(root);folder=root/'work/studies/experiments'/spec['experiment_id'];folder.mkdir(parents=True,exist_ok=True)
    status_path=folder/'status.json'
    if status_path.exists() and resume:
        status=Baseline_ReadJson(status_path)
        if status.get('complete'):return status
    else:
        status=dict(experiment_id=spec['experiment_id'],fingerprint=spec['fingerprint'],complete=False,status='RUNNING',
            event=None,drying_time_h=None,steps=0,minimum_dt=None,maximum_dt=0.,transfers=[],chunks=[],simulated_time_s=spec['schedule'][0]['t_start'])
    Storage_WriteJson(folder/'spec.json',spec)
    model={'q1':1,'q23':3,'q4':4}[spec['case']];inputs=Trajectory_GetInputs(root,spec)
    checkpoint=folder/'checkpoint.npz';state=None;t=spec['schedule'][0]['t_start'];old_mesh=None
    if checkpoint.exists() and resume:
        with np.load(checkpoint) as data:
            state=data['state'].copy();t=float(data['time_s']);old_mesh=(data['xi_faces'].copy(),data['eta_faces'].copy())
    elif spec['kind']=='tail':
        for bt,bs,bm in Trajectory_IterBaseline(root,spec['case']):
            if abs(bt-14400.)<1e-8:state=bs.copy();old_mesh=bm;break
        if state is None:raise RuntimeError('STUDY_REFERENCE_INCOMPLETE: actual 4h branch state')
    start_wall=time.monotonic();report_clock=start_wall
    schedule=Case_GetSchedule(spec['case'],spec['schedule'][-1]['t_end'])
    for index,stage in enumerate(spec['schedule']):
        if stage['t_end']<=t+1e-8:continue
        mesh=Trajectory_GetMesh(root,spec,stage)
        if state is None:
            state=np.empty((2,stage['nr'],1));state[0]=spec['physics']['T0_K'];state[1]=spec['physics']['C0']
        elif old_mesh is not None and not np.array_equal(old_mesh[0],mesh[0]):
            before=state.copy();state,metrics=Stage_ProjectState(state,old_mesh,mesh,t)
            Storage_WriteArray(folder/f'remesh_{index}.npz',before=before,after=state,old_xi=old_mesh[0],new_xi=mesh[0],time_s=t)
            status['transfers'].append(metrics)
        old_mesh=mesh;advance=Trajectory_GetAdvance(root,spec,mesh)
        namespace=dict(Event_Locate.__globals__)
        namespace['Sampling_GetNodes']=lambda u,ts,m,inp,me:Trajectory_GetNodes(u,ts,m,inp,me,spec)
        locate=types.FunctionType(Event_Locate.__code__,namespace,Event_Locate.__name__,Event_Locate.__defaults__)
        points=np.unique(np.r_[t,schedule[(schedule>t+1e-8)&(schedule<=stage['t_end']+1e-8)],stage['t_end']])
        block_times=[t];block_fields=[state.copy()];step_ends=[]
        replay=np.empty(0)
        if spec['replay']:
            for path in sorted((root/'work/studies/experiments'/spec['replay']).glob('chunk_*.npz')):
                with np.load(path) as data:
                    ends=data['step_ends'];ends=ends[(ends>stage['t_start']+1e-8)&(ends<=stage['t_end']+1e-8)]
                    if len(ends):replay=np.r_[replay,ends]
            starts=np.r_[stage['t_start'],replay[:-1]];replay=np.sort(np.r_[replay,(replay+starts)/2])
        for target in points[1:]:
            result=advance(state,t,float(target),replay);state,t=result[0],float(result[1])
            step_ends.extend(result[2]);status['steps']+=len(result[2])
            if len(result[2]):
                status['minimum_dt']=min(status['minimum_dt'] or float('inf'),float(result[9]));status['maximum_dt']=max(status['maximum_dt'],float(result[10]))
            if status['event'] is None and result[6]>=0:
                event,event_state=locate(result[6],result[7],result[8],advance,model,inputs,spec['physics']['threshold'],mesh)
                status.update(event=event,drying_time_h=event['report_h'])
                Storage_WriteArray(folder/'event.npz',state=event_state,time_s=event['report_s'],xi_faces=mesh[0],eta_faces=mesh[1])
            block_times.append(t);block_fields.append(state.copy())
            flush=t>=stage['t_end']-1e-8 or t-block_times[0]>=3600-1e-8 or (root/'work/studies/STOP').exists()
            if flush:
                name=f'chunk_{block_times[0]:012.3f}_{index}.npz'
                Storage_WriteArray(folder/name,time_s=np.array(block_times),fields=np.array(block_fields),step_ends=np.array(step_ends),
                    xi_faces=mesh[0],eta_faces=mesh[1],fingerprint=spec['fingerprint'])
                if name not in status['chunks']:status['chunks'].append(name)
                Storage_WriteArray(checkpoint,state=state,time_s=t,xi_faces=mesh[0],eta_faces=mesh[1])
                status.update(simulated_time_s=t,wall_s=status.get('wall_s',0.)+time.monotonic()-start_wall)
                start_wall=time.monotonic();Storage_WriteJson(status_path,status)
                block_times=[t];block_fields=[state.copy()];step_ends=[]
                if (root/'work/studies/STOP').exists():
                    status['status']='STOPPED';Storage_WriteJson(status_path,status);return status
            if time.monotonic()-report_clock>30:
                print(f"{spec['experiment_id']} {t/3600:.3f} h / {spec['schedule'][-1]['t_end']/3600:g} h Nr={stage['nr']}",flush=True)
                report_clock=time.monotonic()
    status.update(complete=True,status='COMPUTED' if model==1 else 'DRY' if status['event'] else 'NOT_DRY_WITHIN_72H',
        full_history_verified=spec['initial_origin']=='original_uniform_state',actual_parameters=spec['physics'],
        thermal_flags=dict(latent=spec['mode'] in ['M10','M11'],moisture_sensible=spec['mode'] in ['M01','M11']))
    Storage_WriteJson(status_path,status)
    print(f"COMPLETED {spec['experiment_id']} {status['status']} drying_h={status['drying_time_h']}",flush=True)
    return status
