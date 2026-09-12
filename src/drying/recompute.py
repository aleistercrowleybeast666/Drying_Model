"""Offline orchestration only; authoritative CLIs retain every numerical decision."""
import argparse
from enum import IntEnum
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import time
import traceback
from .runtime import Runtime_GetCode, Runtime_GetData, Runtime_BuildRecomputeCommand

TASKS = {'q1':'问题1', 'q23':'问题2 / 问题3（共享轨迹）', 'q4':'问题4',
    'aux-2d':'二维辅助验收', 'mass-balance':'水质量守恒', 'geometry-cross':'几何—物性交叉',
    'environment':'环境延拓敏感性', 'M10':'M10 潜热', 'M01':'M01 水分携热',
    'M11':'M11 潜热＋携热', 'verify':'快速结果一致性验证'}


class RecomputeResult(IntEnum):
    COMPLETE = 0
    FAILED = 1
    STOPPED = 2


def Recompute_Hash(path):
    with Path(path).open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()


def Recompute_GetPlan(selected):
    """Explicit dependency DAG, each authoritative operation scheduled once.

    Official-only requests do not silently compute the other questions or 2D.
    Combined figures and studies require all baseline trajectories/2D evidence.
    Geometry publication follows thermal jobs to avoid re-exporting a sealed study.
    """
    requested = set(selected); plans = []
    supplements = requested & {'mass-balance','geometry-cross','environment','M10','M01','M11'}
    requires_baseline = bool(supplements or 'aux-2d' in requested)
    official = ['q1','q23','q4'] if requires_baseline else [q for q in ['q1','q23','q4'] if q in requested]
    for case in official:
        plans.append(dict(key=case,label=TASKS[case]+' · 一维验证及 Excel（图片稍后统一生成）',script='compute.py',args=['--case',case,'--official-only']))
    if requires_baseline:
        plans += [dict(key='two-dimensional',label='二维轨迹与方向验证（组合图和研究的必要依赖）',script='compute.py',args=['--two-dimensional-only']),
            dict(key='official-plots',label='正式图片及 GIF（Q1～Q4）',script='plot.py',args=[]),
            dict(key='freeze',label='冻结本次独立复算基线',script='@freeze',args=[])]
    if supplements:
        plans.append(dict(key='study-foundation',label='M00 基础验证、几何及环境研究（共享依赖）',script='compute_studies.py',args=['--group','all','--mode','M00','--resume']))
        # The existing technical publisher builds the unified four-mode facts;
        # its prerequisite must be explicit, not discovered hours into the run.
        modes = ['M10','M01','M11'] if requested & {'mass-balance','geometry-cross'} else [m for m in ['M10','M01','M11'] if m in requested]
        for mode in modes:
            plans.append(dict(key=mode,label=TASKS[mode],script='compute_studies.py',args=['--group','thermal','--mode',mode,'--resume']))
        if len(modes)==3:
            plans.append(dict(key='study-plots',label='补充图表刷新',script='plot_studies.py',args=[]))
        else:
            for figure in ['end_effect_extent','drying_fronts','drying_kinetics','diffusion_clock_drivers',
                           'geometry_control','environment_robustness','verification_evidence']:
                plans.append(dict(key='plot-'+figure,label='已有数据范围内的补充图：'+figure,script='plot_studies.py',args=['--fig',figure]))
        if 'geometry-cross' in requested:
            plans += [dict(key='geometry-cross',label=TASKS['geometry-cross'],script='compute_studies.py',args=['--group','geometry_cross','--resume']),
                dict(key='technical-plots',label='几何交叉与动力学图刷新',script='plot_studies.py',args=['--technical-only'])]
        if 'mass-balance' in requested:
            plans.append(dict(key='mass-balance',label=TASKS['mass-balance'],script='compute_studies.py',args=['--group','mass_balance','--resume']))
    if requires_baseline:
        plans.append(dict(key='aux-2d',label='二维辅助判据与汇总同步',script='validate_auxiliary_2d.py',args=[]))
        plans.append(dict(key='recomputed-check',label='本次复算结果一致性检查',script='scripts/check_results.py',args=[]))
    if 'verify' in requested:
        plans.append(dict(key='verify',label='交付结果与事实文件校验（不依赖开发缓存）',script='scripts/check_results.py',args=['--publication-only'],published=True))
    return plans


def Recompute_PrepareWorkspace(root):
    """Materialize original root layout privately; never modify frozen publications.

    This also preserves __file__ source hashes and Numba cache locators: runtime
    imports the reviewable physical source, not a renamed frozen numerical module.
    """
    root = Path(root); code = Runtime_GetCode(root); work = root/'work/recompute'
    work.mkdir(parents=True,exist_ok=True)
    if not (root/'results').exists():
        (work/'output_destination.json').write_text(json.dumps(
            dict(restore_missing_results=True,destination='results'),ensure_ascii=False),encoding='utf-8')
    ignore = shutil.ignore_patterns('__pycache__','*.pyc','.pytest_cache','.git','.venv')
    for name in ['src','configs','scripts']:
        shutil.copytree(code/name,work/name,dirs_exist_ok=True,ignore=ignore)
    for source in code.glob('*.py'): shutil.copy2(source,work/source.name)
    test_receipt = code/'release_evidence/program_tests.json'
    if not test_receipt.exists(): test_receipt = root/'work/validation/program_tests.json'
    if test_receipt.exists() and not (work/'work/validation/program_tests.json').exists():
        output=work/'work/validation/program_tests.json';output.parent.mkdir(parents=True,exist_ok=True)
        saved=json.loads(test_receipt.read_text(encoding='utf-8'))
        saved['scope']='build-machine regression evidence; not run on this judge computer; numerical acceptance is recomputed independently'
        output.write_text(json.dumps(saved,ensure_ascii=False,indent=2),encoding='utf-8')
    if not (work/'data/inputs.npz').exists(): shutil.copytree(Runtime_GetData(root),work/'data',dirs_exist_ok=True,ignore=ignore)
    # Seed presentation files only; no old validation/cache identity is claimed.
    if not (work/'results').exists():
        if (root/'results').is_dir():
            shutil.copytree(root/'results',work/'results',ignore=ignore)
        else:
            (work/'results').mkdir(parents=True)
            print('未发现已有 results；从原始 data 和 code/configs 初始化复算，完成后生成 results。',flush=True)
        for name in ['study_index.json','validation_summary.json']:
            path = work/'results/studies'/name
            if path.exists(): path.unlink()
    # Also repair an interrupted preparation that created results only partially.
    (work/'results/studies').mkdir(parents=True,exist_ok=True)
    summary=work/'results/studies/validation_summary.json'
    if not summary.exists(): summary.write_text('{}',encoding='utf-8')
    return work


def Recompute_RestoreResults(root,work):
    """Publish regenerated files only when the user removed the delivered results."""
    marker=work/'output_destination.json'
    if marker.exists() and json.loads(marker.read_text(encoding='utf-8')).get('restore_missing_results'):
        shutil.copytree(work/'results',root/'results',dirs_exist_ok=True,
            ignore=shutil.ignore_patterns('~$*','*.tmp'))
        return True
    return False


def Recompute_RunInternal(work, script, arguments):
    work = Path(work).resolve()
    os.environ['DRYING_MODEL_ROOT'] = str(work)
    os.environ['NUMBA_CACHE_DIR'] = str(work/'work/numba_cache')
    sys.path.insert(0,str(work/'src')); os.chdir(work)
    # Frozen bootstrap loaded its router from code/. Numerical modules must use
    # the independently materialized workspace for legacy __file__ root lookups.
    for name in list(sys.modules):
        if name == 'drying' or name.startswith('drying.'): del sys.modules[name]
    if script == '@freeze':
        from drying.studies.baseline import Baseline_Freeze
        Baseline_Freeze(work); return 0
    if script == '@reuse-baseline':
        from drying.studies.baseline import Baseline_Check
        print('复用缓存：'+json.dumps(Baseline_Check(work),ensure_ascii=False),flush=True); return 0
    path = (work/script).resolve()
    if not path.is_relative_to(work) or not path.is_file(): raise ValueError('Invalid worker script')
    sys.argv = [str(path),*arguments]
    try: runpy.run_path(str(path),run_name='__main__')
    except SystemExit as exit_status: return int(exit_status.code or 0)
    return 0


def Recompute_RuntimeCheck():
    import numpy as np
    import scipy.linalg
    import numba, llvmlite, matplotlib, openpyxl, PIL, imageio, iapws, pypdf, psutil
    from PySide6.QtCore import qVersion
    @numba.njit(cache=False)
    def Sum_Check(a): return a.sum()
    assert Sum_Check(np.array([1.,2.])) == 3.
    assert np.allclose(scipy.linalg.solve(np.eye(2),np.ones(2)),1)
    assert iapws.IAPWS97(T=300,x=0).h > 0
    from drying.materials import Material_Evaluate
    assert np.isfinite(Material_Evaluate(1,301.15,2.55)).all()
    print(json.dumps(dict(status='PASS',frozen=bool(getattr(sys,'frozen',False)),python=sys.executable,
        qt=qVersion(),numba=numba.__version__,scipy=scipy.__version__,matplotlib_data=matplotlib.get_data_path(),
        checks=['Qt','NumPy','SciPy DLL','Numba JIT','llvmlite','Matplotlib data','openpyxl','Pillow','imageio','IAPWS','pypdf','psutil','original material callable']),ensure_ascii=False),flush=True)
    return 0


def Recompute_Main(root, argv=None):
    parser = argparse.ArgumentParser(description='无参数：完整离线复算。所有复算结果隔离到 work/recompute/results。')
    parser.add_argument('--tasks',nargs='+',choices=TASKS)
    parser.add_argument('--official',action='append',choices=['q1','q23','q4'])
    for name in ['aux-2d','mass-balance','geometry-cross','environment','verify']:
        parser.add_argument('--'+name,action='store_true')
    parser.add_argument('--thermal',action='append',choices=['M10','M01','M11'])
    parser.add_argument('--dry-run',action='store_true',help='只显示真实依赖计划，不计算、不创建工作缓存')
    parser.add_argument('--gui-run',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--runtime-check',action='store_true',help='仅核对运行库、DLL 和小型 JIT，不解 PDE')
    parser.add_argument('--internal',help=argparse.SUPPRESS)
    parser.add_argument('--workspace',help=argparse.SUPPRESS)
    parser.add_argument('worker_args',nargs=argparse.REMAINDER,help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.runtime_check: return Recompute_RuntimeCheck()
    if args.internal:
        return Recompute_RunInternal(args.workspace,args.internal,[x for x in args.worker_args if x!='--'])
    selected = (args.tasks or [])+(args.official or [])+(args.thermal or [])
    selected += [name for name in ['aux-2d','mass-balance','geometry-cross','environment','verify'] if getattr(args,name.replace('-','_'))]
    if not selected: selected = list(TASKS)
    plan = Recompute_GetPlan(selected); root = Path(root).resolve()
    if args.dry_run:
        print(json.dumps(dict(selected=selected,steps=plan,pde_solves=0,mode='DRY_RUN',output='work/recompute/results'),ensure_ascii=False,indent=2),flush=True)
        return 0
    if selected == ['verify']:
        from drying.publication import Publication_Check
        try: Publication_Check(root)
        except (OSError,ValueError,RuntimeError,AssertionError) as error:
            print('校验未通过：'+str(error).replace(str(root),'.')+'；已有结果缺失时，请先选择复算项目。',flush=True)
            return RecomputeResult.FAILED
        print('DRYING_EVENT '+json.dumps(dict(completed=1,total=1,message='交付结果校验 PASS'),ensure_ascii=False),flush=True)
        return 0
    folder = root/'work/recompute'; folder.mkdir(parents=True,exist_ok=True)
    lock = folder/'runner.lock'
    import psutil
    if lock.exists():
        pid = int(lock.read_text())
        if psutil.pid_exists(pid): raise RuntimeError('已有离线复算任务运行中，PID '+str(pid))
        lock.unlink()
    descriptor = os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    os.write(descriptor,str(os.getpid()).encode()); os.close(descriptor)
    from .storage import Storage_WriteJson
    Storage_WriteJson(folder/'runner_identity.json',dict(pid=os.getpid(),created_at=psutil.Process().create_time()))
    def Event_Send(completed,message):
        print('DRYING_EVENT '+json.dumps(dict(completed=completed,total=len(plan),message=message),ensure_ascii=False),flush=True)
    try:
        if not args.gui_run:
            for name in ['STOP','BASELINE_STOP']: (folder/'work/studies'/name).unlink(missing_ok=True)
        work = Recompute_PrepareWorkspace(root)
        if (folder/'interrupted.json').exists():
            print('检测到上次立即停止：仅复用原有验证器接受的检查点和缓存；未完成输出重新生成。',flush=True)
        Event_Send(0,'已列出必要依赖；进度按实际完成阶段单调增加，阶段内保持不变。')
        receipt_path = work/'work/router_receipts.json'
        try:receipts = json.loads(receipt_path.read_text(encoding='utf-8')) if receipt_path.exists() else {}
        except ValueError:
            receipt_path.rename(receipt_path.with_name('router_receipts.interrupted.'+str(time.time_ns())+'.json'))
            receipts={}
        for i,step in enumerate(plan):
            if any((work/'work/studies'/n).exists() for n in ['STOP','BASELINE_STOP']): return 2
            Event_Send(i,step['label'])
            if step.get('published'):
                if (work/'output_destination.json').exists():
                    # Recomputed files are certified by the preceding authority,
                    # not compared to ZIP metadata / hashes of deleted publications.
                    Event_Send(i+1,'原交付结果已删除；本次结果已由复算检查验收，旧交付哈希校验不适用。')
                else:
                    from drying.publication import Publication_Check
                    Publication_Check(root)
                continue
            # Receipts never suppress execution: each authority checks its own caches.
            print(('复用缓存（由权威入口核验，不匹配则重算）' if (work/'work/cache').exists() else '重新计算（没有复算缓存）')+'：'+step['label'],flush=True)
            reuse = (work/'work/baseline_snapshot/baseline_manifest.json').exists() and step['key'] in ['q1','q23','q4','two-dimensional','official-plots','freeze']
            command = Runtime_BuildRecomputeCommand(['--internal','@reuse-baseline' if reuse else step['script'],'--workspace',work.relative_to(root).as_posix(),'--',*step['args']],root)
            env = dict(os.environ,PYTHONUNBUFFERED='1',PYTHONIOENCODING='utf-8',DRYING_MODEL_ROOT=str(root))
            with subprocess.Popen(command,cwd=root,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                    text=True,encoding='utf-8',errors='replace',bufsize=1) as child:
                logdir = root/'logs'; logdir.mkdir(exist_ok=True)
                with (logdir/'offline_recompute.log').open('a',encoding='utf-8') as log:
                    for line in child.stdout:
                        print(line,end='',flush=True); log.write(line); log.flush()
                code = child.wait()
            if any((work/'work/studies'/n).exists() for n in ['STOP','BASELINE_STOP']): return 2
            if code:
                Event_Send(i,f"FAIL：{step['label']}，退出码 {code}"); return code
            recorded_command=[os.path.relpath(value,root) if os.path.isabs(value) and Path(value).is_relative_to(root) else value for value in command]
            receipts[step['key']] = dict(status='PASS',finished_at=time.strftime('%Y-%m-%d %H:%M:%S'),command=recorded_command)
            Storage_WriteJson(receipt_path,receipts)
            Event_Send(i+1,'完成：'+step['label'])
            if Recompute_RestoreResults(root,work): print('已生成 results/：仅包含当前已完成的复算输出。',flush=True)
        Event_Send(len(plan),'PASS：所选任务完成；输出见 work/recompute/results；原 results 缺失时已同步重建。')
        return 0
    except Exception:
        detail=traceback.format_exc().replace(str(root),'.')
        logdir=root/'logs';logdir.mkdir(exist_ok=True)
        with (logdir/'offline_recompute.log').open('a',encoding='utf-8') as stream:stream.write(detail)
        print(detail,flush=True)
        Event_Send(0,'任务失败，请查看详细日志；可修复后继续。')
        return RecomputeResult.FAILED
    finally:
        lock.unlink(missing_ok=True)
        (folder/'runner_identity.json').unlink(missing_ok=True)
