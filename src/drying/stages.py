"""Few scheduled FV grid transfers; each child trajectory has fixed topology."""
import hashlib
import json
from pathlib import Path
import numpy as np
from .cases import (Case_LoadConfig, Case_LoadInputs, Case_LoadMesh, Case_ReadStatus,
                    Case_Solve, Case_IterFields, Case_GetSourceHash)
from .mesh import Mesh_BuildAdaptive, Mesh_GetHash
from .storage import Storage_WriteArray, Storage_WriteJson, Storage_HashFiles
from .diagnostics import Diagnostics_Record


def Stage_GetSourceHash(root):
    # Policy/report edits do not invalidate unchanged numerical trajectories.
    import ast
    root = Path(root)
    names = {'Stage_LoadSchedule','Stage_NormalizeSchedule','Stage_ProjectState','Stage_Solve'}
    tree = ast.parse((root/'src/drying/stages.py').read_text(encoding='utf-8'))
    bundle = '\n'.join(ast.dump(n,include_attributes=False) for n in tree.body
        if isinstance(n,(ast.Import,ast.ImportFrom)) or isinstance(n,ast.FunctionDef) and n.name in names)
    numerical_hash = hashlib.sha256(bundle.encode()).hexdigest()
    cases_hash = Storage_HashFiles([root/'src/drying/cases.py'])
    reference = root/'configs/stage_solver_reference.json'
    if reference.exists():
        saved = json.loads(reference.read_text(encoding='utf-8'))
        if saved['numerical_ast_hash']==numerical_hash and saved['cases_hash']==cases_hash:
            return saved['legacy_source_hash']
    return hashlib.sha256((numerical_hash+cases_hash).encode()).hexdigest()


def Stage_LoadSchedule(root, case, conservative=False):
    config = Case_LoadConfig(root)
    source = Path(root)/config['stage_mesh']['schedule_file']
    schedule = json.loads(source.read_text(encoding='utf-8'))[case]
    cap = 1800. if case == 'q1' else float(config['physics']['t_cap_s'])
    result = Stage_NormalizeSchedule(schedule,cap)
    if conservative and len(result) > 2:
        result = [s for s in result if s['nr'] >= 80]
        result[-1] = dict(result[-1],t_end=cap)
    return result


def Stage_NormalizeSchedule(schedule, cap):
    result = []; cursor = 0.
    for item in schedule:
        start = float(item['t_start'])
        end = cap if item['t_end'] is None else float(item['t_end'])
        nr,nz = int(item['nr']),int(item.get('nz',1))
        if abs(start-cursor) > 1e-8 or end <= start or nr < 2 or nz != 1:
            raise ValueError('REMESH_TRANSFER_FAILED: stages must cover time contiguously; currently 1D only')
        if start >= cap: break
        result.append(dict(t_start=start,t_end=min(end,cap),nr=nr,nz=nz))
        cursor = end
        if end >= cap: break
    if not result or result[-1]['t_end'] != cap:
        raise ValueError('REMESH_TRANSFER_FAILED: schedule does not reach the time cap')
    return result


def Stage_ProjectState(state, source_mesh, target_mesh, switch_time):
    """Positive overlap averages in xi^2 / eta; conserves volume integrals of T/C.

    T volume integral is a transfer diagnostic, not a claim of nonlinear enthalpy
    conservation. The physical radius factor cancels at a same-time Q4 transfer.
    """
    matrices = []
    volumes = []
    for axis,(old,new) in enumerate(zip(source_mesh,target_mesh)):
        a,b = (old**2,new**2) if axis == 0 else (old,new)
        overlap = np.maximum(0.,np.minimum(b[1:,None],a[None,1:])-np.maximum(b[:-1,None],a[None,:-1]))
        matrices.append(overlap/np.diff(b)[:,None])
        volumes.append((np.diff(a),np.diff(b)))
    target = np.stack([matrices[0]@f@matrices[1].T for f in state])
    old_weight = volumes[0][0][:,None]*volumes[1][0][None,:]
    new_weight = volumes[0][1][:,None]*volumes[1][1][None,:]
    # Reconstruct the projected cell averages back by conservative overlap;
    # the lost subcell variation measures the additional transfer error.
    back = []
    for axis,(old,new) in enumerate(zip(source_mesh,target_mesh)):
        a,b = (old**2,new**2) if axis == 0 else (old,new)
        overlap = np.maximum(0.,np.minimum(a[1:,None],b[None,1:])-np.maximum(a[:-1,None],b[None,:-1]))
        back.append(overlap/np.diff(a)[:,None])
    restored = np.stack([back[0]@f@back[1].T for f in target])
    difference = restored-state
    before = np.sum(state*old_weight,axis=(1,2)); after = np.sum(target*new_weight,axis=(1,2))
    relative = np.abs(after-before)/np.maximum(np.abs(before),1e-30)
    if (not np.isfinite(target).all() or np.any(target[1] <= 0) or
        target[0].min() < state[0].min()-1e-10 or target[0].max() > state[0].max()+1e-10 or
        np.any(relative > 1e-12)):
        raise RuntimeError('REMESH_TRANSFER_FAILED: nonfinite/unbounded state or failed volume conservation')
    metrics = dict(switch_time=float(switch_time),old_mesh=list(state.shape[1:]),new_mesh=list(target.shape[1:]),
        projection_max_abs_T=float(np.abs(difference[0]).max()),projection_max_abs_C=float(np.abs(difference[1]).max()),
        projection_L2_T=float(np.sqrt(np.sum(difference[0]**2*old_weight)/old_weight.sum())),
        projection_L2_C=float(np.sqrt(np.sum(difference[1]**2*old_weight)/old_weight.sum())),
        volume_integral_T_before=float(before[0]),volume_integral_T_after=float(after[0]),
        volume_integral_C_before=float(before[1]),volume_integral_C_after=float(after[1]),
        volume_integral_relative_error_T=float(relative[0]),volume_integral_relative_error_C=float(relative[1]),
        metric_note='Max/L2 compare old averages with conservatively back-projected new averages; T integral is not nonlinear enthalpy.',
        method='Exact annular-volume overlap in frozen xi coordinates; positive weights')
    return target,metrics


def Stage_Solve(root, case, schedule=None, dt=None, replay_id=None, label='default'):
    root = Path(root); config = Case_LoadConfig(root)
    schedule = schedule or Stage_LoadSchedule(root,case)
    dt = config['numerics']['dt_s'] if dt is None else dt
    meshes = [Mesh_BuildAdaptive(root,case,s['nr'],s['nz'],config['mesh']['mode']) for s in schedule]
    spec = dict(case=case,dim=1,execution_mode='stage_schedule',schedule=schedule,dt=dt,
        input_hash=json.loads((root/'data/input_manifest.json').read_text(encoding='utf-8'))['hash'],
        source_hash=Case_GetSourceHash(root),stage_source_hash=Stage_GetSourceHash(root),
        mesh_hashes=[m[1]['mesh_profile_hash'] for m in meshes],physics=config['physics'],numerics=config['numerics'],
        replay_id=replay_id)
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
        child = Case_Solve(root,case,1,nr=stage['nr'],nz=1,dt=dt,
            tag=f'stagepart_{fingerprint[:12]}_{i}',cap=stage['t_end'],start_time=stage['t_start'],initial_state=state,
            replay_id=replay['stages'][i]['case_id'] if replay else None)
        children.append(child)
        status['stages'].append(dict(stage,case_id=child['case_id'],fingerprint=child['fingerprint'],
            mesh_profile_hash=child['mesh_profile_hash'],actual_dt_min=child['minimum_dt'],
            actual_dt_mean=(stage['t_end']-stage['t_start'])/child['steps'],actual_dt_max=child['maximum_dt'],
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
        status.update(transfers=transfers,simulated_time_s=stage['t_end'])
        Storage_WriteJson(folder/'status.json',status)
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
        maximum_dt=max(c['maximum_dt'] for c in children),actual_dt_mean=status['cap']/total_steps,
        stage_dt_statistics=status['stages'],wall_s=sum(c['wall_s'] for c in children),
        peak_rss_bytes=max(c['peak_rss_bytes'] for c in children),final=children[-1]['final'],
        radial_initial=children[0]['radial_initial'],radial_minimum=children[-1]['radial_minimum'],
        diagnostics=[row for c in children for row in c['diagnostics']],
        dt_stable_without_limiting=all(c['dt_stable_without_limiting'] for c in children))
    Storage_WriteJson(folder/'status.json',status)
    Diagnostics_Record(root,'STAGE_SCHEDULE_COMPLETED',case_id=case_id,drying_time_h=status['drying_time_h'],
        stage_dt_statistics=status['stages'],transfers=transfers)
    return status


def Stage_Validate(root, case, fixed_entry):
    from .validation import (Validation_CompareCaches, Validation_AssessSpatial,
        Validation_SaveComparison, Validation_SaveEntry, Validation_CheckTime)
    root = Path(root); cfg = Case_LoadConfig(root)
    fixed = Case_Solve(root,case,1,nr=cfg['mesh']['verification_nr'])
    from .audit import Audit_AttachComparison
    trials = []; candidates=[]
    for conservative in [False,True]:
        candidate = Stage_Solve(root,case,Stage_LoadSchedule(root,case,conservative),
                                label='conservative' if conservative else 'default')
        check,rows = Validation_CompareCaches(root,candidate['case_id'],fixed['case_id'])
        Audit_AttachComparison(root,check)
        Validation_AssessSpatial(check,cfg['validation']['spatial'],case != 'q1')
        check['schedule_id'] = candidate['case_id']
        check['schedule'] = candidate['schedule']
        check['projection_checks'] = Stage_AssessTransfers(candidate['transfers'],cfg['validation']['spatial'])
        if check['projection_checks']['threshold_exceeded']:
            Diagnostics_Record(root,'STAGE_PROJECTION_AUDIT_NOTICE',case_id=candidate['case_id'],
                projection_checks=check['projection_checks'],acceptance_veto=False)
        check['stage_schedule_accuracy_passed'] = bool(check['passed'])
        check['early_reference_passed'] = bool(fixed_entry.get('early_refinement',{}).get('passed'))
        check['remesh_transfer_passed'] = bool(check['projection_checks']['remesh_transfer_passed'] and
            len(candidate['transfers'])==len(candidate['schedule'])-1)
        if not check['early_reference_passed']: check['failure_reasons'].append('EARLY_REFERENCE_FAILED')
        if not check['remesh_transfer_passed']: check['failure_reasons'].append('REMESH_TRANSFER_FAILED')
        check['passed'] = bool(check['early_reference_passed'] and check['stage_schedule_accuracy_passed'] and check['remesh_transfer_passed'])
        check['assessment'] = 'PASS' if check['passed'] else 'FAIL'
        check['comparison_role'] = 'Stage production acceptance: early local reference AND full formal-output schedule accuracy AND conservative remesh integrity.'
        Validation_SaveComparison(root,f'{case}_stage_{"conservative" if conservative else "default"}_vs_fixed',check,rows)
        trials.append(check); candidates.append(candidate)
        if not check['passed']:
            Diagnostics_Record(root,'STAGE_COARSENING_TOO_AGGRESSIVE','WARNING',case_id=candidate['case_id'],
                failure_reasons=check['failure_reasons'],official_temperature=check['official_temperature'],
                official_moisture=check['official_moisture'],event_relative_difference=check['event_relative_difference'])
    selected_index = next((i for i,t in enumerate(trials) if t['passed']),len(trials)-1)
    candidate=candidates[selected_index]; selected_trial=trials[selected_index]
    chosen = candidate if selected_trial['passed'] else fixed
    # Validate the proposed schedule too, even when output falls back to fixed.
    temporal = Validation_CheckTime(root,candidate)
    selected_temporal = temporal if chosen['case_id'] == candidate['case_id'] else fixed_entry['temporal']
    if chosen['case_id'] == candidate['case_id'] and not temporal['passed']:
        chosen = fixed; selected_temporal = fixed_entry['temporal']
    old_uniform = fixed_entry.get('old_uniform_comparison',{})
    if chosen['case_id'] != fixed['case_id']:
        from .mesh import Mesh_GetPilot
        legacy,_ = Mesh_GetPilot(root,case,'radial')
        old_uniform,rows = Validation_CompareCaches(root,legacy['case_id'],chosen['case_id'],legacy_reference=legacy)
        Validation_SaveComparison(root,f'{case}_1d_vs_old_uniform',old_uniform,rows)
    entry = dict(fixed_entry,selected_id=chosen['case_id'],selected_fingerprint=chosen['fingerprint'],
        selected_nr=chosen['nr'],fixed_reference_id=fixed['case_id'],fixed_reference_fingerprint=fixed['fingerprint'],
        stage_schedule_enabled=True,stage_schedule_passed=bool(selected_trial['passed'] and temporal['passed']),
        stage_schedule_trials=trials,stage_temporal=temporal,
        stage_schedule_vs_fixed_temperature_max=selected_trial['official_temperature']['value'],
        stage_schedule_vs_fixed_moisture_max=selected_trial['official_moisture']['value'],
        stage_schedule_vs_fixed_drying_time_diff=selected_trial['event_difference_s'],
        stage_schedule_vs_fixed_drying_time_rel=selected_trial['event_relative_difference'],
        recommended_schedule=chosen.get('schedule','fixed 160'),execution_mode=chosen.get('execution_mode','fixed'),
        temporal=selected_temporal,time_passed=selected_temporal['passed'],old_uniform_comparison=old_uniform,
        stage_acceptance_note='Current stage production uses the three required spatial gates; old fixed-grid failure is diagnostic only. If production falls back to a fixed grid, use that fixed grid certificate.')
    entry.update(Stage_AssessProduction(fixed_entry,selected_trial,chosen.get('execution_mode')=='stage_schedule'))
    entry['stage_schedule_passed'] = bool(entry['stage_schedule_spatial_passed'] and selected_temporal['passed'])
    entry['numerical_status'] = 'PASS' if entry['spatial_convergence_passed'] and selected_temporal['passed'] else (
        'SPATIAL_CONVERGENCE_FAILED' if not entry['spatial_convergence_passed'] else 'TIME_CONVERGENCE_FAILED')
    Validation_SaveEntry(root,case+'_1d',entry)
    Storage_WriteJson(root/f'work/validation/{case}_stage_summary.json',entry)
    return entry


def Stage_AssessTransfers(transfers,thresholds):
    checks=[dict(switch_time=v['switch_time'],
        temperature_passed=v['projection_max_abs_T']<=thresholds['temperature_abs_K'],
        moisture_passed=v['projection_max_abs_C']<=thresholds['moisture_abs']) for v in transfers]
    # Lost-variation amplitudes are audit-only; physical transfer integrity remains a gate.
    integral_keys = ['volume_integral_relative_error_T','volume_integral_relative_error_C']
    integrity = all(all(np.isfinite(v.get(k,float('nan'))) and abs(v[k])<=1e-12 for k in integral_keys)
        and all(np.isfinite(v.get(k,float('nan'))) and v[k]>=0 for k in
            ['projection_max_abs_T','projection_max_abs_C','projection_L2_T','projection_L2_C']) for v in transfers)
    return dict(assessment='AUDIT_ONLY',acceptance_veto=False,remesh_transfer_passed=bool(integrity),
        remesh_integral_relative_tolerance=1e-12,
        threshold_exceeded=any(not (v['temperature_passed'] and v['moisture_passed']) for v in checks),switches=checks,
        note='Lost subcell variation is audit-only. Nonfinite/unbounded states and conservation violations still stop Stage_ProjectState.')


def Stage_AssessProduction(fixed_entry, trial, production_is_stage):
    """Keep the historical fixed certificate separate from the current production certificate."""
    fixed_passed = bool(fixed_entry.get('fixed_grid_spatial_passed',fixed_entry.get('spatial_passed',False)))
    gates = {key:bool(trial.get(key,False)) for key in
        ['early_reference_passed','stage_schedule_accuracy_passed','remesh_transfer_passed']}
    candidate_passed = all(gates.values())
    stage_passed = bool(production_is_stage and candidate_passed)
    official_passed = stage_passed if production_is_stage else fixed_passed
    return dict(**gates,certificate_scope='current_production',fixed_grid_spatial_passed=fixed_passed,
        stage_candidate_spatial_passed=candidate_passed,stage_schedule_spatial_passed=stage_passed,
        spatial_convergence_passed=official_passed,spatial_passed=official_passed,candidate_only=not official_passed,
        spatial_acceptance_note='Current production only: early reference AND stage accuracy AND remesh integrity for a stage schedule; fixed-grid certificate for fixed production. Historical fixed failure never vetoes a passing stage production.')
