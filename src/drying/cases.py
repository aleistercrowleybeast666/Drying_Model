import hashlib
import json
import logging
import time
import tomllib
from pathlib import Path
import numpy as np
import psutil
from .diagnostics import Diagnostics_Record
from .events import Event_Locate
from .inputs import Input_AtTime
from .materials import Material_Evaluate
from .rk4 import Rk4_Advance, RkStepResult
from .sampling import Sampling_GetNodes
from .storage import Storage_HashFiles, Storage_WriteArray, Storage_WriteJson


def Case_LoadInputs(root):
    with np.load(Path(root)/'data/inputs.npz') as data:
        return tuple(data[key].copy() for key in ('environment', 'radius', 'tail'))


def Case_LoadConfig(root):
    with (Path(root)/'configs/default.toml').open('rb') as stream:
        return tomllib.load(stream)


def Case_GetId(case, dim, nr=40, nz=125, dt=0.25, tag=''):
    return f'{case}_{dim}d_nr{nr}_nz{nz if dim == 2 else 1}_dt{dt:g}' + (f'_{tag}' if tag else '')


def Case_GetSchedule(case, cap):
    early_end = min(cap, 1800 if case == 'q1' else 10800)
    early = np.arange(0, early_end+1e-8, 1.) if case != 'q4' else np.arange(0, early_end+1e-8, 60.)
    late = np.arange(np.floor(early_end/60)*60+60, cap+1e-8, 60.)
    return np.unique(np.r_[early, late, min(1800, cap), cap])


def Case_Solve(root, case, dim, nr=None, nz=None, dt=None, tag='', cap=None, replay_id=None):
    root = Path(root)
    config = Case_LoadConfig(root)
    num = config['numerics']
    nr, nz, dt = nr or num['nr'], nz or num['nz'], dt or num['dt_s']
    if dim == 1:
        nz = 1
    if nr < 2 or nz < 1 or dim not in (1, 2) or dt <= 0:
        raise ValueError('INPUT_VALUE_INVALID: numerical configuration')
    case_id = Case_GetId(case, dim, nr, nz, dt, tag)
    folder = root/'work/cache'/case_id
    folder.mkdir(parents=True, exist_ok=True)
    model = dict(q1=1, q23=3, q4=4)[case]
    cap = float(cap if cap is not None else (1800 if case == 'q1' else config['physics']['t_cap_s']))
    if cap > (1800 if case == 'q1' else 259200):
        raise ValueError('RADIUS_OUT_OF_RANGE: time cap exceeded')
    inputs = Case_LoadInputs(root)
    input_hash = json.loads((root/'data/input_manifest.json').read_text(encoding='utf-8'))['hash']
    source_hash = Storage_HashFiles([root/'src/drying'/f for f in
        ('materials.py', 'boundaries.py', 'operators.py', 'rk4.py', 'sampling.py', 'inputs.py', 'events.py')])
    specification = dict(case=case, dim=dim, nr=nr, nz=nz, dt=dt, cap=cap,
                         input_hash=input_hash, source_hash=source_hash, replay_id=replay_id,
                         physics=config['physics'], numerics=num)
    fingerprint = hashlib.sha256(json.dumps(specification, sort_keys=True).encode()).hexdigest()
    status_path = folder/'status.json'
    if status_path.exists():
        saved = json.loads(status_path.read_text(encoding='utf-8'))
        if saved['fingerprint'] != fingerprint:
            raise RuntimeError(f'CACHE_MISMATCH: {case_id}; choose a new --tag')
        if saved['complete']:
            logging.getLogger('drying').info('CACHE_REUSED %s', case_id)
            return saved
    schedule = Case_GetSchedule(case, cap)
    Tmin = min(301.15, inputs[0][:, 1].min(), inputs[2][0])
    Tmax = max(301.15, inputs[0][:, 1].max(), inputs[2][0])
    def Advance(state, start, end, replay=np.empty(0)):
        return Rk4_Advance(state, start, end, dt, model, *inputs, model == 4, dim == 2,
            num['safety'], num['min_dt_s'], num['max_rejections'],
            min(num['max_steps'], max(10000, int((end-start)/min(dt, 0.001))+100)),
            Tmin, Tmax, replay)
    state = np.empty((2, nr, nz))
    state[0], state[1] = 301.15, 2.55
    t, chunk_no, steps, limited, peak, prior_wall = 0., 0, 0, 0, 0, 0.
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
                  compile_or_load_s=compile_s, validation='PENDING')
    Storage_WriteJson(status_path, status)
    logging.getLogger('drying').info('START %s warmup %.2fs target %.2fh', case_id, compile_s, cap/3600)
    while t < cap-1e-8:
        block_end = min(cap, (np.floor(t/num['checkpoint_interval_s'])+1)*num['checkpoint_interval_s'])
        targets = schedule[(schedule > t+1e-8) & (schedule <= block_end+1e-8)]
        estimated_block_bytes=(len(targets)+1)*2*nr*nz*8*3+40*nr*nz*8
        if estimated_block_bytes>4*1024**3:
            raise MemoryError('MEMORY_BUDGET_EXCEEDED: lower checkpoint_interval_s before solving this grid')
        times, fields, partitions = [], [], []
        if t == 0:
            times.append(0.)
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
                    r_m=(i+.5)*R/nr, z_m=(j+.5)*.125/nz, xi=(i+.5)/nr,
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
            if steps > num['max_steps']:
                raise RuntimeError('MAX_STEPS_REACHED')
            minimum_dt, maximum_dt = min(minimum_dt, mindt), max(maximum_dt, maxdt)
            partitions.append(accepted)
            if el >= 0 and event is None:
                event, report_state = Event_Locate(el, er, es, Advance, model, inputs)
                Storage_WriteArray(folder/'event.npz', state=report_state, time_s=event['report_s'])
                Diagnostics_Record(root, 'DRYING_EVENT_LOCATED', case_id=case_id, **event)
            state, t = new_state, float(new_t)
            times.append(t)
            fields.append(state.copy())
            now = time.perf_counter()
            if now-last_log >= 20:
                elapsed = now-start_wall
                logging.getLogger('drying').info('%s t=%.2fh %.1f%% wall=%.1fs ETA=%.1fs',
                    case_id, t/3600, 100*t/cap, elapsed, elapsed*(cap-t)/max(t, 1))
                last_log = now
        if len(times) == 0:
            raise RuntimeError('INPUT_SCHEMA_ERROR: schedule made no progress')
        Storage_WriteArray(folder/f'chunk_{chunk_no:04d}.npz', time_s=np.array(times),
                           fields=np.asarray(fields), step_ends=np.concatenate(partitions),
                           fingerprint=fingerprint)
        r, z, nodes = Sampling_GetNodes(state, t, model, inputs)
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
        execution_note='Continued genuine integration to cap for paired comparison; official export stops at 1D report time')
    Storage_WriteJson(status_path, status)
    Diagnostics_Record(root, final_code, 'WARNING' if final_code == 'NOT_DRY_WITHIN_72H' else 'INFO',
        case_id=case_id, simulated_time_s=t, Cmax=diagnostics[-1]['Cmax'],
        wall_s=status['wall_s'], peak_rss_bytes=peak, drying_time_h=status['drying_time_h'])
    return status


def Case_IterFields(root, case_id):
    folder = Path(root)/'work/cache'/case_id
    status = Case_ReadStatus(root, case_id)
    expected = status['fingerprint']
    for path in sorted(folder.glob('chunk_*.npz')):
        with np.load(path) as block:
            if str(block['fingerprint']) != expected:
                raise RuntimeError('CACHE_MISMATCH: block fingerprint')
            times, fields = block['time_s'], block['fields']
        for t, field in zip(times, fields):
            yield float(t), field


def Case_ReadStatus(root, case_id):
    root = Path(root)
    status = json.loads((root/'work/cache'/case_id/'status.json').read_text(encoding='utf-8'))
    current_input = json.loads((root/'data/input_manifest.json').read_text(encoding='utf-8'))['hash']
    current_source = Storage_HashFiles([root/'src/drying'/f for f in
        ('materials.py', 'boundaries.py', 'operators.py', 'rk4.py', 'sampling.py', 'inputs.py', 'events.py')])
    if current_input != status['input_hash'] or current_source != status['source_hash']:
        raise RuntimeError('CACHE_MISMATCH: postprocessing input or numerical core changed')
    return status


def Case_SolvePairEvents(root):
    """Save true states of both models at both report endpoints (solve phase only)."""
    root=Path(root)
    inputs=Case_LoadInputs(root)
    config=Case_LoadConfig(root)
    num=config['numerics']
    for case,model in [('q23',3),('q4',4)]:
        validation_path=root/'work/validation/summary.json'
        validation=json.loads(validation_path.read_text(encoding='utf-8')) if validation_path.exists() else {}
        ids=[validation.get(f'{case}_{dimension}d',{}).get('selected_id',Case_GetId(case,dimension)) for dimension in (1,2)]
        statuses=[Case_ReadStatus(root,case_id) for case_id in ids]
        if not all(status['complete'] for status in statuses):
            continue
        times=np.unique([status['event']['report_s'] for status in statuses if status['event']])
        for case_id,status in zip(ids,statuses):
            destination=root/'work/cache'/case_id/'paired_events.npz'
            if destination.exists():
                with np.load(destination) as data:
                    if str(data['fingerprint'])==status['fingerprint'] and np.array_equal(data['time_s'],times):
                        continue
            fields=[]
            for target in times:
                if status['event'] and abs(status['event']['report_s']-target)<1e-8:
                    with np.load(root/'work/cache'/case_id/'event.npz') as data:
                        fields.append(data['state'].copy())
                    continue
                prior=None
                for path in sorted((root/'work/cache'/case_id).glob('chunk_*.npz')):
                    with np.load(path) as data:
                        stored_times=data['time_s']
                        eligible=np.flatnonzero(stored_times<=target+1e-9)
                        if len(eligible):
                            prior=(path,int(eligible[-1]),float(stored_times[eligible[-1]]))
                        if stored_times[-1]>=target:
                            break
                if prior is None:
                    raise RuntimeError('COMPARISON_INCOMPLETE: no event predecessor state')
                with np.load(prior[0]) as data:
                    state=data['fields'][prior[1]].copy()
                result=Rk4_Advance(state,prior[2],float(target),status['dt'],model,*inputs,model==4,
                    status['dim']==2,num['safety'],num['min_dt_s'],num['max_rejections'],100000,
                    min(301.15,inputs[0][:,1].min()),max(301.15,inputs[0][:,1].max()),np.empty(0))
                if result[4]:
                    raise RuntimeError('COMPARISON_INCOMPLETE: paired endpoint integration failed')
                fields.append(result[0])
            if len(times):
                Storage_WriteArray(destination,time_s=times,fields=np.array(fields),fingerprint=status['fingerprint'])
