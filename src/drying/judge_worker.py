"""Task-scoped execution and a same-runtime persistent stdin protocol."""
from contextlib import redirect_stdout,redirect_stderr
from enum import IntEnum
import gc
import json
import logging
import os
from pathlib import Path
import sys
import threading
import time
import traceback
import psutil
from .storage import Storage_WriteJson


class WorkerRunResult(IntEnum):
    COMPLETE=0
    FAILED=1


def Worker_GetEnvironment(root):
    env=dict(os.environ,DRYING_MODEL_ROOT=str(root),PYTHONUNBUFFERED='1',PYTHONIOENCODING='utf-8',PYTHONDONTWRITEBYTECODE='1')
    for name in ['OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS','NUMBA_NUM_THREADS']:env[name]='1'
    return env


def Worker_ExecuteFile(launch_root,task_file,startup_s=0.,persistent=False):
    from .judge_pipeline import Judge_GetTime,Judge_ReadJson
    launch_root=Path(launch_root).resolve();path=(launch_root/task_file).resolve()
    if not path.is_relative_to(launch_root):raise ValueError('TASK_PATH_OUTSIDE_RELEASE')
    task=Judge_ReadJson(path)
    for name in ['workspace','runtime','receipt','log_path','dataset_root']:
        if name not in task:continue
        target=(launch_root/task[name]).resolve()
        if not target.is_relative_to(launch_root):raise ValueError('WORKER_PATH_OUTSIDE_RELEASE: '+name)
        task[name]=str(target)
    root=Path(task['workspace']);previous_root=os.environ.get('DRYING_MODEL_ROOT')
    os.environ['DRYING_MODEL_ROOT']=str(root);os.environ['DRYING_JUDGE_FROZEN_MESH']='1'
    started=time.perf_counter();stamp=Judge_GetTime();process=psutil.Process();cpu_start=sum(process.cpu_times()[:2])
    peak=[process.memory_info().rss/2**20];stop=threading.Event()
    def Memory_Sample():
        while not stop.wait(.1):peak[0]=max(peak[0],process.memory_info().rss/2**20)
    monitor=threading.Thread(target=Memory_Sample,daemon=True);monitor.start()
    observer=None;imports=0.
    try:
        from .judge_jit import Judge_InstallRuntimeBindings
        Judge_InstallRuntimeBindings()
        from .diagnostics import Diagnostics_Open
        from .judge_tasks import Task_Execute
        from .judge_observer import Progress_ObserveTask
        Diagnostics_Open(root)
        with Progress_ObserveTask(root,task) as observer:
            imports=time.perf_counter()-started
            result=Task_Execute(root,task)
        receipt=dict(key=task['key'],group=task['group'],status='PASS',result=result,cache_reused=bool(result.get('cache_reused',False)))
        outcome=WorkerRunResult.COMPLETE
    except Exception:
        error=traceback.format_exc();print(error,flush=True)
        receipt=dict(key=task['key'],group=task['group'],status='FAIL',error=error,cache_reused=False)
        outcome=WorkerRunResult.FAILED
    finally:
        stop.set();monitor.join();peak[0]=max(peak[0],process.memory_info().rss/2**20)
        logger=logging.getLogger('drying')
        for handler in list(logger.handlers):logger.removeHandler(handler);handler.close()
        if previous_root is None:os.environ.pop('DRYING_MODEL_ROOT',None)
        else:os.environ['DRYING_MODEL_ROOT']=previous_root
    wall=time.perf_counter()-started;kernel=getattr(observer,'kernel_wall_s',0.);jit=getattr(observer,'jit_wall_s',0.)
    receipt.update(started_at=stamp,finished_at=Judge_GetTime(),wall_s=wall,startup_s=startup_s,
        import_jit_s=imports+jit,solve_s=max(0.,kernel-jit),postprocess_s=max(0.,wall-imports-kernel),
        peak_rss_mb=peak[0],cpu_time_s=sum(process.cpu_times()[:2])-cpu_start,worker_pid=os.getpid(),persistent=persistent,
        run_token=task.get('run_token'),progress_identity=task.get('progress_identity'),
        timing_note='import_jit: imports and observed zero-horizon JIT calls; solve includes any first-call compilation inside a nonzero integration block',
        progress_observer=dict(kernel_calls=getattr(observer,'kernel_calls',0),reporting_wall_s=getattr(observer,'reporting_wall_s',0)))
    gc.collect()
    Storage_WriteJson(task['receipt'],receipt)
    return outcome


def Worker_RunPersistent(launch_root):
    """Protocol has descriptors only; scientific arrays never cross task messages."""
    launch_root=Path(launch_root).resolve();runtime=None;first=True
    for line in sys.stdin:
        message=json.loads(line)
        if message.get('command')=='shutdown':return WorkerRunResult.COMPLETE
        task_file=message['task_file'];task=json.loads((launch_root/task_file).read_text(encoding='utf-8'))
        selected=(launch_root/task['runtime']).resolve()
        if task['kind'] not in ['experiment','mass_measure'] or (launch_root/task['workspace']).resolve()!=selected:
            raise ValueError('PERSISTENT_SCOPE_REJECTED')
        if runtime is not None and selected!=runtime:raise ValueError('PERSISTENT_RUNTIME_CHANGED')
        runtime=selected;log_path=(launch_root/task['log_path']).resolve()
        if not log_path.is_relative_to(launch_root):raise ValueError('LOG_PATH_OUTSIDE_RELEASE')
        with log_path.open('w',encoding='utf-8') as log,redirect_stdout(log),redirect_stderr(log):
            result=Worker_ExecuteFile(launch_root,task_file,max(0.,time.time()-message['sent_at']) if first else 0.,True)
        first=False
        if result!=WorkerRunResult.COMPLETE:return result
    return WorkerRunResult.COMPLETE
