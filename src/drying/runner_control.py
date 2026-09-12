"""Stop only this application's verified runner tree; no numerical operations."""
from enum import IntEnum
import json
import os
from pathlib import Path
import time
import psutil
from .storage import Storage_WriteJson


class RunnerStopResult(IntEnum):
    STOPPED=0
    NO_TASK=1
    FAILED=2


def Runner_GetProcess(root):
    root=Path(root).resolve();folder=root/'work/recompute'
    try:
        process=psutil.Process(int((folder/'runner.lock').read_text()))
        if process.pid==os.getpid():return None
        identity=folder/'runner_identity.json'
        if identity.exists():
            record=json.loads(identity.read_text(encoding='utf-8'))
            if record['pid']!=process.pid or abs(record['created_at']-process.create_time())>.01:return None
        # Verify the command as well as the PID: never target an unrelated process
        # that inherited a recycled PID / stale or copied lock file.
        expected={root/'药材烘干模型_完整离线复算.exe',root/'药材烘干模型_完整离线复算.py',
                  root/'code/offline_recompute.py',root/'offline_recompute.py',
                  root/'dependencies/application/code/offline_recompute.py'}
        cwd=Path(process.cwd())
        if not any((Path(arg) if Path(arg).is_absolute() else cwd/arg).resolve() in expected
                   for arg in process.cmdline() if not arg.startswith('-')):return None
        return process if process.is_running() else None
    except (OSError,ValueError,KeyError,psutil.Error):return None


def Runner_Stop(root,owned_pid=0):
    root=Path(root).resolve()
    try:
        parent=psutil.Process(owned_pid) if owned_pid else Runner_GetProcess(root)
        if parent is None:return RunnerStopResult.NO_TASK
        if parent.pid==os.getpid() or (owned_pid and parent.ppid()!=os.getpid()):return RunnerStopResult.FAILED
    except psutil.NoSuchProcess:return RunnerStopResult.NO_TASK
    folder=root/'work/recompute';folder.mkdir(parents=True,exist_ok=True)
    Storage_WriteJson(folder/'interrupted.json',dict(status='INTERRUPTED',reason='immediate stop / GUI close',
        pid=parent.pid,created_at=parent.create_time(),time=time.time(),
        recovery='Reuse only checkpoints and caches accepted by the original validators; incomplete output may need regeneration.'))
    targets=[parent]
    try:
        parent.suspend()  # Prevent the router starting a new stage during termination.
        for child in parent.children(recursive=True):
            targets.append(child)
            try:child.suspend()
            except psutil.NoSuchProcess:pass
        targets=[parent,*parent.children(recursive=True)]
        for process in reversed(targets):
            try:process.kill()
            except psutil.NoSuchProcess:pass
        _,alive=psutil.wait_procs(targets,timeout=3)
        if alive:return RunnerStopResult.FAILED
    except psutil.NoSuchProcess:pass
    except psutil.Error:return RunnerStopResult.FAILED
    finally:
        for process in targets:
            try:
                if process.is_running():process.resume()
            except psutil.Error:pass
    lock=folder/'runner.lock'
    try:
        if lock.exists() and int(lock.read_text())==parent.pid:
            lock.unlink();(folder/'runner_identity.json').unlink(missing_ok=True)
    except (OSError,ValueError):pass
    return RunnerStopResult.STOPPED
