"""Four explicit judge groups, process DAG and a table-only default.

Children own their numerical directories/receipts. Only the parent publishes
combined indexes, statuses and timings. No worker uses the old compute router.
"""
import argparse
from datetime import datetime, timezone
from enum import IntEnum
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
from contextlib import redirect_stdout, redirect_stderr

from .runtime import Runtime_GetCode, Runtime_GetData, Runtime_BuildRecomputeCommand
from .storage import Storage_WriteJson
from .judge_progress import ProgressSession, ProgressConsole, ProgressRunResult, Progress_ReadJson, ProgressLogStream

TASKS = {'q1': 'Q1', 'q23': 'Q2 / Q3（共享轨迹）', 'q4': 'Q4',
    'one-dimensional': '正式一维时间 / 空间 / remesh', 'aux-2d': '二维辅助验收',
    'mass-balance': '水质量守恒（四模式 × 三个 case）', 'consistency': '结果一致性检查',
    'static': '原题静态图', 'gif': '原题 GIF / 动画（耗时较长）',
    'extensions': '全部拓展：热模式、几何交叉、环境、动力学、前沿、diffusion clock'}
TASKS.update({'thermal-gif':'热模式动画 GIF','developer-audit':'Developer Full Audit（历史诊断）','force-reference':'强制重算所有参考'})
PAPER_TASKS=['q1','q23','q4','one-dimensional','aux-2d','mass-balance','consistency','static','extensions']


class JudgeRunResult(IntEnum):
    COMPLETE = 0
    FAILED = 1
    STOPPED = 2


def Judge_ReadJson(path, default=None):
    path = Path(path)
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else ({} if default is None else default)


def Judge_GetTime():
    return datetime.now(timezone.utc).isoformat()


def Judge_GetPlan(root, selected, workers='auto'):
    """Read-only symbolic DAG; identities are checked again by each numerical owner."""
    from .judge_tasks import Task_GetExtendedPlan
    from .judge_schedule import Schedule_GetSlots,Schedule_Deduplicate,Schedule_GetDemand
    workers=Schedule_GetSlots(workers)
    requested = set(selected)
    jobs = []
    needs_all = bool(requested & {'one-dimensional', 'aux-2d', 'mass-balance', 'consistency', 'extensions'})
    originals = ['q23', 'q4', 'q1'] if needs_all else [q for q in ['q23', 'q4', 'q1'] if q in requested]
    for case in originals:
        jobs.append(dict(key='A.'+case, group='original', kind='original', case=case, dependencies=[], pde=True, private=case))
    jobs += Task_GetExtendedPlan(requested, originals)
    logical_count=len(jobs)
    jobs,aliases=Schedule_Deduplicate(jobs)
    runtime = Path(root)/'work/recompute/runtime'
    receipts = runtime/'work/recompute/receipts'
    for job in jobs:
        case_label={'q1':'Q1','q23':'Q2/Q3','q4':'Q4'}.get(job.get('case'),'')
        job['label']={'original':case_label,'validation_1d':'正式时空加密 '+case_label,
            'validation_2d':'二维辅助 '+case_label,'mass_measure':'水质量审计 '+str(job.get('mode',''))+' '+case_label,
            'plot':'原题 GIF' if job.get('selection')=='gif' else '原题静态图'}.get(job['kind'],job['key'])
        previous = Judge_ReadJson(receipts/(job['key']+'.json'))
        job['cache_state'] = 'RECHECK_MATCHING_CACHE' if previous.get('status') == 'PASS' else 'COMPUTE_REQUIRED'
        job['expected_cache_hit'] = previous.get('status') == 'PASS'
        job['slots']=Schedule_GetDemand(job,workers)
        job['force_reference']='force-reference' in requested and (job['kind'] in ['reference_1d','validation_1d','validation_2d'] or job.get('experiment_kind') in ['full_reference','time_half'])
    implicit = [TASKS[q] for q in originals if q not in requested]
    if 'mass-balance' in requested:
        implicit.append('守恒所需 M10/M01/M11 production（完整轨迹，不生成拓展图）')
    if 'extensions' in requested:
        implicit.append('拓展专用完整 72 h M00 baseline、二维及 matched 数据；不复用早停轨迹为 72 h 结果')
    return dict(selected=list(selected), automatic_dependencies=implicit, steps=jobs,
        mode='DRY_RUN', pde_solves=0, requires_pde=any(j['pde'] and not j['expected_cache_hit'] for j in jobs),
        worker_count=workers, parallel_groups={g:[j['key'] for j in jobs if j['group']==g]
            for g in ['original', 'validation', 'plot', 'extension']},
        cache_note='Preview receipt only; execution rechecks fingerprint and source seals. A stale receipt never suppresses a task.',
        output='results/ (runtime data: work/recompute/runtime/)',logical_tasks=logical_count,
        unique_pde_experiments=sum(j['pde'] for j in jobs),deduplicated_experiments=len(aliases),experiment_aliases=aliases,
        mass_scope='12 trajectories retained: current paper facts explicitly cite 12/12; each audit follows its production')


def Judge_CopyResources(code, data, target):
    ignore = shutil.ignore_patterns('__pycache__', '*.pyc', '.pytest_cache', '~$*')
    for name in ['src', 'configs', 'scripts']:
        shutil.copytree(Path(code)/name, target/name, dirs_exist_ok=True, ignore=ignore)
    for source in Path(code).glob('*.py'):
        shutil.copy2(source, target/source.name)
    shutil.copytree(data, target/'data', dirs_exist_ok=True, ignore=ignore)


def Judge_PrepareWorkspace(root, progress=None):
    os.environ['NUMBA_CACHE_DIR'] = str(Path(root)/'work/recompute/numba_cache')
    from .frozen_mesh import Frozen_PrepareCase
    from .inputs import Input_Prepare
    root = Path(root)
    runtime = root/'work/recompute/runtime'
    from contextlib import nullcontext
    with progress.Progress_Phase('prepare.workspace') if progress else nullcontext():
        runtime.mkdir(parents=True, exist_ok=True)
        Judge_CopyResources(Runtime_GetCode(root), Runtime_GetData(root), runtime)
    # All parsers and static resource verification belong to the parent.
    with progress.Progress_Phase('prepare.inputs') if progress else nullcontext():
        Input_Prepare(runtime, runtime/'data/raw')
    os.environ['DRYING_JUDGE_FROZEN_MESH'] = '1'
    with progress.Progress_Phase('prepare.mesh') if progress else nullcontext():
        for case in ['q1', 'q23', 'q4']:
            Frozen_PrepareCase(runtime, case)
    os.environ['NUMBA_CACHE_DIR'] = str(root/'work/recompute/numba_cache')
    os.environ['DRYING_MODEL_ROOT'] = str(runtime)
    return runtime


def Judge_PreparePrivate(runtime, name):
    destination = runtime.parent/'workers'/name
    destination.mkdir(parents=True, exist_ok=True)
    Judge_CopyResources(runtime, runtime/'data', destination)
    shutil.copytree(runtime/'work/validation/mesh_profiles', destination/'work/validation/mesh_profiles', dirs_exist_ok=True)
    if name.startswith(('ref_','two_','dev_')):
        case=name.split('_',1)[1];source=Judge_ReadJson(runtime/'work/recompute/production.json')[case]
        Storage_WriteJson(destination/'work/recompute/production.json',{case:source})
        for row in [source,*source.get('stages',[])]:
            shutil.copytree(runtime/'work/cache'/row['case_id'],destination/'work/cache'/row['case_id'],dirs_exist_ok=True)
    return destination


def Judge_WarmKernels(root, modes=('M00',)):
    import numpy as np
    from .cases import Case_LoadInputs, Case_LoadConfig
    from .rk4 import Rk4_Advance
    from .studies.trajectory import Trajectory_GetAdvance, Trajectory_GetSpec
    config = Case_LoadConfig(root); inputs = Case_LoadInputs(root); n = config['numerics']
    state = np.empty((2, 2, 1)); state[0] = 301.15; state[1] = 2.55
    mesh = (np.array([0., .5, 1.]), np.array([0., 1.]))
    if 'M00' in modes:
        arguments = (state, 0., 0., .25, 3, *inputs, False, False, n['safety'], n['min_dt_s'],
            n['max_rejections'], 10000, min(301.15, inputs[0][:, 1].min()), max(301.15, inputs[0][:, 1].max()), np.empty(0))
        Rk4_Advance(*arguments, xi_faces=mesh[0], eta_faces=mesh[1])
        Rk4_Advance(*arguments, 25., 8e-7, .15, *mesh)
    for mode in modes:
        if mode != 'M00':
            # Thermal dry-basis constants depend on material model/case. Warm
            # each distinct unchanged closure once, before heavy case jobs.
            for case in ['q1','q23','q4']:
                spec = Trajectory_GetSpec(root, case, mode)
                Trajectory_GetAdvance(root, spec, mesh)(state, 0., 0.)
    print('JIT_WARMUP_COMPLETE '+','.join(modes)+'; unchanged state, PDE output=0', flush=True)


def Judge_RunWorker(task_file):
    from .diagnostics import Diagnostics_Open
    from .judge_tasks import Task_Execute
    from .runtime import Runtime_GetRoot
    launch_root=Runtime_GetRoot()
    task = Judge_ReadJson(launch_root/task_file)
    root = (launch_root/task['workspace']).resolve()
    for name in ['workspace','runtime','receipt']:
        path=(launch_root/task[name]).resolve()
        if not path.is_relative_to(launch_root):raise ValueError('WORKER_PATH_OUTSIDE_RELEASE: '+name)
        task[name]=str(path)
    os.environ['DRYING_MODEL_ROOT'] = str(root)
    os.environ['DRYING_JUDGE_FROZEN_MESH'] = '1'
    from .judge_jit import Judge_InstallRuntimeBindings
    Judge_InstallRuntimeBindings()
    Diagnostics_Open(root)
    started = Judge_GetTime(); clock = time.perf_counter()
    try:
        from .judge_observer import Progress_ObserveTask
        with Progress_ObserveTask(root, task) as observer:
            result = Task_Execute(root, task)
        receipt = dict(key=task['key'], group=task['group'], status='PASS', result=result,
            started_at=started, finished_at=Judge_GetTime(), wall_s=time.perf_counter()-clock,
            cache_reused=bool(result.get('cache_reused', False)), worker_pid=os.getpid())
        receipt['progress_observer']=dict(kernel_calls=observer.kernel_calls,reporting_wall_s=observer.reporting_wall_s)
        Storage_WriteJson(task['receipt'], receipt)
        return 0
    except Exception:
        detail = traceback.format_exc()
        print(detail, flush=True)
        Storage_WriteJson(task['receipt'], dict(key=task['key'], group=task['group'], status='FAIL',
            started_at=started, finished_at=Judge_GetTime(), wall_s=time.perf_counter()-clock,
            worker_pid=os.getpid(), cache_reused=False, error=detail))
        return 1


def Judge_MergeWorker(runtime, job, workspace, receipt):
    """One writer; private caches keep their original relative paths/fingerprints."""
    if job['kind']=='developer_diagnostic':return
    if workspace != runtime:
        for name in ['work/cache', 'work/checkpoints', 'work/plot_payload',
                     'work/studies/experiments','work/studies/plot_payload','work/studies/validation']:
            if (workspace/name).exists():
                shutil.copytree(workspace/name, runtime/name, dirs_exist_ok=True)
        comparison = Judge_ReadJson(runtime/'work/comparison/summary.json')
        comparison.update(Judge_ReadJson(workspace/'work/comparison/summary.json'))
        if (workspace/'work/comparison').exists():
            shutil.copytree(workspace/'work/comparison',runtime/'work/comparison',dirs_exist_ok=True,
                ignore=shutil.ignore_patterns('summary.json'))
        if comparison:
            Storage_WriteJson(runtime/'work/comparison/summary.json',comparison)
        # Validation summary is a merge, never a concurrent whole-file replacement.
        validation = Judge_ReadJson(runtime/'work/validation/summary.json')
        incoming=Judge_ReadJson(workspace/'work/validation/summary.json')
        dimension={'validation_1d':'1d','validation_2d':'2d'}.get(job['kind'])
        if dimension:incoming={k:v for k,v in incoming.items() if k==job['case']+'_'+dimension}
        elif job['kind']=='reference_1d':incoming={}
        validation.update(incoming)
        if (workspace/'work/validation').exists():
            shutil.copytree(workspace/'work/validation', runtime/'work/validation', dirs_exist_ok=True,
                ignore=shutil.ignore_patterns('summary.json', 'summary.lock'))
        if validation:
            Storage_WriteJson(runtime/'work/validation/summary.json', validation)
        if (workspace/'results').exists():
            shutil.copytree(workspace/'results', runtime/'results', dirs_exist_ok=True,
                ignore=shutil.ignore_patterns('status.json', 'overview.md', 'validation_summary.json', 'study_index.json'))
        if job['kind'] == 'original':
            local = Judge_ReadJson(workspace/'work/diagnostics/export_manifest.json')
            combined = Judge_ReadJson(runtime/'work/diagnostics/export_manifest.json', dict(input_hash=local['input_hash'], outputs=[], official_source='1D'))
            outputs = {row['question']: row for row in combined['outputs']}
            outputs.update({row['question']: row for row in local['outputs']})
            combined['outputs'] = [outputs[q] for q in sorted(outputs)]
            Storage_WriteJson(runtime/'work/diagnostics/export_manifest.json', combined)
            production = Judge_ReadJson(runtime/'work/recompute/production.json')
            production[job['case']] = receipt['result']['production']
            Storage_WriteJson(runtime/'work/recompute/production.json', production)
            for name in ['table_reference_','table_cache_']:
                source=workspace/f"work/recompute/{name}{job['case']}.json"
                if source.exists():shutil.copy2(source,runtime/f"work/recompute/{name}{job['case']}.json")
    if job['kind'] in ['experiment','reference_1d']:
        index_path = runtime/('work/studies/technical/index.json' if receipt['result'].get('cross') else 'results/studies/study_index.json')
        index = Judge_ReadJson(index_path, dict(schema_version=1, experiments={}))
        index['experiments'][receipt['result']['experiment_id']] = receipt['result']['status']
        Storage_WriteJson(index_path, index)
    if job['kind'] == 'full_production':
        production = Judge_ReadJson(runtime/'work/recompute/full_production.json')
        production[job['case']] = receipt['result']['production']
        Storage_WriteJson(runtime/'work/recompute/full_production.json', production)


def Judge_PublishOriginal(runtime):
    from .outputs import Output_GetEndpoint
    production = Judge_ReadJson(runtime/'work/recompute/production.json')
    validation = Judge_ReadJson(runtime/'work/validation/summary.json')
    questions = {}
    for q, case in [(1, 'q1'), (2, 'q23'), (3, 'q23'), (4, 'q4')]:
        if case not in production:
            continue
        source = production[case]
        evidence = validation.get(case+'_1d', {})
        valid = evidence.get('selected_fingerprint') == source['fingerprint']
        item = dict(question=q, source_case_id=source['case_id'], source_fingerprint=source['fingerprint'],
            official_model='M00', dimension=1, execution_mode='stage_schedule', purpose='table_production',
            schedule=source['schedule'], actual_end_s=source['actual_end_s'],
            drying_time_h=source.get('drying_time_h') if q >= 3 else None,
            table_status='PASS', table_numeric_reference='PASS',
            numerical_validation=evidence['numerical_status'] if valid else 'NOT_RERUN_IN_TABLE_ONLY_MODE',
            spatial_convergence_passed=evidence.get('spatial_convergence_passed') if valid else None,
            fixed_grid_validation='legacy / diagnostic only; NOT_RERUN',
            stage_schedule_spatial_passed=evidence.get('stage_schedule_spatial_passed') if valid else None)
        end = {1:1800.,2:10800.}.get(q, source['actual_end_s'])
        item.update(one_id=source['case_id'], source_case=case, table=f'results/tables/result{q}.xlsx',
            drying_completed=bool(q>=3 and source.get('event')), drying_time=source['event']['report_s'] if q>=3 and source.get('event') else None,
            endpoint_values=Output_GetEndpoint(runtime,source['case_id'],end),
            time_convergence_passed=evidence.get('time_passed') if valid else None,
            requested_dt_max=source['dt'],actual_dt_range_s=[source['minimum_dt'],source['maximum_dt']],
            mean_accepted_dt_s=source['actual_dt_mean'],stage_dt_statistics=source['stage_dt_statistics'])
        equivalent=Judge_ReadJson(runtime/'work/recompute/full_equivalence.json').get(case)
        if equivalent and equivalent.get('status')=='PASS' and equivalent.get('table_fingerprint')==source['fingerprint']:
            item['full_horizon_equivalent_source']=equivalent['full_case_id']
            item['full_horizon_equivalence']=equivalent
        questions['q'+str(q)] = item
        Storage_WriteJson(runtime/f'results/q{q}/q{q}_summary.json', item)
    Storage_WriteJson(runtime/'results/status.json', dict(schema_version=2, questions=questions,
        validation_scope='Current production only; table reference match does not certify convergence'))
    lines = ['# 原题复算结果', '', '正式来源：M00 一维冻结阶段网格；历史 fixed-grid 为 legacy / diagnostic only。', '']
    for key, row in questions.items():
        lines.append(f"- {key.upper()}: Excel / numeric reference PASS；正式数值验证 {row['numerical_validation']}"+
            (f"；烘干 {row['drying_time_h']:.4f} h" if row['drying_time_h'] else ''))
    (runtime/'results/overview.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')


def Judge_RunDag(root, runtime, plan, progress=None):
    root = Path(root)
    pending = list(plan['steps']); running = {}; done = set(); records = []
    started = time.perf_counter(); started_at = Judge_GetTime()
    receipts = runtime/'work/recompute/receipts'; receipts.mkdir(parents=True, exist_ok=True)
    taskdir = runtime/'work/recompute/tasks'; taskdir.mkdir(parents=True, exist_ok=True)
    logdir = root/'logs'; logdir.mkdir(exist_ok=True)
    def Save_Timings():
        totals = {group:sum(r['wall_s'] for r in records if r['group']==group) for group in ['original','validation','plot','extension']}
        group_wall = {}
        for group in totals:
            spans=sorted((datetime.fromisoformat(r['started_at']).timestamp(),datetime.fromisoformat(r['finished_at']).timestamp())
                for r in records if r['group']==group and 'started_at' in r)
            merged=[]
            for left,right in spans:
                if merged and left<=merged[-1][1]:merged[-1][1]=max(merged[-1][1],right)
                else:merged.append([left,right])
            group_wall[group]=sum(right-left for left,right in merged)
        result = dict(started_at=started_at, finished_at=Judge_GetTime(), wall_s=time.perf_counter()-started,
            workers=plan['worker_count'], tasks=records, group_worker_wall_s=totals,
            group_wall_s=group_wall,
            note='Group worker seconds may overlap; total wall is elapsed real time.')
        Storage_WriteJson(root/'work/recompute/timings.json', result)
        Storage_WriteJson(runtime/'results/recompute_timing_summary.json', result)
        return result
    try:
        while pending or running:
            ready_exclusive=next((j for j in pending if j.get('exclusive') and set(j['dependencies'])<=done),None)
            dispatch=sorted(pending,key=lambda j:(j is not ready_exclusive,j['kind']!='mass_measure'))
            for job in dispatch:
                # Drain current workers for a ready short barrier; otherwise a
                # stream of expensive jobs can starve baseline/JIT publication.
                if ready_exclusive is not None and job is not ready_exclusive:continue
                from .judge_schedule import Schedule_CanStart
                if not Schedule_CanStart(job,[r['job'] for r in running.values()],plan['worker_count']):continue
                if not set(job['dependencies']) <= done:
                    continue
                if job.get('exclusive') and running:
                    continue
                if any(entry['job'].get('exclusive') for entry in running.values()):
                    break
                private=job.get('private')
                if private and job.get('force_reference'):private='ref_'+job['case']+'_force_'+str(time.time_ns())
                workspace = Judge_PreparePrivate(runtime, private) if private else runtime
                # The case private workspace already contains its A trajectory.
                task = dict(job, workspace=workspace.relative_to(root).as_posix(), runtime=runtime.relative_to(root).as_posix(),
                    receipt=(receipts/(job['key']+'.json')).relative_to(root).as_posix())
                path = taskdir/(job['key']+'.json'); Storage_WriteJson(path, task)
                command = Runtime_BuildRecomputeCommand(['--worker-json', path.relative_to(root).as_posix()], root)
                log = (logdir/(job['key']+'.log')).open('w', encoding='utf-8')
                process = subprocess.Popen(command, cwd=root, env=dict(os.environ, DRYING_MODEL_ROOT=str(root), PYTHONUNBUFFERED='1', PYTHONIOENCODING='utf-8'),
                    stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                running[process.pid] = dict(process=process, job=job, workspace=workspace, log=log, log_path=logdir/(job['key']+'.log'), position=0,buffer='')
                pending.remove(job)
                if progress:
                    progress.tracker.Progress_Start(job['key']);progress.Progress_Emit()
            for pid, entry in list(running.items()):
                # Tail without a pipe reader deadlock; concurrent workers have separate logs.
                with entry['log_path'].open(encoding='utf-8', errors='replace') as stream:
                    stream.seek(entry['position']); text = stream.read(); entry['position'] = stream.tell()
                if text:
                    entry['buffer']+=text
                    while '\n' in entry['buffer']:
                        line,entry['buffer']=entry['buffer'].split('\n',1)
                        if progress:progress.Progress_WorkerLine(entry['job']['key'],line)
                        else:print(line,flush=True)
                code = entry['process'].poll()
                if code is None:
                    continue
                entry['log'].close()
                job = entry['job']; receipt = Judge_ReadJson(receipts/(job['key']+'.json'))
                records.append(receipt or dict(key=job['key'], group=job['group'], status='FAIL', wall_s=0., error='worker terminated without receipt'))
                del running[pid]
                if code or receipt.get('status') != 'PASS':
                    raise RuntimeError('TASK_FAILED: '+job['key']+'；见 logs/'+job['key']+'.log')
                Judge_MergeWorker(runtime, job, entry['workspace'], receipt)
                done.add(job['key'])
                if job['group'] in ['original', 'validation']:
                    Judge_PublishOriginal(runtime)
                Save_Timings()
                if (runtime/'results').exists():
                    shutil.copytree(runtime/'results', root/'results', dirs_exist_ok=True)
                if progress:
                    progress.tracker.Progress_FinishTask(job['key'],receipt.get('cache_reused',False));progress.Progress_Emit()
            if pending and not running and not any(set(j['dependencies']) <= done for j in pending):
                raise RuntimeError('TASK_DAG_UNRESOLVED: '+str([j['key'] for j in pending]))
            if running:
                time.sleep(.25)
        return Save_Timings()
    finally:
        # Children are owned by this invocation only; never scan/kill another release.
        import psutil
        for entry in running.values():
            try:
                process = psutil.Process(entry['process'].pid)
                for child in process.children(recursive=True):
                    child.kill()
                process.kill()
                entry['process'].wait(timeout=5)
            except (psutil.NoSuchProcess, subprocess.TimeoutExpired):
                pass
            entry['log'].close()
        Save_Timings()


def Judge_Main(root, argv=None):
    parser = argparse.ArgumentParser(description='默认只复算原题四张 Excel；--all 才执行四组任务。')
    parser.add_argument('--original', nargs='*', choices=['q1','q23','q4'])
    parser.add_argument('--validation', action='store_true')
    parser.add_argument('--plots', action='store_true', help='原题静态图；--gifs 显式加入动画')
    parser.add_argument('--gifs', action='store_true')
    parser.add_argument('--extensions', action='store_true')
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--workers', choices=['auto','1','2','3'], default='auto')
    parser.add_argument('--paper-all',action='store_true')
    parser.add_argument('--developer-full-audit',action='store_true')
    parser.add_argument('--explain-schedule',action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--verify', action='store_true', help='仅检查发布资源，不启动 PDE')
    parser.add_argument('--runtime-check', action='store_true')
    parser.add_argument('--tasks', nargs='+', choices=TASKS, help=argparse.SUPPRESS)
    parser.add_argument('--gui-run', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--machine-progress', action='store_true', help='输出统一 JSON 进度协议')
    parser.add_argument('--verbose', action='store_true', help='显示详细 worker 日志')
    parser.add_argument('--worker-json', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    root = Path(root).resolve()
    if args.worker_json:
        return Judge_RunWorker(args.worker_json)
    if args.runtime_check:
        from .recompute import Recompute_RuntimeCheck
        return Recompute_RuntimeCheck()
    if args.verify:
        from .publication import Publication_Check
        print(json.dumps(Publication_Check(root), ensure_ascii=False), flush=True)
        return 0
    selected = list(args.tasks or [])
    if args.original is not None:
        selected += args.original or ['q1','q23','q4']
    if args.validation:
        selected += ['one-dimensional','aux-2d','mass-balance','consistency']
    if args.plots: selected.append('static')
    if args.gifs: selected.append('gif')
    if args.extensions: selected.append('extensions')
    if args.all or args.paper_all:selected=list(PAPER_TASKS)
    if args.developer_full_audit:selected=list(TASKS)
    if not selected: selected = ['q1','q23','q4']
    plan = Judge_GetPlan(root, selected, args.workers)
    if args.explain_schedule:
        from .judge_progress import Progress_ReadReference,Progress_GetCosts
        from .judge_schedule import Schedule_Estimate
        costs=Progress_GetCosts(root,plan,Progress_ReadReference(root))
        remaining={k:None if r.get('confidence')=='unknown' else r['weight'] for k,r in costs.items()}
        wall,path=Schedule_Estimate(plan['steps'],remaining,plan['worker_count'])
        plan['explanation']=dict(critical_path=path,parallel_branches=plan['parallel_groups'],resource_slots=plan['worker_count'],
            top_10_expensive=sorted([dict(task=k,**v) for k,v in costs.items()],key=lambda r:r['weight'],reverse=True)[:10],
            estimated_wall_s=wall,eta_confidence='unknown' if wall is None else 'rough' if any(v['confidence']=='rough' for v in costs.values()) else 'calibrated',
            scope='Scheduler units; 2D validation bundles contain the documented directional/window subsolves; estimate is not an end-to-end benchmark')
    if args.dry_run or args.explain_schedule:
        print(json.dumps(plan, ensure_ascii=False, indent=2), flush=True)
        return 0
    if 'release_v2' in root.parts:raise RuntimeError('RELEASE_V2_PROTECTED: V3 cannot run or write inside V2')
    folder = root/'work/recompute'; folder.mkdir(parents=True, exist_ok=True)
    lock = folder/'runner.lock'
    import psutil
    if lock.exists():
        previous = int(lock.read_text())
        if psutil.pid_exists(previous):
            raise RuntimeError('本目录已有复算任务，PID '+str(previous))
        lock.unlink()
    descriptor = os.open(lock, os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    os.write(descriptor, str(os.getpid()).encode()); os.close(descriptor)
    Storage_WriteJson(folder/'runner_identity.json', dict(pid=os.getpid(), created_at=psutil.Process().create_time(),
        root=str(root),cmdline=psutil.Process().cmdline()))
    console=ProgressConsole(machine=args.gui_run or args.machine_progress,verbose=args.verbose)
    if not console.machine:
        print('2026 A题药材烘干模型 · 原题表格复算\n任务：'+ '、'.join(TASKS[k] for k in selected)+
            f"\n并行：{plan['worker_count']} resource slots\n输出：results/",flush=True)
        if plan['automatic_dependencies']:print('必要依赖：'+'；'.join(plan['automatic_dependencies']),flush=True)
    progress=ProgressSession(root,plan,console);progress.Progress_Begin()
    started = time.perf_counter()
    try:
        # Verbose numerical output remains in durable logs; heartbeat writes to
        # its captured real console stream, unaffected by this redirect.
        with (root/'logs/router.log').open('w',encoding='utf-8') as detail, redirect_stdout(ProgressLogStream(detail,progress)), redirect_stderr(ProgressLogStream(detail,progress)):
            runtime = Judge_PrepareWorkspace(root,progress)
            with progress.Progress_Phase('prepare.jit'):
                if any(j['pde'] for j in plan['steps']):Judge_WarmKernels(runtime)
            preparation_s = time.perf_counter()-started
            result = Judge_RunDag(root, runtime, plan,progress)
        result.update(preparation_and_jit_s=preparation_s, total_wall_s=time.perf_counter()-started,progress_scope_version=3)
        result['progress_identity']=progress.reference.get('identity')
        Storage_WriteJson(folder/'timings.json', result)
        Storage_WriteJson(root/'results/recompute_timing_summary.json', result)
        # Publish success only after all required outputs have been saved.
        audit=progress.Progress_End(ProgressRunResult.COMPLETE);result['progress']=audit
        try:
            Storage_WriteJson(folder/'timings.json',result)
            Storage_WriteJson(root/'results/recompute_timing_summary.json',result)
        except OSError as error:console.Progress_Log('WARNING: 无法保存附加进度统计：'+str(error),force=True)
        if not console.machine:
            production=Judge_ReadJson(runtime/'work/recompute/production.json')
            for case,label in [('q23','Q3'),('q4','Q4')]:
                if case in production:
                    value=production[case]['drying_time_h']
                    print(f"{label} = {value:.4f} h" if value is not None else label+'：观察期内未达标',flush=True)
            print('所选任务完成；总耗时 %.2f min；输出 results/' % (result['total_wall_s']/60), flush=True)
        return JudgeRunResult.COMPLETE
    except (Exception,KeyboardInterrupt) as error:
        result=ProgressRunResult.STOPPED if isinstance(error,KeyboardInterrupt) else ProgressRunResult.FAILED
        audit=progress.Progress_End(result)
        Storage_WriteJson(folder/'progress_failure.json',audit)
        console.Progress_Log(traceback.format_exc(),force=True)
        return JudgeRunResult.STOPPED if result==ProgressRunResult.STOPPED else JudgeRunResult.FAILED
    finally:
        lock.unlink(missing_ok=True)
        (folder/'runner_identity.json').unlink(missing_ok=True)
