"""Table-only orchestration; unchanged RK4, FV, event and conservative projection kernels.

The orchestration is isolated from cases/stages so their full-horizon fingerprints
remain unchanged. Table caches always carry a different purpose and source hash.
"""
import hashlib
import json
import logging
import time
from pathlib import Path
import numpy as np
import psutil
from .cases import (Case_LoadConfig, Case_LoadInputs, Case_GetId, Case_GetSchedule,
    Case_ReadStatus, Case_GetSourceHash)
from .diagnostics import Diagnostics_Record
from .events import Event_Locate
from .materials import Material_Evaluate
from .mesh import Mesh_BuildAdaptive, Mesh_GetHash
from .rk4 import Rk4_Advance, RkStepResult
from .sampling import Sampling_GetNodes
from .stages import Stage_GetSourceHash, Stage_ProjectState
from .storage import Storage_HashFiles, Storage_WriteArray, Storage_WriteJson
from .frozen_mesh import Frozen_ReadManifest


def Table_SolveSegment(root, case, dim, nr=None, nz=None, dt=None, tag='', cap=None, replay_id=None, mesh_mode=None,
               start_time=0., initial_state=None, stop_on_event=True):
    root = Path(root)
    config = Case_LoadConfig(root)
    num = config['numerics']
    nr, nz, dt = nr or num['nr'], nz or num['nz'], dt or num['dt_s']
    if dim == 1:
        nz = 1
    if nr < 2 or nz < 1 or dim not in (1, 2) or dt <= 0:
        raise ValueError('INPUT_VALUE_INVALID: numerical configuration')
    mode = mesh_mode or config['mesh']['mode']
    mesh, mesh_metadata = Mesh_BuildAdaptive(root,case,nr,nz,mode)
    case_id = Case_GetId(case, dim, nr, nz, dt, tag, mode, mesh_metadata['mesh_profile_hash'])
    folder = root/'work/cache'/case_id
    folder.mkdir(parents=True, exist_ok=True)
    model = dict(q1=1, q23=3, q4=4)[case]
    cap = float(cap if cap is not None else (1800 if case == 'q1' else config['physics']['t_cap_s']))
    if cap > (1800 if case == 'q1' else 259200):
        raise ValueError('RADIUS_OUT_OF_RANGE: time cap exceeded')
    inputs = Case_LoadInputs(root)
    input_hash = json.loads((root/'data/input_manifest.json').read_text(encoding='utf-8'))['hash']
    source_hash = Storage_HashFiles([root/'src/drying'/f for f in
        ('materials.py', 'boundaries.py', 'operators.py', 'rk4.py', 'sampling.py', 'inputs.py', 'events.py', 'geometry.py')])
    specification = dict(case=case, dim=dim, nr=nr, nz=nz, dt=dt, cap=cap,
                         input_hash=input_hash, source_hash=source_hash, replay_id=replay_id,
                         physics=config['physics'], numerics=num)
    specification.update(purpose='table_production', stop_policy='drying_report' if stop_on_event else 'reference_horizon',
        table_source_hash=Storage_HashFiles([root/'src/drying/table_solver.py']))
    specification.update(mesh_metadata)
    if start_time != 0 or initial_state is not None:
        if initial_state is None or not 0 <= start_time < cap:
            raise ValueError('INPUT_VALUE_INVALID: stage initial state/time')
        specification.update(start_time=float(start_time),initial_state_hash=Mesh_GetHash(initial_state))
    fingerprint = hashlib.sha256(json.dumps(specification, sort_keys=True).encode()).hexdigest()
    status_path = folder/'status.json'
    if status_path.exists():
        saved = json.loads(status_path.read_text(encoding='utf-8'))
        if saved['fingerprint'] != fingerprint:
            raise RuntimeError(f'CACHE_MISMATCH: {case_id}; choose a new --tag')
        if saved['complete']:
            logging.getLogger('drying').info('CACHE_REUSED %s', case_id)
            Diagnostics_Record(root,'CACHE_REUSED',case_id=case_id)
            return saved
    Storage_WriteArray(folder/'mesh.npz',xi_faces=mesh[0],eta_faces=mesh[1],mesh_profile_hash=mesh_metadata['mesh_profile_hash'])
    schedule = np.unique(np.r_[Case_GetSchedule(case, cap),float(start_time)])
    # A replay bisects an already accepted finite partition, including on a
    # second bisection. Its resource guard must permit that known step count.
    accepted_limit = num['max_steps']
    if replay_id:
        accepted_limit = max(accepted_limit,2*Case_ReadStatus(root,replay_id)['steps']+len(schedule))
    Tmin = min(301.15, inputs[0][:, 1].min(), inputs[2][0])
    Tmax = max(301.15, inputs[0][:, 1].max(), inputs[2][0])
    def Advance(state, start, end, replay=np.empty(0)):
        return Rk4_Advance(state, start, end, dt, model, *inputs, model == 4, dim == 2,
            num['safety'], num['min_dt_s'], num['max_rejections'],
            min(num['max_steps'], max(10000, int((end-start)/min(dt, 0.001))+100)),
            Tmin, Tmax, replay, xi_faces=mesh[0], eta_faces=mesh[1])
    state = np.empty((2, nr, nz))
    state[0], state[1] = 301.15, 2.55
    if initial_state is not None:
        if initial_state.shape != state.shape or not np.isfinite(initial_state).all() or np.any(initial_state[1] <= 0):
            raise ValueError('REMESH_TRANSFER_FAILED: invalid initial state')
        state[:] = initial_state
    t, chunk_no, steps, limited, peak, prior_wall = float(start_time), 0, 0, 0, 0, 0.
    minimum_dt, maximum_dt = float('inf'), 0.
    event = None
    diagnostics = []
    checkpoint = root/'work/checkpoints'/case_id/'checkpoint.npz'
    if checkpoint.exists():
        with np.load(checkpoint) as saved:
            if str(saved['fingerprint']) != fingerprint:
                raise RuntimeError('CACHE_MISMATCH: checkpoint fingerprint')
            state, t = saved['state'].copy(), float(saved['t'])
            meta = json.loads(str(saved['meta']))
        chunk_no, steps, limited = meta['chunk_no'], meta['steps'], meta['limited']
        minimum_dt, maximum_dt = meta['minimum_dt'], meta['maximum_dt']
        event, prior_wall = meta['event'], meta['wall_s']
        diagnostics = meta['diagnostics']
    # Compile/warm up without changing the original state; separately timed.
    warm_started = time.perf_counter()
    Advance(state, t, t)
    compile_s = time.perf_counter()-warm_started
    start_wall = time.perf_counter()
    last_log = start_wall
    process = psutil.Process()
    status = dict(case_id=case_id, **specification, fingerprint=fingerprint,
                  complete=False, status='RUNNING', drying_time_h=None, event=event,
                  compile_or_load_s=compile_s, validation='PENDING', tag=tag)
    Storage_WriteJson(status_path, status)
    logging.getLogger('drying').info('START %s warmup %.2fs target %.2fh', case_id, compile_s, cap/3600)
    stopped_at_report = bool(stop_on_event and event and t >= event['report_s']-1e-8 and (case != 'q23' or t >= 10800))
    while t < cap-1e-8 and not stopped_at_report:
        block_end = min(cap, (np.floor(t/num['checkpoint_interval_s'])+1)*num['checkpoint_interval_s'])
        targets = schedule[(schedule > t+1e-8) & (schedule <= block_end+1e-8)]
        estimated_block_bytes=(len(targets)+1)*2*nr*nz*8*3+40*nr*nz*8
        if estimated_block_bytes>4*1024**3:
            raise MemoryError('MEMORY_BUDGET_EXCEEDED: lower checkpoint_interval_s before solving this grid')
        times, fields, partitions = [], [], []
        if t == start_time:
            times.append(t)
            fields.append(state.copy())
        replay = np.empty(0)
        if replay_id:
            replay_path = root/'work/cache'/replay_id/f'chunk_{chunk_no:04d}.npz'
            with np.load(replay_path) as saved:
                original = saved['step_ends']
            starts = np.r_[t, original[:-1]]
            replay = np.column_stack(((starts+original)/2, original)).ravel()
        for target in targets:
            replay_segment = replay[(replay > t+1e-9) & (replay <= target+1e-9)]
            result = Advance(state, t, target, replay_segment)
            new_state, new_t, accepted, rejected, code, limited_steps, el, er, es, mindt, maxdt = result
            for rejected_row in rejected:
                ts, ds, stage, failure, i, j, T, C, R, Te, He, attempt = rejected_row
                def Finite(value):
                    return float(value) if np.isfinite(value) else None
                try:
                    properties = [Finite(value) for value in Material_Evaluate(model, T, C)]
                except (ValueError, ZeroDivisionError, OverflowError):
                    properties = [None]*4
                Diagnostics_Record(root, 'RK_STEP_REJECTED', 'WARNING', case_id=case_id, dimension=dim,
                    simulated_time_s=ts, requested_dt_s=dt, accepted_dt_s=ds, rk_stage=int(stage),
                    reason=RkStepResult(int(failure)).name, cell_index=[int(i), int(j)],
                    r_m=float((mesh[0][int(i)]+mesh[0][int(i)+1])*R/2),
                    z_m=float((mesh[1][int(j)]+mesh[1][int(j)+1])*.125/2), xi=float((mesh[0][int(i)]+mesh[0][int(i)+1])/2),
                    R_m=R, T_K=Finite(T), C=Finite(C), environment_values=[Te, He], attempt=int(attempt),
                    rho=properties[0], cp=properties[1], k=properties[2], D=properties[3],
                    grid=[nr, nz], suggested_check='Inspect local state, conductances, and rejected RK stage')
            if code:
                status.update(status=RkStepResult(code).name, simulated_time_s=float(new_t))
                Storage_WriteJson(status_path, status)
                raise RuntimeError(f'{RkStepResult(code).name}: {case_id} t={new_t}')
            if limited_steps and limited == 0:
                Diagnostics_Record(root, 'DT_LIMITED_BY_STABILITY', 'WARNING', case_id=case_id,
                                   requested_dt_s=dt, accepted_dt_s=mindt, simulated_time_s=t, grid=[nr, nz])
            limited += limited_steps
            steps += accepted.size
            if steps > accepted_limit:
                raise RuntimeError('MAX_STEPS_REACHED')
            minimum_dt, maximum_dt = min(minimum_dt, mindt), max(maximum_dt, maxdt)
            partitions.append(accepted)
            if el >= 0 and event is None:
                event_advances = []
                def Event_Advance(event_state, left, right):
                    result = Advance(event_state, left, right)
                    event_advances.append((left, right, result))
                    return result
                event, report_state = Event_Locate(el, er, es, Event_Advance, model, inputs, mesh=mesh)
                Storage_WriteArray(folder/'event.npz', state=report_state, time_s=event['report_s'])
                Diagnostics_Record(root, 'DRYING_EVENT_LOCATED', case_id=case_id, **event)
                if stop_on_event and (case != 'q23' or event['report_s'] >= 10800):
                    # Event_Locate reintegrates from the accepted left bracket. Keep
                    # that genuine partition, not the overshooting minute endpoint.
                    located = next(value for left, right, value in reversed(event_advances)
                        if abs(right-event['report_s']) < 1e-8 and abs(left-el) < 1e-8)
                    trimmed = np.r_[accepted[accepted <= el+1e-9], located[2]]
                    steps += len(trimmed)-len(accepted)
                    partitions[-1] = trimmed
                    new_state, new_t = report_state, event['report_s']
                    stopped_at_report = True
            state, t = new_state, float(new_t)
            times.append(t)
            fields.append(state.copy())
            now = time.perf_counter()
            if now-last_log >= 20:
                elapsed = now-start_wall
                logging.getLogger('drying').info('%s t=%.2fh %.1f%% wall=%.1fs ETA=%.1fs',
                    case_id, t/3600, 100*t/cap, elapsed, elapsed*(cap-t)/max(t, 1))
                last_log = now
            if stopped_at_report:
                break
        if len(times) == 0:
            raise RuntimeError('INPUT_SCHEMA_ERROR: schedule made no progress')
        Storage_WriteArray(folder/f'chunk_{chunk_no:04d}.npz', time_s=np.array(times),
                           fields=np.asarray(fields), step_ends=np.concatenate(partitions),
                           fingerprint=fingerprint)
        r, z, nodes = Sampling_GetNodes(state, t, model, inputs, mesh)
        if not np.isfinite(nodes).all() or np.any(nodes[1]<=0):
            raise RuntimeError('BOUNDARY_RECONSTRUCTION_FAILED: invalid reconstructed field')
        index = np.unravel_index(nodes[1].argmax(), nodes[1].shape)
        props = Material_Evaluate(model, float(nodes[0][index]), float(nodes[1][index]))
        diagnostics.append(dict(time_s=t, Cmax=float(nodes[1][index]), r_m=float(r[index[0]]),
            T_K=float(nodes[0][index]), dimension=dim, dt_s=maximum_dt, rk_stage='accepted_state',
            z_m=float(z[index[1]]), R_m=float(r[-1]), rho=props[0], cp=props[1], k=props[2], D=props[3]))
        peak = max(peak, process.memory_info().rss)
        chunk_no += 1
        meta = dict(chunk_no=chunk_no, steps=steps, limited=limited,
                    minimum_dt=minimum_dt, maximum_dt=maximum_dt, event=event,
                    wall_s=prior_wall+time.perf_counter()-start_wall, diagnostics=diagnostics)
        Storage_WriteArray(checkpoint, state=state, t=t, fingerprint=fingerprint,
                           meta=json.dumps(meta))
        status.update(simulated_time_s=t, event=event, **{k:v for k,v in meta.items() if k != 'event'})
        Storage_WriteJson(status_path, status)
    final_code = 'COMPUTED' if model == 1 else ('DRY' if event else ('NOT_DRY_WITHIN_72H' if cap == 259200 else 'PARTIAL_TIME_RANGE'))
    status.update(complete=True, status=final_code, drying_time_h=event['report_h'] if event else None,
        event=event, peak_rss_bytes=peak, final=diagnostics[-1],
        dt_stable_without_limiting=limited==0,
        execution_note='Table trajectory stops at the genuine report state; no full-horizon cache reuse',
        stopped_on_event=stopped_at_report, actual_end_s=t)
    status.update(execution_mode='fixed',requested_dt_max=dt,
        actual_dt_min=minimum_dt,actual_dt_max=maximum_dt,actual_dt_mean=(t-start_time)/steps,
        stage_dt_statistics=[dict(t_start=float(start_time),t_end=t,nr=nr,nz=nz,
            actual_dt_min=minimum_dt,actual_dt_mean=(t-start_time)/steps,actual_dt_max=maximum_dt)])
    Storage_WriteJson(status_path, status)
    Diagnostics_Record(root, final_code, 'WARNING' if final_code == 'NOT_DRY_WITHIN_72H' else 'INFO',
        case_id=case_id, simulated_time_s=t, Cmax=diagnostics[-1]['Cmax'],
        wall_s=status['wall_s'], peak_rss_bytes=peak, drying_time_h=status['drying_time_h'])
    return status


def Table_SolveSchedule(root, case, schedule=None, dt=None, replay_id=None, label='table', stop_on_event=True):
    root = Path(root); config = Case_LoadConfig(root)
    frozen = Frozen_ReadManifest(root)
    schedule = schedule or frozen['schedules'][case]
    dt = config['numerics']['dt_s'] if dt is None else dt
    meshes = [Mesh_BuildAdaptive(root,case,s['nr'],s['nz'],config['mesh']['mode']) for s in schedule]
    spec = dict(case=case,dim=1,execution_mode='stage_schedule',schedule=schedule,dt=dt,
        input_hash=json.loads((root/'data/input_manifest.json').read_text(encoding='utf-8'))['hash'],
        source_hash=Case_GetSourceHash(root),stage_source_hash=Stage_GetSourceHash(root),
        mesh_hashes=[m[1]['mesh_profile_hash'] for m in meshes],physics=config['physics'],numerics=config['numerics'],
        replay_id=replay_id)
    spec.update(purpose='table_production' if label=='table' else 'judge_validation',
        stop_policy='drying_report' if stop_on_event else 'reference_horizon',
        table_source_hash=Storage_HashFiles([root/'src/drying/table_solver.py']),
        frozen_schedule_hash=frozen['schedule_hash'])
    fingerprint = hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()
    case_id = f'{case}_1d_stage_schedule_{label}_dt{dt:g}_s{fingerprint[:12]}'
    folder = root/'work/cache'/case_id; folder.mkdir(parents=True,exist_ok=True)
    if (folder/'status.json').exists():
        saved = json.loads((folder/'status.json').read_text(encoding='utf-8'))
        if saved.get('complete'):
            Diagnostics_Record(root,'CACHE_REUSED',case_id=case_id)
            return Case_ReadStatus(root,case_id)
    replay = Case_ReadStatus(root,replay_id) if replay_id else None
    state = None; children = []; transfers = []; event = None; event_state = None
    status = dict(spec,**meshes[0][1])
    status.update(case_id=case_id,fingerprint=fingerprint,complete=False,status='RUNNING',
        cap=schedule[-1]['t_end'],nr=schedule[0]['nr'],nz=1,stages=[],transfers=[],tag=label,
        requested_dt_max=dt)
    status['schedule_kind']=config['stage_mesh']['mode']
    Storage_WriteArray(folder/'mesh.npz',xi_faces=meshes[0][0][0],eta_faces=meshes[0][0][1])
    Storage_WriteJson(folder/'status.json',status)
    for i,stage in enumerate(schedule):
        if i:
            state,metrics = Stage_ProjectState(state,meshes[i-1][0],meshes[i][0],stage['t_start'])
            transfers.append(metrics)
            Diagnostics_Record(root,'MESH_STAGE_SWITCH',case_id=case_id,**metrics)
        child = Table_SolveSegment(root,case,1,nr=stage['nr'],nz=1,dt=dt,
            tag=f'stagepart_{fingerprint[:12]}_{i}',cap=stage['t_end'],start_time=stage['t_start'],initial_state=state,
            replay_id=replay['stages'][i]['case_id'] if replay else None, stop_on_event=stop_on_event)
        children.append(child)
        actual_stage = dict(stage,t_end=child['simulated_time_s'])
        status['stages'].append(dict(actual_stage,case_id=child['case_id'],fingerprint=child['fingerprint'],
            mesh_profile_hash=child['mesh_profile_hash'],actual_dt_min=child['minimum_dt'],
            actual_dt_mean=(actual_stage['t_end']-stage['t_start'])/child['steps'],actual_dt_max=child['maximum_dt'],
            requested_dt_max=dt,stability_limited_count=child['limited'],
            steps=child['steps'],wall_s=child['wall_s']))
        # Child terminal state is also its restart checkpoint (full precision).
        checkpoint = root/'work/checkpoints'/child['case_id']/'checkpoint.npz'
        with np.load(checkpoint) as data:
            state = data['state'].copy()
        if event is None and child.get('event'):
            event = child['event']
            with np.load(root/'work/cache'/child['case_id']/'event.npz') as data:
                event_state = data['state'].copy()
        status.update(transfers=transfers,simulated_time_s=actual_stage['t_end'])
        Storage_WriteJson(folder/'status.json',status)
        if child.get('stopped_on_event'):
            break
    # A report timestamp must belong to the mesh that actually produced it.
    if event:
        source_index = next(i for i,c in enumerate(children) if c.get('event'))
        if event['report_s'] > schedule[source_index]['t_end']+1e-8:
            raise RuntimeError('REMESH_TRANSFER_FAILED: event report crosses a switch; move that configured switch away from the event')
        Storage_WriteArray(folder/'event.npz',state=event_state,time_s=event['report_s'])
    total_steps = sum(c['steps'] for c in children)
    status.update(complete=True,status='COMPUTED' if case=='q1' else 'DRY' if event else 'NOT_DRY_WITHIN_72H',
        event=event,drying_time_h=event['report_h'] if event else None,steps=total_steps,
        limited=sum(c['limited'] for c in children),minimum_dt=min(c['minimum_dt'] for c in children),
        maximum_dt=max(c['maximum_dt'] for c in children),actual_dt_mean=status['simulated_time_s']/total_steps,
        stage_dt_statistics=status['stages'],wall_s=sum(c['wall_s'] for c in children),
        peak_rss_bytes=max(c['peak_rss_bytes'] for c in children),final=children[-1]['final'],
        radial_initial=children[0]['radial_initial'],radial_minimum=children[-1]['radial_minimum'],
        diagnostics=[row for c in children for row in c['diagnostics']],
        dt_stable_without_limiting=all(c['dt_stable_without_limiting'] for c in children))
    status.update(actual_end_s=status['simulated_time_s'], full_horizon=False,
        numerical_validation='NOT_RERUN_IN_TABLE_ONLY_MODE')
    Storage_WriteJson(folder/'status.json',status)
    Diagnostics_Record(root,'STAGE_SCHEDULE_COMPLETED',case_id=case_id,drying_time_h=status['drying_time_h'],
        stage_dt_statistics=status['stages'],transfers=transfers)
    return status
