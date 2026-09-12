"""Disposable-copy EXE lifecycle integration; never run numerical trajectories."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def Smoke_Run():
    from drying.runtime import Runtime_GetRoot,Runtime_GetCode
    root=Runtime_GetRoot();script=(Runtime_GetCode(root)/'scripts/smoke_release_lifecycle.py').relative_to(root).as_posix()
    command=[sys.executable,'--internal',script,'--workspace','.','--']
    if '--leaf' in sys.argv:time.sleep(60);return 0
    if '--parent' in sys.argv:
        child=subprocess.Popen([*command,'--leaf'],cwd=root)
        (root/'leaf.pid').write_text(str(child.pid));time.sleep(60);return 0
    import psutil
    from PySide6.QtWidgets import QApplication
    from drying.gui.judge_window import JudgeWindow
    assert getattr(sys,'frozen',False)
    assert not (root/'work/recompute/runner.lock').exists(),'Only run in a disposable copy'
    app=QApplication.instance() or QApplication([])
    for external in [False,True]:
        (root/'leaf.pid').unlink(missing_ok=True)
        window=JudgeWindow(root);window.show()
        if external:
            worker=subprocess.Popen([*command,'--parent'],cwd=root)
            parent=worker.pid
            lock=root/'work/recompute/runner.lock';lock.parent.mkdir(parents=True,exist_ok=True);lock.write_text(str(parent))
            window.Task_CheckExternal();assert window.external_busy
        else:
            window.process.setWorkingDirectory(str(root));window.process.start(command[0],[*command[1:],'--parent'])
            assert window.process.waitForStarted(3000);parent=int(window.process.processId())
        deadline=time.monotonic()+15
        while not (root/'leaf.pid').exists() and time.monotonic()<deadline:app.processEvents();time.sleep(.02)
        child=int((root/'leaf.pid').read_text());window.close();app.processEvents()
        assert not window.isVisible() and not psutil.pid_exists(parent) and not psutil.pid_exists(child)
        assert not (root/'work/recompute/runner.lock').exists()
        print(json.dumps(dict(status='PASS',gui_close_killed_tree=True,external_runner=external,production_pde_solves=0)),flush=True)
    return 0


if __name__=='__main__':raise SystemExit(Smoke_Run())
