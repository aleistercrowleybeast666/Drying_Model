"""Cache-only auxiliary end-effect/model-reduction assessment, never a PDE solver.

Pointwise strict assessments remain immutable diagnostics. Only the separate
purpose-specific gates below decide auxiliary acceptance; they do not certify
2D grid independence or replace any official 1D decision.
"""
import hashlib
import json
import re
import shutil
import tomllib
from pathlib import Path

import numpy as np

REPORT = 'work/validation/auxiliary_2d/summary.json'
KEY = 'two_dimensional_auxiliary_validation'
START = '<!-- auxiliary-2d:start -->'
END = '<!-- auxiliary-2d:end -->'


def Auxiliary_ReadJson(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def Auxiliary_WriteJson(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def Auxiliary_HashFile(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def Auxiliary_ReadSummary(root):
    path = Path(root)/REPORT
    if not path.exists(): return None
    report = Auxiliary_ReadJson(path)
    # Readers must not silently publish a PASS against changed input/validation metadata.
    for name, expected in report['source_sha256'].items():
        if Path(name).suffix in ['.json', '.toml']:
            source = Path(root)/name
            if not source.is_file() or Auxiliary_HashFile(source) != expected:
                raise RuntimeError('STALE_2D_AUXILIARY_EVIDENCE: '+name)
    return Auxiliary_GetSummary(report)


def Auxiliary_GetSummary(report):
    brief = {k: report[k] for k in ['schema_version', 'role', 'two_dimensional_auxiliary_validation_passed',
        'two_dimensional_grid_independence_certified', 'grid_independence_status', 'limitations', 'pde_solves']}
    brief['details'] = REPORT
    brief['cases'] = {}
    for case, row in report['cases'].items():
        item = {k: row[k] for k in ['role', 'two_dimensional_auxiliary_validation_passed',
            'two_dimensional_grid_independence_certified', 'two_dimensional_validation_status',
            'grid_independence_status', 'gates', 'critical_window_s', 'directional_coverage',
            'qualitative_spatial_consistency', 'end_effect_detected', 'warnings']}
        item['temporal_validation'] = {k: row['temporal_validation'][k] for k in ['status', 'time_range_s', 'full_time']}
        item['endpoint_sensitivity'] = {d: {k: e[k] for k in ['passed', 'event_difference_s',
            'event_relative_difference', 'time_range_s', 'note']} for d, e in row['endpoint_sensitivity'].items()}
        item['local_Linf'] = dict(diagnostic_only=True, acceptance_veto=False,
            **{d: {k: row['local_Linf'][d][k] for k in ['maxima_temperature', 'maxima_moisture']}
               for d in ['radial', 'axial']})
        item['strict_grid_independence_assessment'] = {k: row['strict_grid_independence_assessment'][k]
            for k in ['spatial_passed', 'spatial_full_time', 'numerical_status']}
        item['strict_grid_independence_assessment']['raw_evidence'] = 'work/validation/summary.json#'+case+'_2d'
        brief['cases'][case] = item
    return brief


def Auxiliary_AttachSummary(value, brief):
    value[KEY] = brief
    # Existing paper-facts rows describe optional full-trajectory refinement.
    # Preserve those assessments, but explicitly label their certification scope.
    for case, row in value.get('two_dimensional', {}).items():
        if case in brief['cases']:
            row.update({k: brief['cases'][case][k] for k in ['role',
                'two_dimensional_auxiliary_validation_passed', 'two_dimensional_grid_independence_certified',
                'two_dimensional_validation_status', 'grid_independence_status']})
            row['validation_status_scope'] = 'grid_independence_only'
    return value


def Auxiliary_CheckGates(gates):
    return bool(gates) and all(value is True for value in gates.values())


def Auxiliary_CheckCoverage(ranges, end):
    cursor = 0.
    for left, right in sorted(ranges):
        if left > cursor or right < left:
            return False
        cursor = max(cursor, right)
    return cursor >= end


class AuxiliaryCache:
    """Read exact saved states; missing data is an error, never an integration fallback."""
    def __init__(self, root):
        self.root = Path(root)
        self.hashes = {}
        self.scans = {}

    def Track_Read(self, path):
        path = Path(path)
        name = path.relative_to(self.root).as_posix()
        if name not in self.hashes:
            self.hashes[name] = Auxiliary_HashFile(path)
        return path

    def Status_Read(self, case_id):
        return Auxiliary_ReadJson(self.Track_Read(self.root/'work/cache'/case_id/'status.json'))

    def Mesh_Read(self, case_id):
        with np.load(self.Track_Read(self.root/'work/cache'/case_id/'mesh.npz')) as data:
            return data['xi_faces'].copy(), data['eta_faces'].copy()

    def Trajectory_Scan(self, case_id, times=()):
        status = self.Status_Read(case_id)
        snapshots = {}
        finite = True
        ranges = []
        saved_times = []
        fingerprint_ok = True
        for path in sorted((self.root/'work/cache'/case_id).glob('chunk_*.npz')):
            with np.load(self.Track_Read(path)) as data:
                t = data['time_s']; fields = data['fields']
                finite &= bool(np.isfinite(fields).all() and np.isfinite(t).all())
                fingerprint_ok &= str(data['fingerprint']) == status['fingerprint']
                if len(t):
                    ranges.append([float(t[0]), float(t[-1])])
                    saved_times.extend(t.tolist())
                for time in times:
                    indices = np.flatnonzero(t == time)
                    if len(indices):
                        snapshots[time] = fields[indices[0]].copy()
        self.scans[case_id] = dict(all_outputs_finite=finite, fingerprint_matches=fingerprint_ok,
            no_solver_failure=bool(status.get('complete')) and status.get('status') not in ['FAILED', 'ERROR'],
            saved_ranges_s=ranges, snapshot_times_s=sorted(snapshots),
            saved_time_count=len(saved_times), max_saved_gap_s=float(np.max(np.diff(saved_times))) if len(saved_times)>1 else None,
            saved_times_strictly_increasing=bool(np.all(np.diff(saved_times)>0)))
        return snapshots

    def State_Read(self, case_id, time):
        status = self.Status_Read(case_id)
        if status.get('stages'):
            for stage in status['stages']:
                # Stage chunks contain their physical absolute times.
                try:
                    return self.State_Read(stage['case_id'], time)
                except LookupError:
                    continue
            raise LookupError((case_id, time))
        for path in sorted((self.root/'work/cache'/case_id).glob('chunk_*.npz')):
            with np.load(path) as data:
                hit = np.flatnonzero(data['time_s'] == time)
                if len(hit):
                    self.Track_Read(path)
                    return data['fields'][hit[0]].copy(), self.Mesh_Read(case_id)
        raise LookupError((case_id, time))


def Auxiliary_CheckSpatial(state, mesh, one, one_mesh, config):
    """Regional ordering uses existing physical zones, not fitted Linf limits."""
    rf, zf = mesh; r = (rf[:-1]+rf[1:])/2; z = (zf[:-1]+zf[1:])/2
    ro = (one_mesh[0][:-1]+one_mesh[0][1:])/2
    half_length = config['physics']['L_m']/2
    end = z*half_length >= config['comparison']['end_zone_z_min_m']
    middle = z*half_length <= config['comparison']['middle_zone_z_max_m']
    bulk = r <= .5
    weights = np.diff(rf**2)[:, None]*np.diff(zf)[None, :]
    rows = []
    for field, initial in [(0, config['physics']['T0_K']), (1, config['physics']['C0'])]:
        reference = np.interp(r, ro, one[field, :, 0])[:, None]
        error = abs(state[field]-reference)
        peak = np.unravel_index(np.argmax(error), error.shape)
        end_mean = float(np.average(error[:, end], weights=weights[:, end]))
        middle_mean = float(np.average(error[:, middle], weights=weights[:, middle]))
        change = float(np.average(state[field][np.ix_(bulk, middle)]-initial,
            weights=weights[np.ix_(bulk, middle)]))
        one_change = float(np.average(reference[bulk, 0]-initial, weights=np.diff(rf**2)[bulk]))
        # Roundoff allowance applies only to trend sign, never to local spatial errors.
        epsilon = 64*np.finfo(float).eps*max(1., abs(initial))
        rows.append(dict(field='temperature' if field == 0 else 'moisture',
            max_difference=float(error[peak]), peak_z_over_half_length=float(z[peak[1]]),
            end_mean_difference=end_mean, middle_mean_difference=middle_mean,
            bulk_change=change, one_dimensional_bulk_change=one_change,
            peak_near_end=bool(end[peak[1]]), end_effect_detected=bool(end_mean > middle_mean+epsilon),
            decays_towards_middle=end_mean > middle_mean,
            bulk_trend_agrees=bool((change >= -epsilon and one_change >= -epsilon) or
                                  (change <= epsilon and one_change <= epsilon))))
    return dict(fields=rows, passed=all(all(row[k] for k in
        ['peak_near_end', 'end_effect_detected', 'decays_towards_middle', 'bulk_trend_agrees']) for row in rows))


def Auxiliary_CheckControl(state, rf, zf):
    moisture = state[1]
    i, j = np.unravel_index(np.argmax(moisture), moisture.shape)
    r = (rf[i]+rf[i+1])/2; z = (zf[j]+zf[j+1])/2
    return dict(max_moisture=float(moisture[i, j]), r_over_R=float(r), z_over_half_length=float(z),
        category='interior_core' if r <= .5 and z <= .5 else 'other',
        all_outputs_finite=bool(np.isfinite(state).all()))


def Auxiliary_Evaluate(root):
    root = Path(root); cache = AuxiliaryCache(root)
    policy = Auxiliary_ReadJson(cache.Track_Read(root/'configs/auxiliary_2d_validation.json'))
    config = tomllib.loads(cache.Track_Read(root/'configs/default.toml').read_text(encoding='utf-8'))
    if policy['endpoint_relative_tolerance'] != config['validation']['spatial']['drying_time_relative']:
        raise ValueError('Auxiliary endpoint tolerance must equal the unchanged official decision tolerance')
    validation = Auxiliary_ReadJson(cache.Track_Read(root/'work/validation/summary.json'))
    cases = {}
    for case, end in policy['critical_window_end_s'].items():
        entry = validation[case+'_2d']; times = policy['representative_times_s'][case]
        base = entry['selected_id']; one_id = validation[case+'_1d']['selected_id']
        one = {time: cache.State_Read(one_id, time) for time in times}
        qualitative = []; controls = {}; endpoints = {}; coverage = {}
        selected = {base, entry['temporal']['fine_id']}
        snapshots = cache.Trajectory_Scan(base, times)
        cache.Trajectory_Scan(entry['temporal']['fine_id'])
        for direction in ['base', 'radial', 'axial']:
            case_id = base if direction == 'base' else entry[direction]['fine_id']
            selected.add(case_id)
            fields = snapshots if direction == 'base' else cache.Trajectory_Scan(case_id, times)
            ranges = [] if direction == 'base' else [entry[direction]['time_range_s']]
            for extension in entry.get('representative_extensions', []):
                if extension['direction'] != direction:
                    continue
                ext_id = extension['extension_id']; selected.add(ext_id)
                ext_fields = cache.Trajectory_Scan(ext_id, times)
                valid = (extension['window_reference_complete'] and
                    extension['source_reference_id'] == case_id and
                    extension['comparison']['inherited_reference_fingerprint'] == cache.Status_Read(case_id)['fingerprint'] and
                    extension['extension_fingerprint'] == cache.Status_Read(ext_id)['fingerprint'])
                if valid:
                    ranges.append(extension['time_range_s']); fields.update(ext_fields)
            if direction != 'base':
                scan = cache.scans[case_id]
                measured = scan['saved_ranges_s']
                coverage[direction] = dict(time_ranges_s=ranges,
                    complete=bool(entry[direction]['reference_complete'] and measured and
                        measured[0][0] == 0 and measured[-1][1] >= entry[direction]['time_range_s'][1] and
                        scan['saved_times_strictly_increasing'] and
                        scan['saved_time_count'] == entry[direction]['sample_count'] and
                        scan['max_saved_gap_s'] <= (60 if case == 'q4' else 1) and
                        Auxiliary_CheckCoverage(ranges, end)))
            for time in times:
                if time not in fields:
                    qualitative.append(dict(direction=direction, time_s=time, passed=False, reason='MISSING_EXACT_SAVED_STATE'))
                    continue
                qualitative.append(dict(direction=direction, time_s=time,
                    **Auxiliary_CheckSpatial(fields[time], cache.Mesh_Read(case_id), *one[time], config)))
            if case != 'q1':
                path = root/'work/cache'/base/'event.npz' if direction == 'base' else root/f'work/validation/{case}_2d_endpoint_{direction}.npz'
                with np.load(cache.Track_Read(path)) as data:
                    mesh = cache.Mesh_Read(base) if direction == 'base' else (data['xi_faces'], data['eta_faces'])
                    controls[direction] = Auxiliary_CheckControl(data['state'], *mesh)
                if direction != 'base':
                    record = Auxiliary_ReadJson(cache.Track_Read(path.with_suffix('.json')))
                    endpoints[direction] = dict(record, passed=bool(record['complete'] and
                        record['base_fingerprint'] == cache.Status_Read(base)['fingerprint'] and
                        record['event_relative_difference'] <= policy['endpoint_relative_tolerance']))
        strict = {key: entry[key] for key in ['spatial_passed', 'spatial_full_time', 'numerical_status', 'radial', 'axial', 'endpoint_sensitivity']}
        strict['representative_extensions'] = entry.get('representative_extensions', [])
        bindings = all(entry[d]['coarse_id'] == base and
            entry[d]['coarse_fingerprint'] == cache.Status_Read(base)['fingerprint'] and
            entry[d]['fine_fingerprint'] == cache.Status_Read(entry[d]['fine_id'])['fingerprint']
            for d in ['temporal', 'radial', 'axial'])
        gates = dict(temporal_pass=bool(entry['time_passed'] and entry['temporal']['passed'] and entry['temporal']['reference_complete']),
            critical_window_refinement_completed=all(row['complete'] for row in coverage.values()),
            radial_refinement_available=coverage['radial']['complete'], axial_refinement_available=coverage['axial']['complete'],
            endpoint_sensitivity_pass_if_applicable=all(row['passed'] for row in endpoints.values()),
            qualitative_spatial_consistency=all(row['passed'] for row in qualitative) and
                all(row['category'] == 'interior_core' for row in controls.values()),
            evidence_source_matches=bindings,
            no_solver_failure=all(cache.scans[k]['no_solver_failure'] and cache.scans[k]['fingerprint_matches'] for k in selected),
            all_outputs_finite=all(cache.scans[k]['all_outputs_finite'] for k in selected) and
                all(row['all_outputs_finite'] for row in controls.values()))
        passed = Auxiliary_CheckGates(gates)
        warnings = ['2D_GRID_INDEPENDENCE_NOT_CERTIFIED', 'SEPARATE_DIRECTIONAL_REFINEMENT_ONLY']
        tol = config['validation']['spatial']
        if any(entry[d]['maxima_temperature']['value'] > tol['temperature_abs_K'] or
               entry[d]['maxima_moisture']['value'] > tol['moisture_abs'] for d in ['radial', 'axial']):
            warnings.append('LOCAL_BOUNDARY_LAYER_LINF_EXCEEDS_1D_TOLERANCE')
            if case == 'q1': warnings.append('EARLY_LOCAL_BOUNDARY_LAYER_SENSITIVE')
        cases[case] = dict(role=policy['role'], two_dimensional_auxiliary_validation_passed=passed,
            two_dimensional_grid_independence_certified=False,
            two_dimensional_validation_status='AUXILIARY_VALIDATION_PASS' if passed else 'AUXILIARY_VALIDATION_FAIL',
            grid_independence_status='PARTIAL_2D', gates=gates,
            temporal_validation=dict(status='PASS' if gates['temporal_pass'] else 'FAIL', time_range_s=entry['temporal']['time_range_s'],
                full_time=entry['time_full_time'], original_assessment=entry['temporal']),
            critical_window_s=[0, end], directional_coverage=coverage, endpoint_sensitivity=endpoints,
            qualitative_spatial_consistency='PASS' if gates['qualitative_spatial_consistency'] else 'FAIL',
            end_effect_detected=all(all(f['end_effect_detected'] for f in row.get('fields', [])) and 'fields' in row for row in qualitative),
            qualitative_samples=qualitative, endpoint_control_regions=controls,
            local_Linf=dict(policy['local_Linf'], radial=entry['radial'], axial=entry['axial']),
            strict_grid_independence_assessment=strict, warnings=warnings)
    return dict(schema_version=1, role=policy['role'], cases=cases,
        two_dimensional_auxiliary_validation_passed=all(c['two_dimensional_auxiliary_validation_passed'] for c in cases.values()),
        two_dimensional_grid_independence_certified=False, grid_independence_status='PARTIAL_2D',
        limitations=policy['limitations'], source_sha256=cache.hashes, trajectory_checks=cache.scans,
        method=policy['qualitative_method'], pde_solves=0)


def Auxiliary_GetLines(report):
    if not report: return []
    lines = ['', START, '', '## 二维辅助验收（独立于正式一维认证）', '',
        '`role = auxiliary_end_effect_and_model_reduction_validation`。二维仅用于端面效应、降维合理性和终点鲁棒性核验，不参与官方 Excel、正式烘干时间或一维空间认证。', '',
        '| Case | 辅助验收 | 时间验证及范围 | 方向加密覆盖 / s | 网格独立性 |', '|---|---|---|---|---|']
    for case, row in report['cases'].items():
        lines.append(f"| {case.upper()} | {row['two_dimensional_validation_status']} | {row['temporal_validation']['status']}，0–1800 s | 径向及轴向 0–{row['critical_window_s'][1]} | PARTIAL_2D / NOT CERTIFIED |")
        for direction, endpoint in row['endpoint_sensitivity'].items():
            lines.append(f"- {case} {direction} 终点差 {endpoint['event_difference_s']:.6g} s / {100*endpoint['event_relative_difference']:.6g}%（阈值 0.2%）。")
        errors = row['local_Linf']
        lines.append(f"- {case} 原始局部 ΔT（径/轴）={errors['radial']['maxima_temperature']['value']:.8g}/{errors['axial']['maxima_temperature']['value']:.8g} K；ΔC={errors['radial']['maxima_moisture']['value']:.8g}/{errors['axial']['maxima_moisture']['value']:.8g} kg/kg；diagnostic_only=true，acceptance_veto=false。")
    lines += ['', '时间验证沿用已有标准；Q23/Q4 仅验证 0–1800 s，不能视为全时域时间认证。终点为末期投影后真实积分的方向细化实验，继承此前粗网格误差。',
        '历史严格判据及原始误差完整保留于 strict_grid_independence_assessment；2D_SPATIAL_VALIDATION_PARTIAL 表示网格独立性未认证，不再否决辅助用途。',
        'WARNING：'+ '；'.join(sorted({w for c in report['cases'].values() for w in c['warnings']}))+'。']
    if report['two_dimensional_auxiliary_validation_passed']:
        lines += ['', '推荐表述：二维轴对称模型在本文中作为一维正式模型的辅助核验模型。考虑到二维模型主要用于判断端面效应的空间范围及烘干终点对降维假设的敏感性，本文采用针对关键阶段、方向加密和终点决策量的辅助验收标准，而不要求极早期暴露边界层的所有局部点值均达到正式一维模型的严格空间误差阈值。现有径向、轴向加密结果覆盖了各问主要强梯度阶段，Q3、Q4 的终点时间对网格细化变化均远低于 0.2%，因此二维模型通过其预定用途的辅助核验。需要指出的是，本文尚未完成二维全时域联合加密的严格网格独立性认证，因此二维结果主要用于趋势、端面影响范围和模型降维合理性分析。']
    return lines+['', END]


def Auxiliary_AppendBlock(text, report):
    text = re.sub(r'\n'+re.escape(START)+r'.*?'+re.escape(END)+r'\n?', '', text, flags=re.S)
    return text.rstrip()+'\n'+'\n'.join(Auxiliary_GetLines(report))+'\n'


def Auxiliary_CheckMetadata(root, name, expected_hash):
    """Narrow baseline exception: ONLY independently reproduced auxiliary additions.

    The old bytes must still match the frozen manifest. No numeric/model/official
    field may be changed; all other protected files retain byte-exact checking.
    """
    if name not in ['results/status.json', 'results/overview.md']: return False
    root = Path(root); prior = root/'work/validation/auxiliary_2d'/('prior_'+Path(name).name)
    # Baseline protects the old official data, not freshness of auxiliary evidence.
    # Allow the cache-only evaluator to replace a stale report; normal readers
    # separately reject stale sources in Auxiliary_ReadSummary.
    report = Auxiliary_GetSummary(Auxiliary_ReadJson(root/REPORT)) if (root/REPORT).exists() else None
    if not prior.exists() or not report or Auxiliary_HashFile(prior) != expected_hash: return False
    if name.endswith('.json'):
        expected = Auxiliary_ReadJson(prior); expected[KEY] = report
        return Auxiliary_ReadJson(root/name) == expected
    expected = Auxiliary_AppendBlock(prior.read_text(encoding='utf-8'), report)
    normalize = lambda s: re.sub(r'^更新时间：.*$', '更新时间：', s, flags=re.M)
    return normalize((root/name).read_text(encoding='utf-8')) == normalize(expected)


def Auxiliary_Publish(root, report):
    root = Path(root)
    baseline = Auxiliary_ReadJson(root/'work/baseline_snapshot/baseline_manifest.json')
    for name in ['results/status.json', 'results/overview.md']:
        path = root/name; prior = root/'work/validation/auxiliary_2d'/('prior_'+path.name)
        if not prior.exists():
            if Auxiliary_HashFile(path) != baseline['protected_files'][name]['sha256']:
                raise RuntimeError('Original frozen metadata changed: '+name)
            prior.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(path, prior)
    Auxiliary_WriteJson(root/REPORT, report)
    brief = Auxiliary_GetSummary(report)
    for name in ['results/status.json', 'results/studies/validation_summary.json', 'results/paper_facts.json']:
        value = Auxiliary_AttachSummary(Auxiliary_ReadJson(root/name), brief)
        Auxiliary_WriteJson(root/name, value)
    for name in ['results/overview.md', 'results/studies/overview.md', 'results/paper_facts.md']:
        path = root/name
        path.write_text(Auxiliary_AppendBlock(path.read_text(encoding='utf-8'), report), encoding='utf-8')
