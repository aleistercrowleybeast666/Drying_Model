"""Judge DAG definitions and numerical adapters; all kernels remain authoritative."""
from pathlib import Path
import json
import shutil
from types import SimpleNamespace

import numpy as np

from .storage import Storage_WriteJson, Storage_WriteArray


def Task_ArchiveReference(root,spec):
    """Explicit force option preserves old evidence outside the active cache."""
    import time
    root=Path(root).resolve()
    if 'release_v2' in root.parts:raise RuntimeError('RELEASE_V2_PROTECTED')
    source=(root/'work/studies/experiments'/spec['experiment_id']).resolve()
    target=(root/'work/recompute/forced_references'/str(time.time_ns())/spec['experiment_id']).resolve()
    if not source.is_relative_to(root/'work/studies/experiments') or not target.is_relative_to(root/'work/recompute/forced_references'):
        raise ValueError('REFERENCE_PATH_OUTSIDE_WORKSPACE')
    if source.exists():target.parent.mkdir(parents=True,exist_ok=True);shutil.move(str(source),str(target))


def Task_GetExtendedPlan(requested, originals):
    jobs = []
    original_dependencies = ['A.'+c for c in originals]
    need_2d = bool(requested & {'aux-2d', 'extensions'})
    need_1d = bool(requested & {'one-dimensional', 'extensions'})
    for case in originals:
        if need_1d:
            jobs.append(dict(key='B.reference.'+case,group='validation',kind='reference_1d',case=case,mode='M00',experiment_kind='full_reference',factor=2,horizon=1800 if case=='q1' else 259200,dependencies=['A.'+case],pde=True,private='ref_'+case))
            jobs.append(dict(key='B.1d.'+case, group='validation', kind='validation_1d', case=case,
                dependencies=['B.reference.'+case], pde=True, private=case))
        if need_2d:
            jobs.append(dict(key='B.2d.'+case, group='validation', kind='validation_2d', case=case,
                dependencies=['A.'+case], pde=True, private='two_'+case))
    if need_1d:
        jobs.append(dict(key='B.1d.publish',group='validation',kind='validation_publish',
            dependencies=['B.1d.'+c for c in originals],pde=False,exclusive=True))
    if need_2d:
        jobs.append(dict(key='B.auxiliary', group='validation', kind='auxiliary', dependencies=['B.2d.'+c for c in originals], pde=False, exclusive=True))
    studies = bool(requested & {'mass-balance','extensions'})
    if 'extensions' in requested:
        for case in originals:
            jobs.append(dict(key='D.full.'+case, group='extension', kind='full_production', case=case,
                dependencies=['A.'+case], pde=True, private='full_'+case))
    if studies:
        foundation = original_dependencies
        jobs.append(dict(key='shared.baseline', group='extension' if 'extensions' in requested else 'validation',
            kind='baseline', dependencies=foundation, pde=False, exclusive=True, full=False))
        jobs.append(dict(key='shared.thermal_warmup', group='extension' if 'extensions' in requested else 'validation',
            kind='thermal_warmup', dependencies=['shared.baseline'], pde=False, exclusive=True))
        for mode in ['M10','M01','M11']:
            for case in ['q23','q4','q1']:
                prefix=f'D.{mode}.{case}'
                jobs.append(dict(key=prefix+'.production', group='extension' if 'extensions' in requested else 'validation',
                    kind='experiment', case=case, mode=mode, experiment_kind='production', dependencies=['shared.thermal_warmup'], pde=True))
                if 'extensions' in requested:
                    for kind in ['full_reference','time_half']:
                        jobs.append(dict(key=prefix+'.'+kind, group='extension', kind='experiment', case=case,
                            mode=mode, experiment_kind=kind, dependencies=[prefix+'.production'], pde=True))
        if 'extensions' in requested:
            jobs.append(dict(key='shared.matched_baseline',group='extension',kind='baseline',full=True,dependencies=['shared.baseline','B.auxiliary']+['D.full.'+c for c in originals],pde=False,exclusive=True))
            for case in ['q23','q4','q1']:
                jobs.append(dict(key=f'D.M00.{case}.full_reference',group='validation',kind='reference_1d',case=case,mode='M00',experiment_kind='full_reference',factor=2,horizon=1800 if case=='q1' else 259200,dependencies=['A.'+case],pde=True,private='ref_'+case))
                for kind in ['matched']:
                    jobs.append(dict(key=f'D.M00.{case}.{kind}', group='extension', kind='experiment', case=case,
                        mode='M00', experiment_kind=kind, dependencies=['shared.matched_baseline'], pde=True))
                if case != 'q1':
                    for tail in [30,90]:
                        jobs.append(dict(key=f'D.tail.{case}.{tail}', group='extension', kind='experiment', case=case,
                            mode='M00', experiment_kind='tail', tail_minutes=tail, dependencies=['shared.baseline'], pde=True))
            jobs.append(dict(key='D.fixed_radius', group='extension', kind='experiment', case='q4', mode='M00',
                experiment_kind='fixed_radius', dependencies=['shared.baseline'], pde=True))
            for kind in ['production','full_reference','time_half']:
                jobs.append(dict(key='D.cross.'+kind, group='extension', kind='experiment', cross=True, case='q23', mode='M00',
                    experiment_kind=kind, dependencies=['D.cross.production'] if kind=='time_half' else ['shared.baseline'], pde=True))
            dependencies = [j['key'] for j in jobs if j['kind'] in ['experiment','reference_1d']]+['B.auxiliary','B.1d.publish']
            jobs.append(dict(key='D.publish', group='extension', kind='extension_publish', dependencies=dependencies, pde=False, exclusive=True,gifs='thermal-gif' in requested))
            jobs.append(dict(key='B.study_figures',group='validation',kind='validation_study_plots',
                dependencies=['D.publish'],pde=False,exclusive=True))
    if 'mass-balance' in requested:
        for mode in ['M00','M10','M01','M11']:
            for case in ['q23','q4','q1']:
                dependency='A.'+case if mode=='M00' else f'D.{mode}.{case}.production'
                jobs.append(dict(key=f'B.mass.{mode}.{case}',group='validation',kind='mass_measure',mode=mode,case=case,
                    dependencies=[dependency,'shared.baseline'],pde=True))
        jobs.append(dict(key='B.mass.prepare',group='validation',kind='mass_prepare',
            dependencies=[j['key'] for j in jobs if j['kind']=='mass_measure'],pde=False,exclusive=True))
        jobs.append(dict(key='B.mass.publish',group='validation',kind='mass_publish',dependencies=['B.mass.prepare']+
            (['D.publish'] if 'extensions' in requested else []),pde=False,exclusive=True))
    if 'consistency' in requested:
        jobs.append(dict(key='B.consistency', group='validation', kind='consistency',
            dependencies=[j['key'] for j in jobs]+original_dependencies, pde=False, exclusive=True))
    for choice in ['static','gif']:
        if choice in requested:
            jobs.append(dict(key='C.'+choice, group='plot', kind='plot', selection=choice,
                dependencies=original_dependencies+(['B.auxiliary'] if need_2d else []), pde=False, exclusive=True))
    if 'developer-audit' in requested:
        for case in originals:
            jobs.append(dict(key='developer.fixed.'+case,group='validation',kind='developer_diagnostic',case=case,dependencies=['A.'+case],pde=True,private='dev_'+case))
    return jobs


def Task_PrepareBaseline(root, full=False):
    from .cases import Case_LoadConfig, Case_GetSourceHash, Case_ReadStatus
    from .frozen_mesh import Frozen_ReadManifest, Frozen_HashValue, Frozen_HashFile
    from .judge_pipeline import Judge_ReadJson
    root = Path(root)
    frozen = Frozen_ReadManifest(root)
    production = Judge_ReadJson(root/'work/recompute/full_production.json' if full else root/'work/recompute/production.json')
    # A private validation worker contains one real table source only. The other
    # entries are configuration descriptors, never fabricated complete results.
    selected = {c+'_1d':dict(case=c, schedule=schedule, cap=schedule[-1]['t_end']) for c,schedule in frozen['schedules'].items()}
    selected.update({c+'_1d':value for c,value in production.items()})
    validation = Judge_ReadJson(root/'work/validation/summary.json')
    for case in ['q1','q23','q4']:
        entry = validation.get(case+'_2d', {})
        if entry.get('selected_id'):
            selected[case+'_2d'] = Case_ReadStatus(root, entry['selected_id'])
    protected = {}
    for path in (root/'work/validation/mesh_profiles').glob('*_monitor.npz'):
        protected[path.relative_to(root).as_posix()] = dict(sha256=Frozen_HashFile(path), size=path.stat().st_size)
    names = ['data/inputs.npz','data/input_manifest.json','configs/default.toml','configs/stage_schedule.json']
    names += ['src/drying/'+name+'.py' for name in ['materials','boundaries','operators','rk4','sampling','inputs','events','geometry','cases','stages']]
    for name in names:
        path = root/name; protected[name] = dict(sha256=Frozen_HashFile(path), size=path.stat().st_size)
    for status in selected.values():
        if not status.get('complete'):continue
        for case_id in [status['case_id']]+[s['case_id'] for s in status.get('stages',[])]:
            folder=root/'work/cache'/case_id
            paths=[folder/'mesh.npz',folder/'status.json',*sorted(folder.glob('chunk_*.npz'))]
            if (folder/'event.npz').exists():paths.append(folder/'event.npz')
            for path in paths:
                protected[path.relative_to(root).as_posix()]=dict(sha256=Frozen_HashFile(path),size=path.stat().st_size)
    for path in (root/'results/tables').glob('result*.xlsx'):
        protected[path.relative_to(root).as_posix()]=dict(sha256=Frozen_HashFile(path),size=path.stat().st_size)
    config = Case_LoadConfig(root)
    result = dict(schema_version=2, baseline_id=Frozen_HashValue(dict(frozen_mesh=frozen, config=config,
        numerical_core_hash=Case_GetSourceHash(root), purpose='judge_full_horizon_definition')),
        config=config, selected=selected, numerical_core_hash=Case_GetSourceHash(root),
        input=Judge_ReadJson(root/'data/input_manifest.json'),
        validation=validation, status=Judge_ReadJson(root/'results/status.json'), protected_files=protected,
        policy='Explicit runtime sources. Table and full-horizon cases have independent identities; descriptors are not results.',
        full_horizon=full, workbooks=[], images=[])
    Storage_WriteJson(root/'work/baseline_snapshot/baseline_manifest.json', result)
    return result


def Task_GetCaseSpec(root, status, kind='production', replay=None):
    from .studies.trajectory import Trajectory_GetSpec
    spec = Trajectory_GetSpec(root, status['case'], kind=kind, replay=replay)
    spec.update(experiment_id=status['case_id'], fingerprint=status['fingerprint'], case_cache_id=status['case_id'])
    return spec


def Task_ValidateCase(root, case, runtime=None):
    from .judge_pipeline import Judge_ReadJson
    from .table_solver import Table_SolveSchedule
    from .cases import Case_ReadStatus
    from .studies.trajectory import Trajectory_GetSpec, Trajectory_Solve
    from .studies.cache import Cache_SealExperiment
    from .studies.analysis import Analysis_ExtractSeries, Analysis_Compare
    from .stages import Stage_AssessTransfers
    from .validation import Validation_SaveEntry
    production = Judge_ReadJson(root/'work/recompute/production.json')[case]
    production = Case_ReadStatus(root, production['case_id'])
    Task_PrepareBaseline(root)
    spec = Task_GetCaseSpec(root, production)
    reference_spec = Trajectory_GetSpec(root, case, kind='full_reference', factor=2)
    if runtime and Path(runtime)!=Path(root):
        shared=Path(runtime)/'work/studies/experiments'/reference_spec['experiment_id']
        if not shared.exists():raise RuntimeError('SHARED_REFERENCE_IDENTITY_MISMATCH')
        shutil.copytree(shared,Path(root)/'work/studies/experiments'/reference_spec['experiment_id'],dirs_exist_ok=True)
    reference = Cache_SealExperiment(root, reference_spec, Trajectory_Solve(root, reference_spec))
    left = Analysis_ExtractSeries(root, spec)
    right = Analysis_ExtractSeries(root, reference_spec)
    spatial = Analysis_Compare(root, spec, reference_spec, left, right, production, reference,
        formal_end_s=production['actual_end_s'])
    half = Table_SolveSchedule(root, case, dt=.125, replay_id=production['case_id'], label='time_half')
    half_spec = Task_GetCaseSpec(root, half, 'time_half', production['case_id'])
    half_entry = Analysis_ExtractSeries(root, half_spec)
    temporal = Analysis_Compare(root, spec, half_spec, left, half_entry, production,
        dict(half, full_history_verified=True), formal_end_s=min(production['actual_end_s'], half['actual_end_s']))
    remesh = Stage_AssessTransfers(production['transfers'], dict(temperature_abs_K=.01, moisture_abs=.01))
    space_passed = spatial['status']=='PASS' and remesh['remesh_transfer_passed']
    passed = space_passed and temporal['status']=='PASS'
    entry = dict(selected_id=production['case_id'], selected_fingerprint=production['fingerprint'],
        numerical_status='PASS' if passed else 'FAIL', fixed_grid_validation='legacy / diagnostic only; NOT_RERUN',
        fixed_grid_spatial_passed=None, stage_schedule_spatial_passed=space_passed, spatial_passed=space_passed,
        spatial_convergence_passed=space_passed, time_passed=temporal['status']=='PASS', time_full_time=True,
        spatial_full_time=True, eligible_1d_export=True, full_schedule_reference=spatial, temporal=temporal,
        remesh=remesh, remesh_transfer_passed=remesh['remesh_transfer_passed'],
        certificate_scope='formal original outputs plus both genuinely integrated endpoints; internal audit only')
    Validation_SaveEntry(root, case+'_1d', entry)
    Storage_WriteJson(root/f'work/validation/{case}_judge_summary.json', entry)
    if not passed:
        raise RuntimeError('JUDGE_VALIDATION_FAILED: '+case+' '+json.dumps(entry,ensure_ascii=False))
    return dict(validation=entry, cache_reused=False)


def Task_Execute(root, task):
    from .judge_pipeline import Judge_ReadJson
    kind = task['kind']; case = task.get('case')
    if kind == 'original':
        from .table_solver import Table_SolveSchedule
        from .export import Export_Run
        from .table_reference import Table_CheckReference, Table_SealProduction
        from .storage import Storage_HashFiles
        old = Judge_ReadJson(root/'work/recompute/production.json').get(case, {})
        status = Table_SolveSchedule(root, case)
        Table_SealProduction(root,case,status)
        outputs=Judge_ReadJson(root/'work/diagnostics/export_manifest.json').get('outputs',[])
        questions=dict(q1=[1],q23=[2,3],q4=[4])[case]
        cached=old.get('fingerprint')==status['fingerprint'] and all(any(row['question']==q and
            row.get('fingerprint')==status['fingerprint'] and (root/row['path']).is_file() and
            Storage_HashFiles([root/row['path']])==row.get('workbook_hash') for row in outputs) for q in questions)
        if not cached:
            Export_Run(root, case, source_case_id=status['case_id'])
        from .judge_observer import Progress_Substep
        Progress_Substep(.96,'四表数据核对 / 冻结参考','reference',upper=.99,expected_s=1.)
        reference = Table_CheckReference(root, case, status)
        Storage_WriteJson(root/'work/recompute/production.json', {case:status})
        return dict(production=status, numeric_reference=reference, cache_reused=cached)
    if kind == 'validation_1d':
        return Task_ValidateCase(root, case, task.get('runtime'))
    if kind == 'reference_1d':
        from .studies.trajectory import Trajectory_GetSpec,Trajectory_Solve
        from .studies.cache import Cache_SealExperiment
        Task_PrepareBaseline(root)
        spec=Trajectory_GetSpec(root,case,kind='full_reference',factor=2)
        if task.get('force_reference'):Task_ArchiveReference(root,spec)
        old=Judge_ReadJson(root/'work/studies/experiments'/spec['experiment_id']/'status.json')
        result=Cache_SealExperiment(root,spec,Trajectory_Solve(root,spec,resume=True))
        return dict(experiment_id=spec['experiment_id'],status=result,cache_reused=old.get('complete',False))
    if kind == 'developer_diagnostic':
        from .validation import Validation_Run
        return dict(diagnostic_only=True,validation=Validation_Run(root,scope='1d',case_filter=case),cache_reused=False)
    if kind == 'validation_publish':
        from .judge_plots import Judge_DrawSpatialEvidence
        return Judge_DrawSpatialEvidence(root)
    if kind == 'validation_study_plots':
        from .studies.plot_contract import StudyPlot_ReadManifest, StudyPlot_GetHash
        from .studies.plots import StudyPlot_Draw,StudyPlot_SetStyle
        StudyPlot_SetStyle();manifest=StudyPlot_ReadManifest(root)
        files=[StudyPlot_Draw(root,manifest,name).relative_to(root).as_posix() for name in ['verification_evidence']]
        path=root/'work/studies/diagnostics/render_manifest.json'
        receipt=Judge_ReadJson(path)
        receipt['files']=[row for row in receipt.get('files',[]) if row['path'] not in files]
        receipt['files'] += [dict(path=name,sha256=StudyPlot_GetHash(root/name),group='validation') for name in files]
        Storage_WriteJson(path,receipt)
        from .studies.synthesis import Synthesis_RefreshOverview
        Synthesis_RefreshOverview(root)
        return dict(files=files,pde_solves=0,cache_reused=False)
    if kind == 'validation_2d':
        from .validation import Validation_Run, Validation_SaveEntry
        production = Judge_ReadJson(root/'work/recompute/production.json')[case]
        summary = Judge_ReadJson(root/'work/validation/summary.json')
        if case+'_1d' not in summary:
            Validation_SaveEntry(root, case+'_1d', dict(selected_id=production['case_id'], selected_fingerprint=production['fingerprint'],
                numerical_status='NOT_RERUN_IN_TABLE_ONLY_MODE'))
        from .judge_validation import Judge_Validate2d
        summary = Judge_Validate2d(root,case)
        # The current auxiliary policy contains the previously reviewed critical
        # window; ensure it is fully covered, not just the old 1800 s default.
        from .judge_validation import Judge_CompleteAuxiliaryWindows
        Judge_CompleteAuxiliaryWindows(root, case, summary[case+'_2d'])
        return dict(validation=Judge_ReadJson(root/'work/validation/summary.json')[case+'_2d'], cache_reused=False)
    if kind == 'auxiliary':
        from .auxiliary2d import Auxiliary_Evaluate, Auxiliary_GetSummary
        report = Auxiliary_Evaluate(root)
        Storage_WriteJson(root/'work/validation/auxiliary_2d/summary.json', report)
        path = root/'results/studies/validation_summary.json'
        summary = Judge_ReadJson(path); summary['two_dimensional_auxiliary_validation'] = Auxiliary_GetSummary(report)
        Storage_WriteJson(path, summary)
        from .judge_plots import Judge_DrawValidation
        Judge_DrawValidation(root)
        if not report['two_dimensional_auxiliary_validation_passed']:
            raise RuntimeError('AUXILIARY_VALIDATION_FAILED; full 2D grid independence remains PARTIAL_2D')
        return dict(auxiliary=Auxiliary_GetSummary(report), cache_reused=False)
    if kind == 'full_production':
        from .stages import Stage_Solve
        from .frozen_mesh import Frozen_ReadManifest
        schedule = Frozen_ReadManifest(root)['schedules'][case]
        status = Stage_Solve(root, case, schedule, label='conservative' if case=='q23' else 'default')
        Storage_WriteJson(root/'work/recompute/full_production.json', {case:status})
        return dict(production=status, purpose='extension_full_horizon', full_horizon=True, cache_reused=False)
    if kind == 'baseline':
        if task['full']:
            from .judge_validation import Judge_CheckFullEquivalence
            from .judge_pipeline import Judge_PublishOriginal
            Judge_CheckFullEquivalence(root)
            Judge_PublishOriginal(root)
        result = Task_PrepareBaseline(root, task['full'])
        return dict(baseline_id=result['baseline_id'], full_horizon=task['full'], cache_reused=False)
    if kind == 'thermal_warmup':
        from .judge_pipeline import Judge_WarmKernels
        Judge_WarmKernels(root, ['M10','M01','M11'])
        return dict(cache_reused=False, pde_outputs=0)
    if kind == 'experiment':
        from .studies.trajectory import Trajectory_GetSpec, Trajectory_Solve
        from .studies.selection import Selection_GetFactor
        from .studies.cache import Cache_SealExperiment
        mode = task['mode']; experiment_kind = task['experiment_kind']
        factor = Selection_GetFactor(root, case, mode)*(2 if experiment_kind=='full_reference' else 1)
        if task.get('cross'):
            from .studies.cross_spec import Cross_GetPlan
            spec = next(s for s in Cross_GetPlan(root) if s['kind']==experiment_kind)
        else:
            replay = Trajectory_GetSpec(root, case, mode, factor=factor)['experiment_id'] if experiment_kind=='time_half' else None
            spec = Trajectory_GetSpec(root, case, mode, kind=experiment_kind, factor=factor,
                tail_minutes=task.get('tail_minutes',60), replay=replay)
        if task.get('force_reference'):Task_ArchiveReference(root,spec)
        old = Judge_ReadJson(root/'work/studies/experiments'/spec['experiment_id']/'status.json')
        result = Cache_SealExperiment(root, spec, Trajectory_Solve(root, spec, resume=True))
        if not result.get('complete'):
            raise RuntimeError('STUDY_REFERENCE_INCOMPLETE: '+spec['experiment_id'])
        return dict(experiment_id=spec['experiment_id'], status=result, cross=task.get('cross', False),
            purpose='extension_full_horizon', full_horizon=True, cache_reused=old.get('complete',False))
    if kind == 'extension_publish':
        Task_PrepareBaseline(root,full=True)
        from .studies.analysis import Studies_Summarize
        from .studies.technical_analysis import Technical_Summarize
        from .judge_plots import Judge_DrawExtensions
        if (root/'work/studies/technical/plot_payload/technical_manifest.json').exists():
            from .studies.plot_contract import StudyPlot_ReadManifest
            from .studies.technical_contract import Technical_ReadPayload
            manifest=StudyPlot_ReadManifest(root)
            Technical_ReadPayload(root,manifest)
            Judge_DrawExtensions(root,gifs=task.get('gifs',False))
            return dict(status='PASS',cache_reused=True)
        Studies_Summarize(root, Judge_ReadJson(root/'results/studies/study_index.json'))
        manifest=Judge_ReadJson(root/'work/studies/plot_payload/study_manifest.json')
        Storage_WriteJson(root/'work/studies/diagnostics/render_manifest.json',dict(manifest_seal=manifest['seal'],
            files=[],status='NOT_RENDERED',pde_solves=0))
        summary = Technical_Summarize(root, Judge_ReadJson(root/'work/studies/technical/index.json'))
        if summary['status'] != 'PASS':
            raise RuntimeError('TECHNICAL_VALIDATION_FAILED')
        Judge_DrawExtensions(root,gifs=task.get('gifs',False))
        return dict(status=summary['status'], cache_reused=False)
    if kind == 'mass_prepare':
        from .judge_validation import Judge_PrepareMass
        return Judge_PrepareMass(root)
    if kind == 'mass_measure':
        from .studies.mass_balance import MassBalance_MeasureCase
        from .judge_validation import Judge_PrepareMass
        manifest=Judge_PrepareMass(root,only=(case,task['mode']),write_manifest=False)
        key = next(k for k,v in manifest['specs'].items() if v['case']==case and v['mode']==task['mode'])
        result = MassBalance_MeasureCase(root, manifest, key)
        return dict(measurement=result['solver_mass_balance'], cache_reused=False)
    if kind == 'mass_publish':
        from .judge_validation import Judge_PublishMass
        return Judge_PublishMass(root)
    if kind == 'consistency':
        from .table_reference import Table_CheckReference
        production = Judge_ReadJson(root/'work/recompute/production.json')
        for c,status in production.items():
            Table_CheckReference(root, c, status)
        return dict(status='PASS', cases=list(production), cache_reused=False)
    if kind == 'plot':
        from .judge_plots import Judge_DrawOriginal
        return Judge_DrawOriginal(root, task['selection'])
    raise ValueError('UNKNOWN_JUDGE_TASK: '+kind)
