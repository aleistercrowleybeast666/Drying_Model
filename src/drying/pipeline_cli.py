"""Independent V5 A/B data, C render, D validation command line."""
import argparse
from contextlib import redirect_stdout,redirect_stderr
import json
import os
from pathlib import Path
import time
import traceback
from .pipeline_plan import Catalog_Read,Catalog_GetPresets,PipelinePlan_Build,Pipeline_CheckPrerequisites
from .storage import Storage_WriteJson


def Pipeline_ParseSelection(root,argv):
    catalog=Catalog_Read(root);presets=Catalog_GetPresets(root)
    parser=argparse.ArgumentParser(description='A/B 生成数据，C 只绘图，D 只验证。默认仅正式四表。')
    parser.add_argument('--official','--original',nargs='*',choices=['q1','q23','q4'])
    parser.add_argument('--innovation',nargs='*')
    parser.add_argument('--plot',nargs='+');parser.add_argument('--validate',nargs='+')
    for flag in ['plots','validation','all','paper-all','developer-full-audit','force-data','force-validation',
                 'dry-run','explain-schedule','gui-run','machine-progress','verbose','extensions','gifs','force-reference','import-legacy']:
        parser.add_argument('--'+flag,action='store_true')
    parser.add_argument('--tasks',nargs='+',choices=list(catalog))
    parser.add_argument('--workers',choices=['auto','1','2','3','4','5','6'],default='auto')
    args=parser.parse_args(argv);selected=list(args.tasks or [])
    if args.official is not None:selected+=args.official or presets['official']
    for values,mode,prefix in [(args.innovation,'B','innovation.'),(args.plot,'C','plot.'),(args.validate,'D','validation.')]:
        if values is None:continue
        if not values:selected += [k for k,v in catalog.items() if v['mode']==mode]
        for name in values:
            matches=[k for k,v in catalog.items() if v['mode']==mode and
                     (k==name or k==prefix+name or k.startswith(prefix+name+'.') or v['group']==name)]
            if not matches:parser.error('未知逐项任务：'+name)
            selected+=matches
    if args.extensions:selected += [k for k,v in catalog.items() if v['mode']=='B']
    if args.plots:selected += [k for k,v in catalog.items() if v['mode']=='C']
    if args.gifs:selected += [k for k,v in catalog.items() if v['mode']=='C' and v['animation']]
    if args.validation or args.developer_full_audit:selected+=presets['validation']
    if args.paper_all:selected+=presets['paper']
    if args.all:selected+=presets['all']
    if not selected:selected=presets['official']
    return args,list(dict.fromkeys(selected))


def Pipeline_Main(root,argv=None):
    from .judge_pipeline import JudgeRunResult,Judge_PrepareWorkspace,Judge_RunDag,Judge_WarmKernels
    from .judge_progress import ProgressSession,ProgressConsole,ProgressRunResult,ProgressLogStream
    from .dataset_layer import Innovation_PrepareBaseline
    from .dataset_migration import LegacyArtifact_Import
    root=Path(root).resolve();args,selected=Pipeline_ParseSelection(root,argv)
    plan=PipelinePlan_Build(root,selected,args.workers,args.force_data,args.force_validation or args.force_reference)
    if args.dry_run or args.explain_schedule:
        print(json.dumps(plan,ensure_ascii=False,indent=2),flush=True);return JudgeRunResult.COMPLETE
    if any(p in root.parts for p in ['release_v2','release_v4']):raise RuntimeError('OLD_RELEASE_PROTECTED')
    # Preflight fails before creating a runtime or warming a kernel.
    if args.import_legacy:LegacyArtifact_Import(root)
    plan=PipelinePlan_Build(root,selected,args.workers,args.force_data,args.force_validation or args.force_reference)
    Pipeline_CheckPrerequisites(plan)
    import psutil
    folder=root/'work/recompute';folder.mkdir(parents=True,exist_ok=True);lock=folder/'runner.lock'
    if lock.exists():
        previous=int(lock.read_text())
        if psutil.pid_exists(previous):raise RuntimeError('本目录已有复算任务，PID '+str(previous))
        lock.unlink()
    descriptor=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.write(descriptor,str(os.getpid()).encode());os.close(descriptor)
    Storage_WriteJson(folder/'runner_identity.json',dict(pid=os.getpid(),created_at=psutil.Process().create_time(),root=str(root),cmdline=psutil.Process().cmdline()))
    console=ProgressConsole(machine=args.gui_run or args.machine_progress,verbose=args.verbose)
    progress=ProgressSession(root,plan,console);progress.Progress_Begin();started=time.perf_counter()
    try:
        (root/'logs').mkdir(parents=True,exist_ok=True)
        with (root/'logs/router.log').open('w',encoding='utf-8') as detail,redirect_stdout(ProgressLogStream(detail,progress)),redirect_stderr(ProgressLogStream(detail,progress)):
            runtime=Judge_PrepareWorkspace(root,progress);Innovation_PrepareBaseline(runtime)
            with progress.Progress_Phase('prepare.jit'):
                if any(j['pde'] and not j['expected_cache_hit'] for j in plan['steps']):Judge_WarmKernels(runtime)
            preparation=time.perf_counter()-started
            result=Judge_RunDag(root,runtime,plan,progress)
        result.update(preparation_and_jit_s=preparation,total_wall_s=time.perf_counter()-started,progress_scope_version=5)
        Storage_WriteJson(folder/'timings.json',result);Storage_WriteJson(root/'results/recompute_timing_summary.json',result)
        progress.Progress_End(ProgressRunResult.COMPLETE)
        return JudgeRunResult.COMPLETE
    except (Exception,KeyboardInterrupt) as error:
        stopped=isinstance(error,KeyboardInterrupt);progress.Progress_End(ProgressRunResult.STOPPED if stopped else ProgressRunResult.FAILED)
        console.Progress_Log(traceback.format_exc(),force=True)
        return JudgeRunResult.STOPPED if stopped else JudgeRunResult.FAILED
    finally:
        lock.unlink(missing_ok=True);(folder/'runner_identity.json').unlink(missing_ok=True)
