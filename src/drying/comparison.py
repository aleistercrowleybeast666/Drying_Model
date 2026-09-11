import csv
import json
from pathlib import Path
import numpy as np
from .cases import Case_GetId, Case_LoadMesh, Case_IterFields, Case_LoadConfig, Case_LoadInputs, Case_ReadStatus
from .sampling import Sampling_GetNodes
from .geometry import Geometry_GetCells
from .storage import Storage_WriteJson
from .diagnostics import Diagnostics_Record
from .outputs import Output_GetEnd, Output_GetSelected, Output_ReadJson, Output_UpdateSummary, Output_PrepareFolders


def Comparison_IterFields(root, case_id):
    path=Path(root)/'work/cache'/case_id/'paired_events.npz'
    extras=[]
    if path.exists():
        with np.load(path) as data:
            if str(data['fingerprint'])!=Case_ReadStatus(root,case_id)['fingerprint']:
                raise RuntimeError('CACHE_MISMATCH: paired endpoint states')
            fields = data['fields'] if 'fields' in data else [data[f'field_{i}'] for i in range(len(data['time_s']))]
            extras=list(zip(data['time_s'].tolist(),fields))
    status=Case_ReadStatus(root,case_id)
    if status.get('event') and not any(abs(t-status['event']['report_s'])<1e-8 for t,_ in extras):
        with np.load(Path(root)/'work/cache'/case_id/'event.npz') as saved:
            extras.append((float(saved['time_s']),saved['state'].copy()))
        extras.sort(key=lambda item:item[0])
    index=0
    for t,field in Case_IterFields(root,case_id):
        while index<len(extras) and extras[index][0]<t-1e-8:
            yield extras[index]
            index+=1
        if index<len(extras) and abs(extras[index][0]-t)<1e-8:
            yield extras[index]
            index+=1
        else:
            yield t,field
    yield from extras[index:]


def Comparison_ReadSnapshot(root, case_id, at_time):
    folder = Path(root)/'work/cache'/case_id
    status = Case_ReadStatus(root, case_id)
    if status.get('event') and abs(status['event']['report_s']-at_time) < 1e-8:
        with np.load(folder/'event.npz') as block:
            return block['state'].copy()
    for path in [folder/'paired_events.npz', *sorted(folder.glob('chunk_*.npz'))]:
        if not path.exists():
            continue
        with np.load(path) as block:
            if str(block['fingerprint']) != status['fingerprint']:
                raise RuntimeError('CACHE_MISMATCH: snapshot fingerprint')
            indices = np.flatnonzero(abs(block['time_s']-at_time) < 1e-8)
            if len(indices):
                index = int(indices[0])
                return (block['fields'][index] if 'fields' in block else block[f'field_{index}']).copy()
    if status.get('execution_mode') == 'stage_schedule':
        stage = next((s for s in status['stages'] if at_time < s['t_end']-1e-8),status['stages'][-1])
        return Comparison_ReadSnapshot(root,stage['case_id'],at_time)
    raise RuntimeError(f'PLOT_FAILED: exact cached field {case_id} at t={at_time} is unavailable')


def Comparison_Run(root, case_filter='all'):
    root = Path(root)
    Output_PrepareFolders(root)
    cfg = Case_LoadConfig(root)['comparison']
    inputs = Case_LoadInputs(root)
    validation_path = root/'work/validation/summary.json'
    validation = json.loads(validation_path.read_text(encoding='utf-8')) if validation_path.exists() else {}
    folder = root/'work/comparison'
    folder.mkdir(parents=True, exist_ok=True)
    summary_path=folder/'case_summary.json'
    summary=json.loads(summary_path.read_text(encoding='utf-8')) if summary_path.exists() else {}
    for case, model in [('q1', 1), ('q23', 3), ('q4', 4)]:
        if case_filter not in ('all',case):
            continue
        one_id = Output_GetSelected(root,case,1)
        two_id = Output_GetSelected(root,case,2)
        mesh1,mesh2 = Case_LoadMesh(root,one_id),Case_LoadMesh(root,two_id)
        one_status, two_status = Case_ReadStatus(root, one_id), Case_ReadStatus(root, two_id)
        if not one_status['complete'] or not two_status['complete']:
            raise RuntimeError('COMPARISON_INCOMPLETE: requested trajectory is still running')
        stream1, stream2 = iter(Comparison_IterFields(root, one_id)), iter(Comparison_IterFields(root, two_id))
        one, two = next(stream1, None), next(stream2, None)
        maxima = [dict(value=-1.), dict(value=-1.)]
        count, start, end = 0, None, None
        with (folder/f'{case}_pointwise.csv').open('w', newline='', encoding='utf-8-sig') as output, (folder/f'{case}_z_profiles.csv').open('w', newline='', encoding='utf-8-sig') as profile:
            writer, zwriter = csv.writer(output), csv.writer(profile)
            columns = ['time_s', 'R_m']
            for label in ['T_K', 'C_kg_kg']:
                columns.extend([f'{label}_{name}' for name in ['max_abs', 'r_m', 'z_m', 'volume_RMSE', 'midplane_max_abs', 'endface_max_abs', 'middle_zone_max_abs', 'end_zone_max_abs']])
            writer.writerow(columns)
            zwriter.writerow(['time_s', 'z_m', 'max_abs_delta_T_K', 'max_abs_delta_C_kg_kg', 'radial_weighted_mean_delta_T_K', 'radial_weighted_mean_delta_C_kg_kg'])
            while one is not None and two is not None:
                if abs(one[0]-two[0]) > 1e-8:
                    if one[0] < two[0]: one = next(stream1, None)
                    else: two = next(stream2, None)
                    continue
                t = one[0]
                if one_status.get('execution_mode') == 'stage_schedule': mesh1 = Case_LoadMesh(root,one_id,t)
                r1, _, values1 = Sampling_GetNodes(one[1], t, model, inputs, mesh1)
                r2, z2, values2 = Sampling_GetNodes(two[1], t, model, inputs, mesh2)
                reference = np.stack([np.interp(r2, r1, values1[p, :, 0]) for p in range(2)])
                delta = values2-reference[:, :, None]
                weights = Geometry_GetCells(two_status['nr'], two_status['nz'], r2[-1], mesh=mesh2)[2]
                row = [t, r2[-1]]
                for p in range(2):
                    index = np.unravel_index(np.abs(delta[p]).argmax(), delta[p].shape)
                    maximum = float(abs(delta[p][index]))
                    rmse = float(np.sqrt(np.sum(weights*delta[p, 1:-1, 1:-1]**2)/weights.sum()))
                    row.extend([maximum, r2[index[0]], z2[index[1]], rmse,
                        np.max(np.abs(delta[p, :, 0])), np.max(np.abs(delta[p, :, -1])),
                        np.max(np.abs(delta[p, :, z2 <= cfg['middle_zone_z_max_m']])),
                        np.max(np.abs(delta[p, :, z2 >= cfg['end_zone_z_min_m']]))])
                    if maximum > maxima[p]['value']:
                        maxima[p] = dict(value=maximum, signed_difference=float(delta[p][index]),
                            time_s=t, r_m=float(r2[index[0]]), z_m=float(z2[index[1]]))
                writer.writerow(row)
                if t % 60 == 0:
                    radial_weights = weights[:, 0]
                    for j, z in enumerate(z2):
                        zwriter.writerow([t, z, np.max(np.abs(delta[0, :, j])), np.max(np.abs(delta[1, :, j])),
                            np.average(delta[0, 1:-1, j], weights=radial_weights), np.average(delta[1, 1:-1, j], weights=radial_weights)])
                start = t if start is None else start
                end, count = t, count+1
                one, two = next(stream1, None), next(stream2, None)
        if count == 0:
            raise RuntimeError('COMPARISON_INCOMPLETE: no shared samples')
        relative = None
        if one_status['event'] and two_status['event']:
            relative = abs(two_status['event']['raw_event_s']-one_status['event']['raw_event_s'])/one_status['event']['raw_event_s']
        exceed = maxima[0]['value'] > cfg['temperature_tolerance_K'] or maxima[1]['value'] > cfg['moisture_tolerance'] or (relative is not None and relative > cfg['relative_time_tolerance'])
        verified = all(validation.get(case+f'_{dim}d', {}).get('time_passed', False) and validation.get(case+f'_{dim}d', {}).get('time_full_time', False) and validation.get(case+f'_{dim}d', {}).get('spatial_passed', False) for dim in [1, 2])
        status = 'END_EFFECT_NOT_NEGLIGIBLE' if exceed else ('PASS_AT_SAMPLED_TIMES' if verified and (model == 1 or relative is not None) else 'COMPARISON_INCOMPLETE')
        summary[case] = dict(status=status, one_id=one_id, two_id=two_id,
            one_fingerprint=one_status['fingerprint'], two_fingerprint=two_status['fingerprint'],
            max_abs_temperature=maxima[0], max_abs_moisture=maxima[1],
            one_drying_time_h=one_status['drying_time_h'], two_drying_time_h=two_status['drying_time_h'],
            relative_drying_time_difference=relative, sample_count=count, time_range_s=[start,end],
            fully_numerically_verified=verified, thresholds=cfg,
            coordinate_method='Same physical time/r; linear radial interpolation of reconstructed 1D field; genuine 2D field',
            scope_note='Maxima only at stored sampled times; event times compared separately. Different radial cell counts mean these discrepancies include spatial error and cannot isolate physical end effects.',
            one_grid=[one_status['nr'],one_status['nz']],two_grid=[two_status['nr'],two_status['nz']],
            official_source='1D')
        Diagnostics_Record(root, status, 'WARNING' if status != 'PASS_AT_SAMPLED_TIMES' else 'INFO',
                           case_id=case, max_abs_T=maxima[0]['value'], max_abs_C=maxima[1]['value'], relative_time_difference=relative)
        Storage_WriteJson(summary_path, summary)
    return Comparison_WriteQuestions(root, case_filter)


def Comparison_WriteQuestions(root, case_filter='all'):
    root = Path(root)
    source = Output_ReadJson(root/'work/comparison/case_summary.json')
    summary = Output_ReadJson(root/'work/comparison/summary.json')
    for case, questions in [('q1', [1]), ('q23', [2, 3]), ('q4', [4])]:
        if case_filter not in ('all', case):
            continue
        info = source[case]
        one_status = Case_ReadStatus(root, info['one_id'])
        path = root/f'work/comparison/{case}_pointwise.csv'
        with path.open(encoding='utf-8-sig') as stream:
            columns = next(csv.reader(stream))
        rows = np.loadtxt(path, delimiter=',', skiprows=1, ndmin=2)
        for q in questions:
            end = Output_GetEnd(q, one_status)
            data = rows[rows[:, 0] <= end + 1e-8]
            if len(data) < 2 or abs(data[0, 0]) > 1e-8 or abs(data[-1, 0]-end) > 1e-8:
                raise RuntimeError(f'COMPARISON_INCOMPLETE: q{q} requires cached paired endpoint {end}')
            maxima = []
            for offset in [2, 10]:
                row = data[np.argmax(data[:, offset])]
                maxima.append(dict(value=float(row[offset]), time_s=float(row[0]),
                                   r_m=float(row[offset+1]), z_m=float(row[offset+2])))
            destination = root/f'results/q{q}/q{q}_compare.csv'
            with destination.open('w', newline='', encoding='utf-8-sig') as stream:
                writer = csv.writer(stream)
                writer.writerow(columns)
                writer.writerows(data)
            record = dict(info, question=q, time_range_s=[0., end], sample_count=len(data),
                max_abs_temperature=maxima[0], max_abs_moisture=maxima[1], comparison_completed=True,
                schema_version=2, csv=str(destination.relative_to(root)))
            if q <= 2:
                record.update(one_drying_time_h=None, two_drying_time_h=None, relative_drying_time_difference=None)
            summary[f'q{q}'] = record
            Output_UpdateSummary(root, q,
                max_1d_2d_temperature_difference=maxima[0]['value'],
                max_1d_2d_moisture_difference=maxima[1]['value'],
                time_of_max_difference={name: value['time_s'] for name, value in zip(['temperature', 'moisture'], maxima)},
                location_of_max_difference={name: {key: value[key] for key in ['r_m', 'z_m']}
                                           for name, value in zip(['temperature', 'moisture'], maxima)},
                representative_section_time_s=maxima[1]['time_s'], comparison_time_range_s=[0., end],
                comparison_scope='Absolute 2D minus 1D differences at stored samples; z=0 is the midplane',
                temperature_difference_unit='K', moisture_difference_unit='kg/kg')
    Storage_WriteJson(root/'work/comparison/summary.json', summary)
    return summary


def Comparison_EnsureQuestions(root):
    summary = Output_ReadJson(Path(root)/'work/comparison/summary.json')
    for case, questions in [('q1', [1]), ('q23', [2, 3]), ('q4', [4])]:
        ids = [Output_GetSelected(root, case, dim) for dim in [1, 2]]
        statuses = [Case_ReadStatus(root, case_id) for case_id in ids]
        if any(summary.get(f'q{q}', {}).get('schema_version') != 2 or
               summary.get(f'q{q}', {}).get('one_id') != ids[0] or
               summary.get(f'q{q}', {}).get('two_id') != ids[1] or
               not (Path(root)/f'results/q{q}/q{q}_compare.csv').exists() or
               summary.get(f'q{q}', {}).get('one_fingerprint') != statuses[0]['fingerprint'] or
               summary.get(f'q{q}', {}).get('two_fingerprint') != statuses[1]['fingerprint'] or
               summary.get(f'q{q}', {}).get('time_range_s', [None, None])[-1] != Output_GetEnd(q, statuses[0])
               for q in questions):
            summary = Comparison_Run(root, case)
    return summary
