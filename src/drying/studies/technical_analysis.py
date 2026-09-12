"""Final cross-property evidence and response timing from identified caches."""
from pathlib import Path
import json
import hashlib
import shutil
import numpy as np
from ..storage import Storage_WriteArray, Storage_WriteJson
from .baseline import Baseline_Check, Baseline_HashFile, Baseline_ReadJson
from .plot_contract import StudyPlot_ReadManifest
from .cross_spec import Cross_GetPlan
from .cache import Cache_SealExperiment
from .analysis import Analysis_ExtractSeries, Analysis_LoadSeries, Analysis_Compare, Analysis_GetExactState
from .trajectory import Trajectory_Iter, Trajectory_IterBaseline, Trajectory_GetNodes, Trajectory_GetInputs
from .kinetics import Kinetics_Extract, Kinetics_GetVolumeMeans


def Technical_Freeze(root, manifest):
    root = Path(root);folder = root/'work/studies/technical'
    path = folder/'pre_extension_manifest.json'
    if not path.exists():
        Storage_WriteJson(path, manifest)
        render = Baseline_ReadJson(root/'work/studies/diagnostics/render_manifest.json')
        Storage_WriteJson(folder/'pre_extension_render.json', render)
        protected = {item['path']:item['sha256'] for item in manifest['data_files']}
        for item in render['files']:
            if Path(item['path']).name not in ['03_drying_kinetics.png', '05_geometry_control.png']:
                protected[item['path']] = item['sha256']
        for item in manifest['workbooks']:
            if '/thermal/' in item['path']:protected[item['path']] = item['sha256']
        Storage_WriteJson(folder/'protected_existing.json', protected)
    for name in ['study_summary.xlsx','study_timeseries.xlsx']:
        backup=folder/'original_workbooks'/name
        if not backup.exists():
            backup.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(root/'results/studies/tables'/name,backup)
    changed = [name for name, digest in Baseline_ReadJson(folder/'protected_existing.json').items()
               if not (root/name).is_file() or Baseline_HashFile(root/name) != digest]
    if changed:raise RuntimeError('EXISTING_STUDY_OUTPUT_MODIFIED: '+', '.join(changed))


def Technical_GetQualifiedFraction(r, C, threshold=.15):
    """Exact annular volume of C<threshold under the declared radial reconstruction."""
    total = 0.
    for a, b, ca, cb in zip(r[:-1], r[1:], C[:-1], C[1:]):
        if ca < threshold and cb < threshold:total += b*b-a*a
        elif (ca < threshold) != (cb < threshold):
            crossing = a+(threshold-ca)*(b-a)/(cb-ca)
            total += crossing*crossing-a*a if ca < threshold else b*b-crossing*crossing
    return float(total/(r[-1]**2))


def Technical_CheckTransfers(root, spec, status):
    records = []
    for path in sorted((Path(root)/'work/studies/experiments'/spec['experiment_id']).glob('remesh_*.npz')):
        with np.load(path) as data:
            before, after = data['before'], data['after']
            old, new = np.diff(data['old_xi']**2), np.diff(data['new_xi']**2)
            left = before[:, :, 0]@old;right = after[:, :, 0]@new
            error = np.abs(left-right)/np.maximum(np.abs(left), 1e-30)
            records.append(dict(time_s=float(data['time_s']), relative_T_volume_error=float(error[0]),
                relative_C_volume_error=float(error[1]), finite=bool(np.isfinite(after).all()),
                positive_moisture=bool(np.all(after[1] > 0))))
    expected = len(spec['schedule'])-1
    passed = len(records) == expected and all(row['finite'] and row['positive_moisture']
        and max(row['relative_T_volume_error'], row['relative_C_volume_error']) <= 1e-12 for row in records)
    result = dict(experiment_id=spec['experiment_id'], status='PASS' if passed else 'FAIL', expected_transfers=expected,
        records=records, scope='original conservative FV transfer; no claim of nonlinear total enthalpy conservation')
    Storage_WriteJson(Path(root)/'work/studies/technical/validation'/f"{spec['experiment_id']}_transfers.json", result)
    return result


def Technical_ValidateCross(root, index):
    specs = Cross_GetPlan(root);statuses = [];entries = []
    for spec in specs:
        folder = Path(root)/'work/studies/experiments'/spec['experiment_id']
        if not (folder/'status.json').exists():raise RuntimeError('CROSS_REFERENCE_INCOMPLETE: '+spec['experiment_id'])
        status = Cache_SealExperiment(root, spec, Baseline_ReadJson(folder/'status.json'))
        if not status.get('complete'):raise RuntimeError('CROSS_REFERENCE_INCOMPLETE: '+spec['experiment_id'])
        statuses.append(status)
        event_times = [status['event']['report_s']] if status.get('event') else []
        entries.append(Analysis_ExtractSeries(root, spec, extra_times=event_times))
    checks = [Analysis_Compare(root, specs[0], specs[i], entries[0], entries[i], statuses[0], statuses[i]) for i in [1, 2]]
    transfers = [Technical_CheckTransfers(root, spec, status) for spec, status in zip(specs, statuses)]
    event_checks = []
    for spec, status in zip(specs, statuses):
        event = status.get('event')
        valid = bool(event and event['left_max_C'] >= .15 > event['right_max_C']
                     and event['report_max_C'] < .15 and event['width_s'] <= .1+1e-12)
        event_checks.append(dict(experiment_id=spec['experiment_id'], status='PASS' if valid else 'NOT_DRY_WITHIN_72H' if not event else 'FAIL',
            event=event, method='original Event_Locate; saved genuinely reintegrated state'))
    passed = all(c['status'] == 'PASS' for c in checks+transfers) and all(e['status'] != 'FAIL' for e in event_checks)
    result = dict(study_id='geometry_cross_p3_shrink', status='PASS' if passed else 'FAIL',
        specs=specs, statuses=statuses, entries=entries, checks=checks, transfers=transfers, events=event_checks,
        material_appendix=3, shrinking_radius=True, inherited_pass=False)
    Storage_WriteJson(Path(root)/'work/studies/technical/validation/cross_summary.json', result)
    return result


def Technical_BuildCross(root, manifest, validation):
    p3fixed = manifest['baseline_keys']['q23'];p4shrink = manifest['baseline_keys']['q4']
    p4fixed = next(key for key, spec in manifest['specs'].items() if spec['kind'] == 'fixed_radius')
    groups = [('P3_fixed', p3fixed, manifest['specs'][p3fixed], manifest['statuses'][p3fixed], manifest['series'][p3fixed]),
              ('P3_shrink', validation['specs'][0]['experiment_id'], validation['specs'][0], validation['statuses'][0], validation['entries'][0]),
              ('P4_fixed', p4fixed, manifest['specs'][p4fixed], manifest['statuses'][p4fixed], manifest['series'][p4fixed]),
              ('P4_shrink', p4shrink, manifest['specs'][p4shrink], manifest['statuses'][p4shrink], manifest['series'][p4shrink])]
    official=Baseline_ReadJson(Path(root)/'results/status.json')['questions']
    arrays = {};rows = []
    common = np.arange(0., 259200.+1, 60.)
    for group, key, spec, status, entry in groups:
        data = Analysis_LoadSeries(root, entry);indices = np.searchsorted(data['time_s'], common)
        if not np.array_equal(data['time_s'][indices], common):raise RuntimeError('CROSS_COMMON_TIME_MISSING: '+key)
        baseline = entry.get('baseline', False);inputs = Trajectory_GetInputs(root, spec);model = spec.get('material_appendix', 3 if spec['case'] == 'q23' else 4)
        qualified = {};source = Trajectory_IterBaseline(root, spec['case']) if baseline else Trajectory_Iter(root, key)
        required = set(common.tolist())
        for t, state, mesh in source:
            if t not in required:continue
            r, z, nodes = Trajectory_GetNodes(state, t, model, inputs, mesh, spec)
            qualified[t] = Technical_GetQualifiedFraction(r, nodes[1, :, 0])
        if len(qualified) != len(common):raise RuntimeError('CROSS_VOLUME_SAMPLES_MISSING: '+key)
        arrays[group+'_Cmax'] = data['Cmax'][indices]
        arrays[group+'_Cmean'] = data['Cmean'][indices]
        arrays[group+'_qualified_volume_fraction'] = np.array([qualified[t] for t in common])
        arrays[group+'_radius_m'] = data['radius_m'][indices]
        end = status['event']['report_s'] if status.get('event') else 259200.
        state, mesh = Analysis_GetExactState(root, spec, end, baseline)
        r, z, nodes = Trajectory_GetNodes(state, end, model, inputs, mesh, spec)
        means = Kinetics_GetVolumeMeans(state, mesh, r[-1])
        q='q3' if group=='P3_fixed' else 'q4'
        row = dict(group=group, row_kind='model', drying_completed=bool(status.get('event')), drying_time_h=status.get('drying_time_h'),
            endpoint_time_s=end, endpoint_Cmax=float(nodes[1].max()), endpoint_Cmean=float(means[1]), source_case_id=key,
            convergence_status=validation['status'] if group == 'P3_shrink' else 'NOT_INDEPENDENTLY_REFINED' if group == 'P4_fixed' else ('PASS' if all(official[q][key] for key in ['time_convergence_passed','spatial_convergence_passed']) else 'FAIL'),
            material_appendix=model, shrinking_radius=spec['shrink'],
            qualified_fraction_definition='annular volume where reconstructed C<0.15; not water mass fraction',
            endpoint_reason='own genuine drying event' if status.get('event') else 'NOT_DRY_WITHIN_72H; endpoint is final observation, not drying time')
        for hour in [24, 48, 72]:
            i = int(hour*60)
            for metric in ['Cmax', 'Cmean', 'qualified_volume_fraction']:
                row[f'{metric}_{hour}h'] = float(arrays[group+'_'+metric][i])
        rows.append(row)
    interactions = {}
    for metric in ['Cmax', 'Cmean', 'qualified_volume_fraction']:
        values = {row['group']:row[metric+'_72h'] for row in rows}
        interactions[metric+'_72h'] = values['P4_shrink']-values['P4_fixed']-values['P3_shrink']+values['P3_fixed']
    interactions['drying_time_h'] = None if any(row['drying_time_h'] is None for row in rows) else rows[3]['drying_time_h']-rows[2]['drying_time_h']-rows[1]['drying_time_h']+rows[0]['drying_time_h']
    interactions['drying_time_reason'] = 'P4_fixed has no drying event within 72 h' if interactions['drying_time_h'] is None else 'all four own events available'
    arrays['time_s'] = common
    path = Path(root)/'work/studies/technical/plot_payload/geometry_property_cross.npz'
    Storage_WriteArray(path, **arrays)
    return dict(study_id='geometry_property_cross', groups=rows, interactions=interactions,
        interaction_definition='Y(P4,shrink)-Y(P4,fixed)-Y(P3,shrink)+Y(P3,fixed)',
        inference_scope='factorial model contrasts; P4_fixed lacks independent refinement, so no fully certified interaction error bound',
        path=path.relative_to(root).as_posix(), sha256=Baseline_HashFile(path),
        source_ids=[row['source_case_id'] for row in rows], time_range_s=[0., 259200.],
        units=dict(time_s='s', Cmax='kg/kg', Cmean='kg/kg', qualified_volume_fraction='dimensionless', radius_m='m'))


def Technical_Summarize(root, index, publish=True):
    root = Path(root);manifest = StudyPlot_ReadManifest(root, validate_technical=False)
    Technical_Freeze(root, manifest)
    validation = Technical_ValidateCross(root, index)
    cross = Technical_BuildCross(root, manifest, validation)
    kinetics = {}
    for key, entry in manifest['series'].items():
        if entry['kind'] == 'production':
            print('TECHNICAL_KINETICS '+key, flush=True)
            kinetics[key] = Kinetics_Extract(root, manifest, key)
    refinement_path = root/'work/studies/technical/refinement2d/index.json'
    refinement = Baseline_ReadJson(refinement_path) if refinement_path.exists() else dict(status='PARTIAL_2D', reason='full 60x188 cost probe not yet executed', cases={})
    result = dict(schema_version=1, baseline_id=manifest['baseline_id'], study_id='final_technical_completion',
        cross_validation=validation, geometry_property_cross=cross, kinetics=kinetics,
        kinetics_summary=kinetics[manifest['baseline_keys']['q4']]['timing'], refinement2d=refinement,
        status='PASS' if validation['status'] == 'PASS' else 'CROSS_VALIDATION_FAILED')
    payload_files = {}
    for entry in [cross, *kinetics.values(), *validation['entries']]:
        payload_files[entry['path']] = dict(path=entry['path'], sha256=entry['sha256'], purpose='prepared technical analysis')
    for check in validation['checks']:
        payload_files[check['series_path']] = dict(path=check['series_path'], sha256=check['series_sha256'], purpose='own spatial/time comparison')
    for spec, status in zip(validation['specs'], validation['statuses']):
        prefix='work/studies/experiments/'+spec['experiment_id']+'/'
        for name, record in status['data_files'].items():
            payload_files[prefix+name] = dict(path=prefix+name, sha256=record['sha256'], purpose='independent cross trajectory')
        for name in ['spec.json','status.json']:
            payload_files[prefix+name] = dict(path=prefix+name, sha256=Baseline_HashFile(root/(prefix+name)), purpose='cross identity and validation source')
    for record in refinement.get('cases',{}).values():
        for item in record.get('source_files',[]):payload_files[item['path']]=item
        if record.get('data_path'):
            name=record['data_path'];payload_files[name]=dict(path=name,sha256=record['data_sha256'],purpose='full 2D comparison')
    result['payload_files'] = list(payload_files.values())
    path = root/'work/studies/technical/plot_payload/technical_manifest.json'
    result['seal'] = hashlib.sha256(json.dumps(result, sort_keys=True, allow_nan=False).encode()).hexdigest()
    Storage_WriteJson(path, result)
    if publish:
        from .technical_export import Technical_Publish
        Technical_Publish(root, manifest, result)
    Baseline_Check(root)
    Technical_Freeze(root, manifest)
    return result
