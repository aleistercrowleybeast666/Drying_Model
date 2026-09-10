import csv
import json
from pathlib import Path
import numpy as np
from scipy.interpolate import RegularGridInterpolator
from .cases import Case_GetId, Case_IterFields, Case_LoadConfig, Case_LoadInputs, Case_ReadStatus, Case_Solve
from .sampling import Sampling_GetNodes
from .storage import Storage_WriteJson
from .diagnostics import Diagnostics_Record


def Validation_CompareCaches(root, coarse_id, fine_id):
    coarse_status, fine_status = Case_ReadStatus(root, coarse_id), Case_ReadStatus(root, fine_id)
    model = dict(q1=1, q23=3, q4=4)[coarse_status['case']]
    inputs = Case_LoadInputs(root)
    maxima = [dict(value=-1.), dict(value=-1.)]
    rows = []
    coarse = iter(Case_IterFields(root, coarse_id))
    fine = iter(Case_IterFields(root, fine_id))
    a, b = next(coarse, None), next(fine, None)
    while a is not None and b is not None:
        if abs(a[0]-b[0]) > 1e-8:
            if a[0] < b[0]: a = next(coarse, None)
            else: b = next(fine, None)
            continue
        t = a[0]
        ra, za, va = Sampling_GetNodes(a[1], t, model, inputs)
        rb, zb, vb = Sampling_GetNodes(b[1], t, model, inputs)
        rr, zz = np.meshgrid(rb, zb, indexing='ij')
        coordinates = np.column_stack((rr.ravel(), zz.ravel()))
        metrics = []
        for p in range(2):
            interpolated = RegularGridInterpolator((ra, za), va[p], bounds_error=True)(coordinates).reshape(rr.shape)
            difference = vb[p]-interpolated
            index = np.unravel_index(np.abs(difference).argmax(), difference.shape)
            value = float(abs(difference[index]))
            metrics.append(value)
            if value > maxima[p]['value']:
                maxima[p] = dict(value=value, signed_difference=float(difference[index]),
                    time_s=t, r_m=float(rr[index]), z_m=float(zz[index]),
                    coarse_value=float(interpolated[index]), fine_value=float(vb[p][index]))
        rows.append((t, *metrics))
        a, b = next(coarse, None), next(fine, None)
    if not rows:
        raise RuntimeError('COMPARISON_INCOMPLETE: no common sampled times')
    event_difference = None
    event_comparison_applicable = coarse_status['cap'] == fine_status['cap']
    if event_comparison_applicable and coarse_status['event'] and fine_status['event']:
        event_difference = abs(coarse_status['event']['raw_event_s']-fine_status['event']['raw_event_s'])
    return dict(coarse_id=coarse_id, fine_id=fine_id, maxima_temperature=maxima[0],
        maxima_moisture=maxima[1], event_difference_s=event_difference,
        event_status_agrees=(bool(coarse_status['event']) == bool(fine_status['event'])) if event_comparison_applicable else True,
        event_comparison_applicable=event_comparison_applicable,
        time_range_s=[rows[0][0], rows[-1][0]], sample_count=len(rows),
        method='Piecewise bilinear reconstruction at fine-grid cells, axis, symmetry and exposed boundary nodes; physical r,z'), rows


def Validation_SaveComparison(root, name, value, rows):
    folder = Path(root)/'results/validation'
    folder.mkdir(parents=True, exist_ok=True)
    Storage_WriteJson(folder/f'{name}.json', value)
    with (folder/f'{name}.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.writer(stream)
        writer.writerow(['time_s', 'max_abs_temperature_K', 'max_abs_moisture_kg_kg'])
        writer.writerows(rows)


def Validation_Run(root, scope='all', case_filter='all'):
    root = Path(root)
    config = Case_LoadConfig(root)
    cfg, num = config['validation'], config['numerics']
    dimensions = [1, 2] if scope == 'all' else [int(scope[0])]
    summary_path = root/'results/validation/summary.json'
    summary = json.loads(summary_path.read_text(encoding='utf-8')) if summary_path.exists() else {}
    for dim in dimensions:
        for case in ['q1', 'q23', 'q4']:
            if case_filter not in ('all',case):
                continue
            base = Case_Solve(root, case, dim)
            base_id = base['case_id']
            dt = num['dt_s']/2
            temporal_cap = None if dim == 1 else cfg['two_dimensional_refinement_duration_s']
            fine = Case_Solve(root, case, dim, dt=dt, tag='half_steps', replay_id=base_id, cap=temporal_cap)
            result, rows = Validation_CompareCaches(root, base_id, fine['case_id'])
            def Passed(value):
                return (value['maxima_temperature']['value'] <= cfg['temperature_tolerance_K'] and
                    value['maxima_moisture']['value'] <= cfg['moisture_tolerance'] and
                    value['event_status_agrees'] and
                    (value['event_difference_s'] is None or value['event_difference_s'] <= cfg['event_tolerance_s']))
            passed = Passed(result)
            result.update(passed=passed, actual_base_partition_bisected=True, requested_dt_s=dt)
            Validation_SaveComparison(root, f'{case}_{dim}d_time_half', result, rows)
            if not passed:
                # Validate the half-step candidate by truly bisecting its partition again.
                quarter = Case_Solve(root, case, dim, dt=dt/2, tag='quarter_steps', replay_id=fine['case_id'], cap=temporal_cap)
                result2, rows2 = Validation_CompareCaches(root, fine['case_id'], quarter['case_id'])
                passed = Passed(result2)
                result2.update(passed=passed, actual_base_partition_bisected=True)
                Validation_SaveComparison(root, f'{case}_{dim}d_time_quarter', result2, rows2)
                if passed:
                    base, base_id = fine, fine['case_id']
                else:
                    Diagnostics_Record(root, 'TIME_CONVERGENCE_FAILED', 'WARNING', case_id=base_id)
            radial_cap = None if dim == 1 else cfg['two_dimensional_refinement_duration_s']
            radial = Case_Solve(root, case, dim, nr=cfg['refined_nr'], dt=base['dt'],
                tag='radial_refinement', cap=radial_cap)
            radial_result, radial_rows = Validation_CompareCaches(root, base_id, radial['case_id'])
            radial_result.update(assessment='QUANTIFIED',
                note='Adjacent-grid differences, not rigorous true-error bounds; no spatial acceptance tolerance supplied')
            Validation_SaveComparison(root, f'{case}_{dim}d_radial', radial_result, radial_rows)
            axial_result = None
            full_space = dim == 1 or case == 'q1'
            if dim == 2:
                axial = Case_Solve(root, case, dim, nz=cfg['refined_nz'], dt=base['dt'],
                    tag='axial_refinement', cap=radial_cap)
                axial_result, axial_rows = Validation_CompareCaches(root, base_id, axial['case_id'])
                axial_result['assessment'] = 'QUANTIFIED'
                Validation_SaveComparison(root, f'{case}_{dim}d_axial', axial_result, axial_rows)
                if not full_space:
                    Diagnostics_Record(root, 'SPATIAL_VALIDATION_INCOMPLETE', 'WARNING', case_id=base_id,
                        covered_time_s=[0, radial_cap], uncovered_time_s=[radial_cap, 259200],
                        reason='2D temporal and separate doubled spatial meshes restricted to first 1800 s based on measured base runtime and cache cost',
                        measured_base_wall_s=base['wall_s'], base_peak_rss_bytes=base['peak_rss_bytes'])
            # The prompt sets temporal and 1D/2D tolerances, but supplies no
            # spatial acceptance tolerance. Do not turn a measured mesh delta
            # into an unearned spatial PASS or silently reuse the time tolerance.
            space_T = cfg.get('spatial_temperature_tolerance_K')
            space_C = cfg.get('spatial_moisture_tolerance')
            space_time = cfg.get('spatial_event_tolerance_s')
            space_passed = (full_space and space_T is not None and space_C is not None
                and radial_result['maxima_temperature']['value'] <= space_T
                and radial_result['maxima_moisture']['value'] <= space_C
                and (radial_result['event_difference_s'] is None or
                    (space_time is not None and radial_result['event_difference_s'] <= space_time)))
            summary[f'{case}_{dim}d'] = dict(selected_id=base_id, time_passed=passed, time_full_time=full_space,
                spatial_quantified=True, spatial_full_time=full_space, radial=radial_result,
                spatial_passed=space_passed,
                spatial_acceptance_note='No spatial tolerance supplied; quantified grid sensitivity retained, not certified as grid independent',
                axial=axial_result, numerical_status='TIME_VALIDATED_SPATIAL_QUANTIFIED' if passed and full_space
                    else ('SPATIAL_VALIDATION_INCOMPLETE' if passed else 'NUMERICAL_VALIDATION_FAILED'),
                eligible_1d_export=dim == 1 and passed and space_passed)
            Storage_WriteJson(summary_path, summary)
    if 2 in dimensions:
        from .cases import Case_SolvePairEvents
        Case_SolvePairEvents(root)
    return summary
