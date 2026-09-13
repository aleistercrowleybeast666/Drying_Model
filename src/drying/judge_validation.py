"""Adapters to the existing auxiliary and solver-level conservation criteria."""
from pathlib import Path
import json
import shutil

import numpy as np

from .storage import Storage_WriteJson


def Judge_Validate2d(root,case):
    """Same validation functions, plan the required critical window once."""
    import types
    from .validation import Validation_Run
    policy=json.loads((Path(root)/'configs/auxiliary_2d_validation.json').read_text(encoding='utf-8'))
    namespace=dict(Validation_Run.__globals__);load=namespace['Case_LoadConfig']
    def Config_GetPlan(path):
        config=load(path)
        config['validation']['two_dimensional_refinement_duration_s']=max(
            config['validation']['two_dimensional_refinement_duration_s'],policy['critical_window_end_s'][case])
        return config
    namespace['Case_LoadConfig']=Config_GetPlan
    from .judge_observer import Progress_Substep
    completed=0;total=5 if case=='q1' else 7
    def Observe(original,name):
        def Step_Run(*args,**kwargs):
            nonlocal completed
            result=original(*args,**kwargs)
            if name!='Case_Solve' or (not kwargs.get('tag') and kwargs.get('cap') is None):
                completed+=1;Progress_Substep(.95*min(completed,total)/total,'二维验证完成子步骤 '+name,'validation_stage')
            return result
        return Step_Run
    for name in ['Case_Solve','Validation_CheckTime','Validation_CompareCaches','Validation_CheckEndpoint']:
        namespace[name]=Observe(namespace[name],name)
    # Comparison_Run is locally imported by Validation_Run; the final compare
    # phase is covered by its first directional comparison rather than a fake tick.
    total-=1
    run=types.FunctionType(Validation_Run.__code__,namespace,Validation_Run.__name__,Validation_Run.__defaults__)
    return run(root,scope='2d',case_filter=case)


def Judge_CheckFullEquivalence(root):
    from .judge_pipeline import Judge_ReadJson
    from .cases import Case_IterFields
    from .comparison import Comparison_IterFields
    root=Path(root)
    tables=Judge_ReadJson(root/'work/recompute/production.json')
    full=Judge_ReadJson(root/'work/recompute/full_production.json'); records={}
    for case,table in tables.items():
        other=full[case]
        reference=iter(Comparison_IterFields(root,other['case_id'])); row=next(reference,None)
        peak=0.;count=0
        for t,state in Case_IterFields(root,table['case_id']):
            while row is not None and row[0]<t-1e-8:row=next(reference,None)
            if row is None or abs(row[0]-t)>1e-8 or row[1].shape!=state.shape:
                raise RuntimeError('FULL_HORIZON_EQUIVALENCE_INCOMPLETE: '+case+' '+str(t))
            peak=max(peak,float(np.max(np.abs(state-row[1]))));count+=1
        if peak>1e-10 or table.get('event')!=other.get('event'):
            raise RuntimeError('FULL_HORIZON_EQUIVALENCE_FAILED: '+case+' '+str(peak))
        records[case]=dict(status='PASS',table_case_id=table['case_id'],table_fingerprint=table['fingerprint'],
            full_case_id=other['case_id'],full_fingerprint=other['fingerprint'],compared_saved_states=count,
            max_absolute_state_difference=peak,exact_event_agreement=True,
            scope='All actual table states and report endpoint; extension continues beyond the table end')
    Storage_WriteJson(root/'work/recompute/full_equivalence.json',records)
    return records


def Judge_CompleteAuxiliaryWindows(root, case, entry):
    from .cases import Case_LoadConfig, Case_Solve
    from .validation import Validation_CompareCaches, Validation_SaveComparison, Validation_SaveEntry
    policy = json.loads((root/'configs/auxiliary_2d_validation.json').read_text(encoding='utf-8'))
    end = policy['critical_window_end_s'][case]
    cfg = Case_LoadConfig(root)['mesh']
    for direction, nr, nz in [('radial',cfg['refined_nr'],cfg['base_nz']), ('axial',cfg['base_nr'],cfg['refined_nz'])]:
        if entry[direction]['time_range_s'][-1] >= end:
            continue
        fine = Case_Solve(root, case, 2, nr=nr, nz=nz, cap=end, tag=f'judge_auxiliary_{direction}_t{end}')
        value, rows = Validation_CompareCaches(root, entry['selected_id'], fine['case_id'], end_time=end)
        value.update(assessment='QUANTIFIED', note='Same existing directional refinement, covering the frozen auxiliary critical window')
        Validation_SaveComparison(root, f'{case}_2d_{direction}', value, rows)
        entry[direction] = value
    Validation_SaveEntry(root, case+'_2d', entry)


def Judge_PrepareMass(root,only=None,write_manifest=True):
    from .judge_pipeline import Judge_ReadJson
    from .judge_tasks import Task_GetCaseSpec
    from .studies.trajectory import Trajectory_GetSpec
    from .studies.selection import Selection_GetFactor
    root = Path(root)
    baseline = Judge_ReadJson(root/'work/baseline_snapshot/baseline_manifest.json')
    result = dict(specs={}, statuses={}, series={})
    for case in ['q1','q23','q4']:
        if only and only[0]!=case:continue
        source = Judge_ReadJson(root/'work/recompute/production.json')[case]
        spec = Task_GetCaseSpec(root, source)
        # Audit every accepted step of the actual source, with an explicit scope.
        # This audit spec is distinct from an extension trajectory specification.
        if source.get('purpose') == 'table_production':
            spec['schedule'] = [dict(t_start=s['t_start'],t_end=s['t_end'],nr=s['nr'],nz=1) for s in source['stages']]
            spec['audit_scope'] = 'entire table_production accepted trajectory through real drying report'
        key = spec['experiment_id']
        if not only or only[1]=='M00':
            result['specs'][key] = spec; result['statuses'][key] = source; result['series'][key] = dict(baseline=True)
        for mode in ['M10','M01','M11']:
            if only and only[1]!=mode:continue
            spec = Trajectory_GetSpec(root, case, mode, factor=Selection_GetFactor(root,case,mode))
            key = spec['experiment_id']; status = Judge_ReadJson(root/'work/studies/experiments'/key/'status.json')
            if not status.get('complete'):
                raise RuntimeError('MASS_SOURCE_INCOMPLETE: '+key)
            result['specs'][key] = spec; result['statuses'][key] = status; result['series'][key] = dict(baseline=False)
    if not write_manifest:return result
    folder = root/'work/validation/mass_balance'; folder.mkdir(parents=True, exist_ok=True)
    # Freeze the previously measured policy as a release resource; never fit it
    # again to this machine's residuals.
    shutil.copy2(root/'configs/mass_balance_policy.json', folder/'policy.json')
    Storage_WriteJson(folder/'source_manifest.json', result)
    return dict(cases=len(result['specs']), cache_reused=False)


def Judge_PublishMass(root):
    from .judge_pipeline import Judge_ReadJson
    from .studies.mass_report import MassReport_Publish, MassReport_GetBrief
    root = Path(root)
    manifest = Judge_ReadJson(root/'work/validation/mass_balance/source_manifest.json')
    path = root/'results/studies/validation_summary.json'
    if not path.exists():
        Storage_WriteJson(path, {})
    summary = MassReport_Publish(root, manifest, refresh_overview=False)
    brief = MassReport_GetBrief(root, summary)
    text = ('# 验证摘要\n\n水质量守恒：'+summary['status']+f"，{summary['completed_case_count']}/12。\n\n"
        f"最大绝对残差 {summary['max_mass_balance_abs_error_kg']:.6e} kg；相对残差 {summary['max_mass_balance_rel_error']:.6e}。\n\n"
        f"Q4 remesh 最大水质量跳变 {summary['q4_max_remesh_water_mass_jump_abs_kg']:.6e} kg。\n")
    overview = root/'results/studies/overview.md'
    if (root/'work/studies/plot_payload/study_manifest.json').exists():
        from .studies.synthesis import Synthesis_RefreshOverview
        Synthesis_RefreshOverview(root)
    else:
        validation=Judge_ReadJson(path)
        official=validation.get('official_one_dimensional',{})
        if official:
            text += '\n正式一维验证（历史 fixed-grid 为 legacy / diagnostic only）：\n\n'
            text += '\n'.join(f"- {case}: {row['numerical_status']}" for case,row in official.items())+'\n'
        auxiliary=validation.get('two_dimensional_auxiliary_validation')
        if auxiliary:
            text += '\n二维辅助用途验收：'+('PASS' if auxiliary['two_dimensional_auxiliary_validation_passed'] else 'FAIL')+'；完整二维独立性仍为 PARTIAL_2D。\n'
        overview.write_text(text, encoding='utf-8')
    facts = root/'results/paper_facts.json'
    if not facts.exists():
        Storage_WriteJson(facts, dict(scope='solver mass balance only; extensions not run', solver_mass_balance=brief))
        (root/'results/paper_facts.md').write_text(text, encoding='utf-8')
    if summary['status'] != 'PASS':
        raise RuntimeError('MASS_BALANCE_'+summary['status']+'; see work/validation/mass_balance/summary.json')
    return dict(summary=brief, cache_reused=False)
