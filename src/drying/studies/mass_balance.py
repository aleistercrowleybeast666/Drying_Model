"""Independent solver-level water conservation replay; no production writes."""
from enum import IntEnum
from pathlib import Path
import hashlib
import json
import time
import traceback
import numpy as np
from ..geometry import Geometry_GetCells
from ..inputs import Input_AtTime
from ..materials import Material_Evaluate
from ..stages import Stage_ProjectState
from ..storage import Storage_WriteArray, Storage_WriteJson
from .baseline import Baseline_Check, Baseline_ReadJson, Baseline_HashFile
from .plot_contract import StudyPlot_ReadManifest
from .trajectory import Trajectory_GetInputs
from .mass_kernel import MassBalance_BuildKernel, MassBalance_GetWeightedMass


class MassAuditResult(IntEnum):
    COMPLETE = 0
    INCOMPLETE = 1
    FAILED = 2


def MassBalance_GetWeights(mesh, b0, R0):
    # Full cylinder: the solver stores one radian of the positive axial half.
    return b0*np.pi*R0**2*.25*np.diff(mesh[0]**2)[:, None]*np.diff(mesh[1])[None, :]


def MassBalance_GetPhysicalMass(state, mesh, radius, b0, R0):
    _, _, volumes = Geometry_GetCells(state.shape[1], state.shape[2], radius, mesh=mesh)
    return float(2*b0*(R0/radius)**2*np.sum(state[1]*volumes))


def MassBalance_GetSources(root, manifest, key):
    spec = manifest['specs'][key]; rows = []; files = {}
    if manifest['series'][key]['baseline']:
        stages = manifest['statuses'][key]['stages']
        for index, stage in enumerate(stages):
            folder = root/'work/cache'/stage['case_id']
            for name in ['status.json', 'mesh.npz']:
                path = folder/name; files[path.relative_to(root).as_posix()] = Baseline_HashFile(path)
            for path in sorted(folder.glob('chunk_*.npz')):
                rows.append(dict(path=path.relative_to(root).as_posix(), stage=index,
                    mesh=(folder/'mesh.npz').relative_to(root).as_posix(), fingerprint=stage['fingerprint']))
    else:
        folder = root/'work/studies/experiments'/key
        for path in [folder/'spec.json', folder/'status.json', *sorted(folder.glob('remesh_*.npz'))]:
            files[path.relative_to(root).as_posix()] = Baseline_HashFile(path)
        status = Baseline_ReadJson(folder/'status.json')
        if not status.get('complete'):
            raise RuntimeError('MASS_SOURCE_INCOMPLETE: '+key)
        for name in status['chunks']:
            rows.append(dict(path=(folder/name).relative_to(root).as_posix(),
                stage=int(Path(name).stem.rsplit('_', 1)[-1]), mesh=None, fingerprint=spec['fingerprint']))
    for row in rows:
        files[row['path']] = Baseline_HashFile(root/row['path'])
    return rows, files


def MassBalance_GetResidual(audit):
    return dict(initial_water_mass_kg=float(audit[0]), remaining_water_mass_kg=float(audit[9]),
        cumulative_outflow_water_mass_kg=float(audit[1]),
        max_mass_balance_abs_error_kg=float(audit[4]), max_mass_balance_rel_error=float(audit[4]/audit[0]),
        final_mass_balance_abs_error_kg=float(abs(audit[10])), final_mass_balance_rel_error=float(abs(audit[10])/audit[0]),
        final_mass_balance_signed_error_kg=float(audit[10]), time_of_max_error_s=float(audit[6]),
        maximum_error_context=dict(time_s=float(audit[6]), stage=int(audit[7]), dt_s=float(audit[11]),
            kind='remesh' if audit[11]==0. and audit[6]>0. else 'accepted_RK4_step',
            signed_error_kg=float(audit[5]), boundary_outflow_RK4_kg_s=audit[12:16].tolist(), radius_m=float(audit[16])),
        accepted_steps=int(audit[8]), integrated_absolute_boundary_flow_kg=float(audit[3]))


def MassBalance_MeasureCase(root, manifest, key, resume=True):
    root = Path(root); spec = manifest['specs'][key]; p = spec['physics']; n = spec['numerics']
    folder = root/'work/validation/mass_balance'/key; folder.mkdir(parents=True, exist_ok=True)
    rows, sources = MassBalance_GetSources(root, manifest, key)
    identity = dict(source_case_id=key, source_files=sources, spec=spec,
        audit_sources={name:Baseline_HashFile(Path(__file__).with_name(name)) for name in ['mass_kernel.py', 'mass_balance.py']},
        numerical_sources={str(path.relative_to(root).as_posix()):Baseline_HashFile(path) for path in
            [root/'src/drying'/name for name in ['operators.py','rk4.py','stages.py','inputs.py','geometry.py','materials.py','boundaries.py']]
            +[root/'src/drying/studies'/name for name in ['thermal.py','water.py','trajectory.py']]})
    signature = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    summary_path = folder/'measurement.json'; checkpoint_path = folder/'checkpoint.npz'
    if resume and summary_path.exists():
        prior = Baseline_ReadJson(summary_path)
        if prior['signature'] == signature and prior.get('complete'):
            for row in prior['audit_files']:
                if Baseline_HashFile(root/row['path']) != row['sha256']:
                    raise RuntimeError('MASS_AUDIT_CACHE_MISMATCH')
            return prior
    model = {'q1':1, 'q23':3, 'q4':4}[spec['case']]
    b0 = Material_Evaluate(model, p['T0_K'], p['C0'])[0]/(1+p['C0'])
    inputs = Trajectory_GetInputs(root, spec)
    Tmin = min(p['T0_K'], inputs[0][:, 1].min(), inputs[2][0])
    Tmax = max(p['T0_K'], inputs[0][:, 1].max(), inputs[2][0])
    if spec['mode'] != 'M00':
        Tmin, Tmax = spec['water']['temperature_range_K']; Tmin += .05; Tmax -= .05
    kernel = MassBalance_BuildKernel(spec, b0)
    audit = np.zeros(20); state = None; mesh = None; t = 0.; transfers = []; trace = []
    next_chunk = 0; max_T_difference = 0.; max_C_difference = 0.; max_geometry_difference = 0.; max_export_residual = 0.
    if resume and checkpoint_path.exists():
        with np.load(checkpoint_path) as data:
            if str(data['signature']) == signature:
                state = data['state'].copy(); mesh = (data['xi'].copy(), data['eta'].copy())
                t = float(data['time_s']); audit = data['audit'].copy(); trace = data['trace'].tolist()
                meta = json.loads(str(data['meta'])); next_chunk = meta['next_chunk']; transfers = meta['transfers']
                max_T_difference = meta['max_T_difference']; max_C_difference = meta['max_C_difference']
                max_geometry_difference = meta['max_geometry_difference']
                max_export_residual = meta['max_export_residual']
    started = time.monotonic(); reported = started
    print(f'MASS_START {key} resume_time_s={t:g}', flush=True)
    for chunk_index, row in enumerate(rows):
        if chunk_index < next_chunk:continue
        with np.load(root/row['path']) as data:
            if str(data['fingerprint']) != row['fingerprint']:
                raise RuntimeError('MASS_SOURCE_FINGERPRINT_MISMATCH')
            times = data['time_s'].copy(); fields = data['fields'].copy(); replay = data['step_ends'].copy()
            if row['mesh'] is None:new_mesh = (data['xi_faces'].copy(), data['eta_faces'].copy())
        if row['mesh']:
            with np.load(root/row['mesh']) as data:new_mesh = (data['xi_faces'].copy(), data['eta_faces'].copy())
        audit[19] = row['stage']
        if state is None:
            if times[0] != 0. or not np.all(fields[0, 0] == p['T0_K']) or not np.all(fields[0, 1] == p['C0']):
                raise RuntimeError('MASS_ORIGINAL_INITIAL_STATE_REQUIRED')
            state = fields[0].copy(); mesh = new_mesh
            audit[0] = MassBalance_GetWeightedMass(state, MassBalance_GetWeights(mesh, b0, p['R0_m']))
            audit[9] = audit[0]; audit[18] = audit[0]
        elif not np.array_equal(mesh[0], new_mesh[0]):
            R = Input_AtTime(t, *inputs, spec['shrink'])[2]
            before = MassBalance_GetPhysicalMass(state, mesh, R, b0, p['R0_m'])
            state, projection = Stage_ProjectState(state, mesh, new_mesh, t)
            after = MassBalance_GetPhysicalMass(state, new_mesh, R, b0, p['R0_m'])
            transfer = dict(time_s=t, stage=row['stage'], radius_m=float(R),
                water_mass_before_remesh=before, water_mass_after_remesh=after,
                remesh_water_mass_jump_abs=abs(after-before), remesh_water_mass_jump_rel=abs(after-before)/abs(before),
                remesh_water_mass_jump_signed_kg=after-before, projection=projection)
            transfers.append(transfer); mesh = new_mesh
            audit[9] = MassBalance_GetWeightedMass(state, MassBalance_GetWeights(mesh, b0, p['R0_m']))
            audit[10] = (audit[9]-audit[0])+audit[1]
            if abs(audit[10]) > audit[4]:
                audit[4] = abs(audit[10]); audit[5] = audit[10]; audit[6] = t; audit[7] = row['stage']
                audit[11] = 0.; audit[12:16] = 0.; audit[16] = R
        weights = MassBalance_GetWeights(mesh, b0, p['R0_m'])
        for target, expected in zip(times, fields):
            if target < t-1e-8:raise RuntimeError('MASS_SOURCE_TIME_REVERSED')
            if target > t+1e-9:
                partition = replay[(replay > t+1e-9) & (replay <= target+1e-9)]
                if len(partition) == 0:raise RuntimeError('MASS_ACCEPTED_PARTITION_MISSING')
                result = kernel(state, t, float(target), spec['dt_max_s'], model, *inputs, spec['shrink'], False,
                    n['safety'], n['min_dt_s'], n['max_rejections'], len(partition)+2, Tmin, Tmax, partition,
                    p['h'], p['hm'], p['threshold'], *mesh, audit, weights)
                if result[4] or not np.array_equal(result[2], partition):
                    Storage_WriteJson(folder/'failure.json', dict(case=spec['case'], mode=spec['mode'], time_s=t,
                        stage=row['stage'], code=int(result[4]), reason='accepted partition mismatch',
                        residual=MassBalance_GetResidual(audit), remesh=transfers))
                    raise RuntimeError('MASS_ACTUAL_ACCEPTED_PARTITION_MISMATCH')
                state = result[0]; t = float(result[1])
            dT = float(np.max(abs(state[0]-expected[0]))); dC = float(np.max(abs(state[1]-expected[1])))
            max_T_difference = max(max_T_difference, dT); max_C_difference = max(max_C_difference, dC)
            # Replay fidelity is separate from both spatial and mass thresholds.
            if dT > 1e-9 or dC > 1e-11:
                Storage_WriteJson(folder/'failure.json', dict(case=spec['case'], mode=spec['mode'], time_s=t,
                    stage=row['stage'], max_T_difference=dT, max_C_difference=dC, reason='original state replay mismatch',
                    residual=MassBalance_GetResidual(audit), remesh=transfers))
                raise RuntimeError('MASS_ORIGINAL_STATE_REPLAY_MISMATCH')
            R = Input_AtTime(t, *inputs, spec['shrink'])[2]
            physical = MassBalance_GetPhysicalMass(state, mesh, R, b0, p['R0_m'])
            max_geometry_difference = max(max_geometry_difference, abs(physical-audit[9]))
            exported_mass = MassBalance_GetPhysicalMass(expected, mesh, R, b0, p['R0_m'])
            max_export_residual = max(max_export_residual, abs((exported_mass-audit[0])+audit[1]))
            trace.append([t, audit[9], audit[1], audit[9]+audit[1], audit[10], row['stage'], R])
        meta = dict(next_chunk=chunk_index+1, transfers=transfers, max_T_difference=max_T_difference,
            max_C_difference=max_C_difference, max_geometry_difference=max_geometry_difference,
            max_export_residual=max_export_residual)
        Storage_WriteArray(checkpoint_path, signature=signature, state=state, xi=mesh[0], eta=mesh[1],
            time_s=t, audit=audit, trace=np.array(trace), meta=json.dumps(meta))
        if time.monotonic()-reported > 30:
            print(f'MASS_PROGRESS {spec["case"]}/{spec["mode"]} t={t/3600:.3f} h max_rel={audit[4]/audit[0]:.3e}', flush=True)
            reported = time.monotonic()
    if abs(t-spec['schedule'][-1]['t_end']) > 1e-8:
        raise RuntimeError('MASS_FULL_TRAJECTORY_INCOMPLETE')
    expected_steps = manifest['statuses'][key]['steps']
    if int(audit[8]) != expected_steps:raise RuntimeError('MASS_ACCEPTED_STEP_COUNT_MISMATCH')
    for path, digest in sources.items():
        if Baseline_HashFile(root/path) != digest:raise RuntimeError('MASS_SOURCE_CHANGED_DURING_AUDIT')
    trace_path = folder/'trajectory.npz'
    names = ['time_s', 'remaining_water_mass_kg', 'cumulative_outflow_water_mass_kg',
        'total_water_mass_kg', 'mass_balance_signed_error_kg', 'stage', 'radius_m']
    Storage_WriteArray(trace_path, **dict(zip(names, np.array(trace).T)))
    result = dict(schema_version=1, complete=True, status='MEASURED', case=spec['case'], mode=spec['mode'],
        source_case_id=key, signature=signature, source=identity, method='solver_mass_balance',
        observation_start_s=0., observation_end_s=t, full_accepted_partition_verified=True,
        effective_initial_dry_density_kg_m3=b0, physical_length_m=p['L_m'],
        definition='Mw=b0*(R0/R)^2*integral_full_cylinder(C dV); signed outward boundary flux uses identical dry basis',
        accumulation='exact original RK4 AST; actual FV boundary subtraction captured at all four stages; accepted steps only; Kahan outflow sum; continuous replay without checkpoint state resets',
        replay_verification=dict(status='PASS',
            maximum_original_state_difference_T_K=max_T_difference, maximum_original_state_difference_C=max_C_difference,
            maximum_physical_vs_reference_volume_mass_difference_kg=max_geometry_difference),
        export_mass_balance=dict(status='DIAGNOSTIC_ONLY', affects_pass=False,
            method='original saved FV moisture fields plus solver-integrated outflow at exported times; no inferred flux',
            max_mass_balance_abs_error_kg=max_export_residual, max_mass_balance_rel_error=max_export_residual/audit[0]),
        solver_mass_balance=MassBalance_GetResidual(audit), remesh=transfers,
        audit_files=[dict(path=trace_path.relative_to(root).as_posix(), sha256=Baseline_HashFile(trace_path))],
        wall_s=time.monotonic()-started)
    Storage_WriteJson(summary_path, result)
    print(f'MASS_MEASURED {spec["case"]}/{spec["mode"]} steps={int(audit[8])} max_abs={audit[4]:.4e} max_rel={audit[4]/audit[0]:.4e}', flush=True)
    return result


def MassBalance_Run(root, args):
    root = Path(root); Baseline_Check(root); manifest = StudyPlot_ReadManifest(root)
    keys = [k for k, spec in manifest['specs'].items() if spec['kind']=='production'
        and (not args.case or spec['case']==args.case) and (not args.mode or spec['mode']==args.mode)]
    if args.dry_run:
        for key in keys:print('MASS_AUDIT '+key, flush=True)
        return MassAuditResult.COMPLETE
    folder = root/'work/validation/mass_balance'; folder.mkdir(parents=True, exist_ok=True)
    failures = []
    for key in keys:
        try:
            if not args.payload_only:MassBalance_MeasureCase(root, manifest, key, resume=args.resume)
        except Exception as exc:
            detail = dict(source_case_id=key, error=str(exc), traceback=traceback.format_exc())
            failures.append(detail)
            Storage_WriteJson(folder/key/'run_failure.json', detail)
            print('MASS_FAILED '+key+': '+str(exc), flush=True)
    Baseline_Check(root)
    # Classification is deliberately separate: first measure all actual residuals.
    Storage_WriteJson(folder/'measurement_index.json', dict(status='FAILED' if failures else 'MEASURED',
        selected_cases=keys, failures=failures))
    from .mass_report import MassReport_Publish
    summary = MassReport_Publish(root, manifest)
    return MassAuditResult.FAILED if failures or summary['status']=='FAIL' else MassAuditResult.COMPLETE
