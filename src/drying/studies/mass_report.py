"""Read-only aggregation and publication of independent solver mass audits."""
from pathlib import Path
import math
import sys
from datetime import datetime, timezone
from ..storage import Storage_WriteJson
from .baseline import Baseline_ReadJson, Baseline_HashFile


def MassReport_ReadSummary(root):
    path = Path(root)/'work/validation/mass_balance/summary.json'
    return MassReport_GetBrief(root, Baseline_ReadJson(path)) if path.exists() else None


def MassReport_GetBrief(root, summary):
    result = {key:value for key,value in summary.items() if key not in ['cases','policy']}
    result['details_path']='work/validation/mass_balance/summary.json'
    result['details_sha256']=Baseline_HashFile(Path(root)/result['details_path'])
    names=['case','mode','source_case_id','status','initial_water_mass_kg','remaining_water_mass_kg',
        'cumulative_outflow_water_mass_kg','max_mass_balance_abs_error_kg','max_mass_balance_rel_error',
        'final_mass_balance_abs_error_kg','final_mass_balance_rel_error','time_of_max_error_s',
        'accepted_steps','source_file','source_sha256']
    result['cases']=[dict({name:row[name] for name in names},
        max_remesh_water_mass_jump_abs_kg=max((t['remesh_water_mass_jump_abs'] for t in row['remesh']),default=0.),
        max_remesh_water_mass_jump_rel=max((t['remesh_water_mass_jump_rel'] for t in row['remesh']),default=0.))
        for row in summary['cases']]
    if summary.get('policy'):
        result['policy']={key:summary['policy'][key] for key in ['relative_tolerance','remesh_relative_tolerance']}
        result['policy'].update(source_file='work/validation/mass_balance/policy.json',
            source_sha256=Baseline_HashFile(Path(root)/'work/validation/mass_balance/policy.json'),
            note='FP64 accepted-step RK4 conservation audit; detailed rounding/accumulation rationale in the policy file; existing convergence thresholds unchanged')
    return result


def MassReport_GetLines(summary):
    if not summary:return []
    lines = ['', '## 水质量守恒审计', '',
        f"solver_mass_balance：{summary['status']}；已完成 {summary['completed_case_count']}/12 个完整生产轨迹。"]
    if summary['completed_case_count']:
        lines += [f"最大绝对残差 {summary['max_mass_balance_abs_error_kg']:.6e} kg；最大相对残差 {summary['max_mass_balance_rel_error']:.6e}。",
            f"Q4 换网格最大水质量跳变 {summary['q4_max_remesh_water_mass_jump_abs_kg']:.6e} kg。",
            '采用实际接受的 RK4 步与原边界通量积分；导出数据仅作诊断。完整记录：`work/validation/mass_balance/`。']
    if summary.get('policy'):
        lines += [f"独立审计阈值：相对残差 ≤ {summary['policy']['relative_tolerance']:.1e}，换网格相对质量跳变 ≤ {summary['policy']['remesh_relative_tolerance']:.1e}；未修改空间或时间收敛阈值。"]
        lines += ['', '| 模式 | Q1 | Q23 | Q4 |', '|---|---|---|---|']
        for mode in ['M00','M10','M01','M11']:
            statuses=[next((r['status'] for r in summary['cases'] if r['case']==case and r['mode']==mode),'INCOMPLETE') for case in ['q1','q23','q4']]
            lines.append('| '+mode+' | '+' | '.join(statuses)+' |')
    if summary.get('failures'):
        lines += ['失败案例：'+', '.join(summary['failures'])+'；具体时间、阶段、边界通量与换网格信息见对应记录。']
    return lines


def MassReport_Assess(record, policy):
    audit = record['solver_mass_balance']; initial = audit['initial_water_mass_kg']
    relative = audit['max_mass_balance_rel_error']
    checks = dict(full_trajectory=record.get('complete', False) and record.get('full_accepted_partition_verified', False),
        replay_identity=record['replay_verification']['status']=='PASS',
        finite_positive_initial_mass=math.isfinite(initial) and initial>0,
        integrated_mass_balance=math.isfinite(relative) and relative <= policy['relative_tolerance'] and
            math.isfinite(audit['max_mass_balance_abs_error_kg']) and
            audit['max_mass_balance_abs_error_kg'] <= initial*policy['relative_tolerance'],
        remesh_mass_balance=all(math.isfinite(row['remesh_water_mass_jump_rel']) and
            row['remesh_water_mass_jump_rel'] <= policy['remesh_relative_tolerance'] for row in record['remesh']))
    return dict(status='PASS' if all(checks.values()) else 'FAIL', checks=checks,
        absolute_tolerance_kg=initial*policy['relative_tolerance'],
        relative_tolerance=policy['relative_tolerance'], remesh_relative_tolerance=policy['remesh_relative_tolerance'],
        nonphysical_mass_source_or_sink_detected=not (checks['integrated_mass_balance'] and checks['remesh_mass_balance']),
        export_mass_balance_affects_pass=False)


def MassReport_FreezePolicy(root, cases):
    """Choose an operation-count allowance only after all raw measurements exist.

Residual magnitudes are recorded for review, never used to fit the tolerance.
The existing policy is immutable across resume/publication runs.
"""
    path=Path(root)/'work/validation/mass_balance/policy.json'
    if path.exists():return Baseline_ReadJson(path)
    expected={(case,mode) for case in ['q1','q23','q4'] for mode in ['M00','M10','M01','M11']}
    if len(cases)!=12 or {(r['case'],r['mode']) for r in cases}!=expected:
        raise RuntimeError('MASS_POLICY_REQUIRES_ALL_12_MEASUREMENTS')
    steps=max(r['accepted_steps'] for r in cases);epsilon=sys.float_info.epsilon
    condition=1+max(r['integrated_absolute_boundary_flow_kg']/r['initial_water_mass_kg'] for r in cases)
    # Conservative engineering scale for FP64 state-update roundoff over one
    # independent trajectory. It is not a rigorous worst-case error theorem.
    scale=64*epsilon*math.sqrt(steps)*condition
    tolerance=10.**math.ceil(math.log10(scale))
    policy=dict(schema_version=1,created_at=datetime.now(timezone.utc).isoformat(),
        relative_tolerance=tolerance,absolute_tolerance_definition='initial_water_mass_kg * relative_tolerance',
        remesh_relative_tolerance=1e-12,fp64_epsilon=epsilon,maximum_case_accepted_steps=steps,
        total_accepted_steps=sum(r['accepted_steps'] for r in cases),maximum_mass_sum_condition_scale=condition,
        rounding_operation_allowance=64,estimated_relative_roundoff_scale=scale,
        selection_formula='10**ceil(log10(64*eps64*sqrt(max_case_accepted_steps)*(1+max_case(integral_abs_boundary_flux/Mw0))))',
        selection_scope='engineering FP64 roundoff allowance, not a rigorous worst-case bound; rounded once to a common decimal scale; no observed residual in the threshold formula',
        rk4_rationale='FV internal face fluxes cancel; bd(t)*cell_volume(t) is constant for prescribed uniform radial shrinkage. The same accepted-step RK4 weights update C and integrate boundary flow, so RK4 trajectory truncation error does not create a defect of this linear discrete mass invariant.',
        accumulation_rationale='Boundary outflow uses signed stage flux and Kahan summation; leading compensated-sum error is order eps times accumulated absolute flow. Remaining defect includes repeated FP64 cell-state updates and volume products.',
        remesh_rationale='Retains the existing Stage_ProjectState relative volume-integral criterion 1e-12. At the same remesh time the effective dry basis and physical radius are common scalars.',
        existing_space_and_time_thresholds_changed=False,residual_used_to_fit_tolerance=False,
        measured_before_policy=[dict(case=r['case'],mode=r['mode'],source_file=r['source_file'],
            source_sha256=r['source_sha256'],observed_max_relative_residual=r['max_mass_balance_rel_error']) for r in cases])
    Storage_WriteJson(path,policy)
    return policy


def MassReport_Publish(root, manifest):
    root = Path(root); folder = root/'work/validation/mass_balance'
    keys = [k for k, spec in manifest['specs'].items() if spec['kind']=='production']
    cases = []; missing = []; policy_path = folder/'policy.json'
    policy = Baseline_ReadJson(policy_path) if policy_path.exists() else None
    for key in keys:
        path = folder/key/'measurement.json'
        if not path.exists():missing.append(key);continue
        record = Baseline_ReadJson(path)
        if not record.get('complete'):missing.append(key);continue
        for name, digest in record['source']['source_files'].items():
            if Baseline_HashFile(root/name) != digest:raise RuntimeError('MASS_REPORT_SOURCE_MISMATCH: '+name)
        for name, digest in record['source']['numerical_sources'].items():
            if Baseline_HashFile(root/name) != digest:raise RuntimeError('MASS_REPORT_NUMERICAL_SOURCE_MISMATCH: '+name)
        for name, digest in record['source']['audit_sources'].items():
            if Baseline_HashFile(Path(__file__).with_name(name)) != digest:raise RuntimeError('MASS_REPORT_AUDIT_SOURCE_MISMATCH: '+name)
        for entry in record['audit_files']:
            if Baseline_HashFile(root/entry['path']) != entry['sha256']:raise RuntimeError('MASS_REPORT_TRACE_MISMATCH')
        assessment = MassReport_Assess(record, policy) if policy else dict(status='MEASURED')
        cases.append(dict(case=record['case'], mode=record['mode'], source_case_id=key,
            **assessment, **record['solver_mass_balance'], remesh=record['remesh'],
            source_file=path.relative_to(root).as_posix(), source_sha256=Baseline_HashFile(path)))
        if policy:
            Storage_WriteJson(folder/key/'assessment.json', dict(case=record['case'], mode=record['mode'],
                source_case_id=key, **assessment, policy_sha256=Baseline_HashFile(policy_path),
                solver_mass_balance=record['solver_mass_balance'], remesh=record['remesh']))
    if not policy and not missing:
        MassReport_FreezePolicy(root,cases)
        return MassReport_Publish(root,manifest)
    summary = dict(schema_version=1, status='MEASURED' if not missing else 'INCOMPLETE',
        method='solver_mass_balance', completed_case_count=len(cases), expected_case_count=12,
        cases=cases, missing_cases=missing, export_mass_balance_affects_pass=False,
        tolerance_status='PENDING_MEASURED_RESIDUAL_REVIEW',
        max_mass_balance_abs_error_kg=max((r['max_mass_balance_abs_error_kg'] for r in cases), default=0.),
        max_mass_balance_rel_error=max((r['max_mass_balance_rel_error'] for r in cases), default=0.),
        q4_max_remesh_water_mass_jump_abs_kg=max((t['remesh_water_mass_jump_abs'] for r in cases if r['case']=='q4' for t in r['remesh']), default=0.),
        q4_max_remesh_water_mass_jump_rel=max((t['remesh_water_mass_jump_rel'] for r in cases if r['case']=='q4' for t in r['remesh']), default=0.))
    if policy:
        summary.update(policy=policy, tolerance_status='FROZEN_AFTER_MEASUREMENT',
            failures=[r['case']+'/'+r['mode'] for r in cases if r['status']=='FAIL'],
            nonphysical_mass_source_or_sink_detected=any(r['nonphysical_mass_source_or_sink_detected'] for r in cases))
        summary['status']='INCOMPLETE' if missing else 'FAIL' if summary['failures'] else 'PASS'
    Storage_WriteJson(folder/'summary.json', summary)
    if policy:
        brief=MassReport_GetBrief(root,summary)
        validation_path=root/'results/studies/validation_summary.json'
        validation=Baseline_ReadJson(validation_path); validation['solver_mass_balance']=brief
        Storage_WriteJson(validation_path,validation)
        facts_path=root/'results/paper_facts.json'
        if facts_path.exists():
            from .paper_facts import PaperFacts_WriteMarkdown
            facts=Baseline_ReadJson(facts_path); facts['solver_mass_balance']=brief
            Storage_WriteJson(facts_path,facts); PaperFacts_WriteMarkdown(root,facts)
        from .synthesis import Synthesis_RefreshOverview
        Synthesis_RefreshOverview(root)
        print(f'MASS_BALANCE_{summary["status"]} {len(cases)}/12 max_abs={summary["max_mass_balance_abs_error_kg"]:.6e} kg max_rel={summary["max_mass_balance_rel_error"]:.6e}',flush=True)
    return summary
