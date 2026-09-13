"""Judge routing, genuine progress and isolated runtime contracts; no long solves."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import pytest
from drying.recompute import Recompute_GetPlan, Recompute_PrepareWorkspace, TASKS
from drying.runtime import Runtime_GetRoot, Runtime_BuildRecomputeCommand


@pytest.fixture(autouse=True)
def confirm_owned_test_shutdown(monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.StandardButton.Yes)


def Progress_TestEvent(fraction,message='阶段'):
    return dict(schema_version=1,event='progress',overall_fraction=fraction,elapsed_s=12.,eta_s=12.*(1-fraction)/fraction if fraction else 0.,eta_confidence='measured',message=message,
        running_tasks=[dict(task_label=message,task_fraction=fraction)])


def test_minimal_bundle_bootstraps_without_top_level_code_data_or_results(tmp_path):
    from drying.runtime import Runtime_GetCode,Runtime_GetData
    resource=tmp_path/'dependencies/application'
    for folder in ['code/src','code/configs','code/scripts','data']:(resource/folder).mkdir(parents=True,exist_ok=True)
    (resource/'data/inputs.npz').write_bytes(b'original input')
    assert Runtime_GetCode(tmp_path)==resource/'code'
    assert Runtime_GetData(tmp_path)==resource/'data'
    work=Recompute_PrepareWorkspace(tmp_path)
    assert (work/'data/inputs.npz').read_bytes()==b'original input'
    assert all(not (tmp_path/name).exists() for name in ['code','data','results'])


def test_cold_workspace_accepts_missing_results_and_repairs_partial_setup(tmp_path):
    for folder in ['code/src','code/configs','code/scripts','data']:
        (tmp_path/folder).mkdir(parents=True,exist_ok=True)
    (tmp_path/'data/inputs.npz').write_bytes(b'input')
    work=Recompute_PrepareWorkspace(tmp_path)
    assert (work/'results/studies/validation_summary.json').read_text()=='{}'
    assert not (tmp_path/'results').exists()  # no fake result before a successful task
    (work/'results/studies/validation_summary.json').unlink()
    assert Recompute_PrepareWorkspace(tmp_path)==work
    assert (work/'results/studies/validation_summary.json').is_file()


def test_restore_only_regenerates_user_deleted_results(tmp_path):
    from drying.recompute import Recompute_RestoreResults
    work=tmp_path/'work/recompute';(work/'results').mkdir(parents=True)
    (work/'results/result.txt').write_text('recomputed')
    assert not Recompute_RestoreResults(tmp_path,work)
    assert not (tmp_path/'results').exists()
    (work/'output_destination.json').write_text('{"restore_missing_results":true}')
    assert Recompute_RestoreResults(tmp_path,work)
    assert (tmp_path/'results/result.txt').read_text()=='recomputed'


def test_moved_source_command_resolves_from_new_root_not_launch_directory(tmp_path,monkeypatch):
    moved=tmp_path/'移动后的 程序';moved.mkdir()
    (moved/'药材烘干模型_原题表格复算.py').write_text('')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('DRYING_MODEL_ROOT',str(moved))
    command=Runtime_BuildRecomputeCommand(['--official','q1'])
    assert Path(command[2]).parent==moved and command[-2:]==['--official','q1']


@pytest.fixture(scope='module')
def qt_app():
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.mark.parametrize('case',['q1','q23','q4'])
def test_selective_official_does_not_add_other_pdes(case):
    plan = Recompute_GetPlan([case])
    assert len(plan)==1 and plan[0]['args']==['--case',case,'--official-only']


def test_full_plan_has_unique_authorities_and_needed_order():
    plan = Recompute_GetPlan(list(TASKS)); keys = [p['key'] for p in plan]
    assert len(keys)==len(set(keys))
    assert keys[:3]==['q1','q23','q4']
    assert keys.index('study-plots') < keys.index('geometry-cross') < keys.index('mass-balance')
    assert keys.index('M11') < keys.index('mass-balance')
    assert keys[-2:]==['recomputed-check','verify']
    assert sum(p['args']==['--group','all','--mode','M00','--resume'] for p in plan)==1


def test_verify_has_no_numeric_or_workspace_dependency():
    assert Recompute_GetPlan(['verify'])==[dict(key='verify',label='交付结果与事实文件校验（不依赖开发缓存）',
        script='scripts/check_results.py',args=['--publication-only'],published=True)]


def test_exe_command_never_uses_external_python(monkeypatch,tmp_path):
    monkeypatch.setattr(sys,'frozen',True,raising=False)
    command = Runtime_BuildRecomputeCommand(['--official','q4'],tmp_path)
    assert command==[str(tmp_path/'药材烘干模型_原题表格复算.exe'),'--official','q4']


def test_runtime_root_honors_explicit_workspace(monkeypatch,tmp_path):
    monkeypatch.setenv('DRYING_MODEL_ROOT',str(tmp_path))
    assert Runtime_GetRoot()==tmp_path.resolve()


def test_compatibility_layout_preserves_source_and_published_data(tmp_path):
    for folder in ['code/src','code/configs','code/scripts','data','results/studies']:
        (tmp_path/folder).mkdir(parents=True,exist_ok=True)
    (tmp_path/'code/src/core.py').write_bytes(b'# untouched scientific source\r\n')
    (tmp_path/'data/inputs.npz').write_bytes(b'input')
    (tmp_path/'results/paper_facts.json').write_text('{}')
    (tmp_path/'results/studies/study_index.json').write_text('{"stale":true}')
    work = Recompute_PrepareWorkspace(tmp_path)
    assert (work/'src/core.py').read_bytes()==(tmp_path/'code/src/core.py').read_bytes()
    assert not (work/'results/studies/study_index.json').exists()
    (work/'results/paper_facts.json').write_text('{"recomputed":true}')
    assert (tmp_path/'results/paper_facts.json').read_text()=='{}'


def test_gui_single_page_selection_progress_and_stop(qt_app,tmp_path):
    from drying.gui.judge_window import JudgeWindow
    window = JudgeWindow(tmp_path)
    assert not hasattr(window,'nav') and not hasattr(window,'pages')
    assert [k for k,v in window.checks.items() if v.isChecked()]==['q1','q23','q4']
    window.select_buttons[1].click(); assert window.checks['extensions'].isChecked() and not window.checks['gif'].isChecked()
    window.select_buttons[2].click(); assert not any(v.isChecked() for v in window.checks.values())
    window.start.click(); assert '至少' in window.current.text()
    window.select_buttons[0].click(); assert sum(v.isChecked() for v in window.checks.values())==3
    assert window.logs.isHidden(); window.log_toggle.click(); assert not window.logs.isHidden()
    window.Task_Stop()
    assert not window.stop.isEnabled()
    window.close()


def test_gui_real_subprocess_dry_run_and_logs(qt_app):
    from drying.gui.judge_window import JudgeWindow
    from PySide6.QtCore import QProcess
    root = Path(__file__).resolve().parents[1]
    window = JudgeWindow(root); window.Selection_Set(['q1','extensions']); window.dry_run=True
    window.Task_Start()
    deadline=time.monotonic()+15
    while window.process.state()!=QProcess.ProcessState.NotRunning and time.monotonic()<deadline:
        qt_app.processEvents(); time.sleep(.01)
    qt_app.processEvents()
    assert window.process.exitCode()==0
    assert 'DRY_RUN' in window.logs.toPlainText() and 'shared.baseline' in window.logs.toPlainText()
    assert window.start.isEnabled()
    window.close()


def test_gui_preserves_split_utf8_progress(qt_app,tmp_path,monkeypatch):
    from drying.gui.judge_window import JudgeWindow
    from PySide6.QtCore import QByteArray
    window=JudgeWindow(tmp_path)
    payload=('DRYING_PROGRESS '+json.dumps(Progress_TestEvent(.4,'空间验证'),ensure_ascii=False)+'\n').encode()
    cut=payload.index('空'.encode())+1
    chunks=iter([payload[:cut],payload[cut:]])
    monkeypatch.setattr(window.process,'readAllStandardOutput',lambda:QByteArray(next(chunks)))
    window.Log_Read();window.Log_Read()
    assert '空间验证' in window.inner.text() and window.outer.value()==4000 and window.outer.maximum()==10000
    window.close()


def test_gui_tracks_new_credible_wall_target(qt_app,tmp_path,monkeypatch):
    from drying.gui.judge_window import JudgeWindow
    from PySide6.QtCore import QByteArray
    window=JudgeWindow(tmp_path)
    values=[]
    for completed in [2,1,4,0]:
        payload='DRYING_PROGRESS '+json.dumps(Progress_TestEvent(completed/5))+'\n'
        monkeypatch.setattr(window.process,'readAllStandardOutput',lambda:QByteArray(payload.encode()))
        window.Log_Read();values.append(window.outer.value())
    assert values==[4000,2000,8000,0] and window.outer.maximum()==10000
    monkeypatch.setattr(window.process,'readAllStandardOutput',lambda:QByteArray())
    window.Task_Done(1,None);assert window.outer.value()==0
    window.Task_Done(0,None);assert window.outer.value()==10000
    window.close()


def test_white_background_overrides_dark_system_palette(qt_app,tmp_path):
    from drying.gui.judge_window import JudgeWindow
    from PySide6.QtGui import QPalette,QColor
    saved=qt_app.palette();dark=QPalette(saved)
    dark.setColor(QPalette.ColorRole.Window,QColor('black'));dark.setColor(QPalette.ColorRole.Base,QColor('black'))
    qt_app.setPalette(dark)
    try:
        window=JudgeWindow(tmp_path);window.show();window.log_toggle.click();qt_app.processEvents()
        for widget in [window,window.controls_scroll.viewport(),window.logs.viewport(),window.splitter.widget(1)]:
            assert widget.palette().color(QPalette.ColorRole.Window).name()=='#ffffff'
            assert widget.palette().color(QPalette.ColorRole.Base).name()=='#ffffff'
        window.close()
    finally:qt_app.setPalette(saved)


def test_stop_button_enables_for_running_process_and_disables_after_request(qt_app,tmp_path):
    from drying.gui.judge_window import JudgeWindow
    window=JudgeWindow(tmp_path)
    assert not window.stop.isEnabled()
    window.process.start(sys.executable,['-c','import time;time.sleep(30)'])
    assert window.process.waitForStarted(3000)
    qt_app.processEvents();assert window.stop.isEnabled()
    window.stop.click()
    assert (tmp_path/'work/recompute/interrupted.json').is_file()
    qt_app.processEvents();assert not window.stop.isEnabled()
    window.close()


def test_reopened_gui_can_stop_existing_runner(qt_app,tmp_path):
    from drying.gui.judge_window import JudgeWindow
    script=tmp_path/'offline_recompute.py';script.write_text('import time;time.sleep(30)')
    process=subprocess.Popen([sys.executable,str(script)],cwd=tmp_path)
    lock=tmp_path/'work/recompute/runner.lock';lock.parent.mkdir(parents=True)
    lock.write_text(str(process.pid))
    import psutil
    (lock.parent/'runner_identity.json').write_text(json.dumps(dict(pid=process.pid,created_at=psutil.Process(process.pid).create_time())))
    window=JudgeWindow(tmp_path)
    assert window.external_busy and window.stop.isEnabled() and window.start.isEnabled()
    window.select_buttons[1].click();assert window.checks['extensions'].isChecked() and not window.checks['gif'].isChecked()
    window.select_buttons[2].click();assert not any(check.isChecked() for check in window.checks.values())
    window.start.click();assert window.external_busy and '已有复算' in window.current.text()
    window.stop.click();window.Task_CheckExternal()
    assert process.wait(timeout=3)!=0 and not lock.exists()
    assert window.start.isEnabled() and not window.stop.isEnabled()
    window.close()


def test_close_terminates_worker_and_descendants(qt_app,tmp_path):
    from drying.gui.judge_window import JudgeWindow
    from PySide6.QtCore import QProcess
    import psutil
    script=tmp_path/'offline_recompute.py'
    script.write_text("import subprocess,sys,time\nfrom pathlib import Path\np=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])\nPath('child.pid').write_text(str(p.pid))\ntime.sleep(30)\n")
    window=JudgeWindow(tmp_path);window.show()
    window.process.setWorkingDirectory(str(tmp_path))
    window.process.start(sys.executable,[str(script)])
    assert window.process.waitForStarted(3000)
    deadline=time.monotonic()+5
    while not (tmp_path/'child.pid').exists() and time.monotonic()<deadline:
        qt_app.processEvents();time.sleep(.01)
    child=int((tmp_path/'child.pid').read_text());parent=int(window.process.processId())
    window.close();qt_app.processEvents()
    assert not window.isVisible() and window.process.state()==QProcess.ProcessState.NotRunning
    assert not psutil.pid_exists(child) and not psutil.pid_exists(parent)


def test_stale_or_recycled_lock_never_targets_unrelated_process(tmp_path):
    from drying.runner_control import Runner_GetProcess,Runner_Stop,RunnerStopResult
    lock=tmp_path/'work/recompute/runner.lock';lock.parent.mkdir(parents=True)
    lock.write_text(str(os.getpid()))
    assert Runner_GetProcess(tmp_path) is None
    assert Runner_Stop(tmp_path)==RunnerStopResult.NO_TASK


def test_official_only_entry_stops_before_cross_question_processing(tmp_path,monkeypatch):
    import importlib.util
    import drying.cases as cases
    import drying.inputs as inputs
    import drying.mesh as mesh
    import drying.validation as validation
    import drying.export as export
    import drying.outputs as outputs
    import drying.diagnostics as diagnostics
    from drying.storage import Storage_WriteJson
    entry=Path(__file__).resolve().parents[1]/'compute.py'
    spec=importlib.util.spec_from_file_location('isolated_compute',entry);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module._ROOT=tmp_path;calls=[]
    monkeypatch.setattr(cases,'Case_LoadConfig',lambda root: {'stage_mesh':{'mode':'fixed'}})
    monkeypatch.setattr(inputs,'Input_Prepare',lambda *a:None)
    monkeypatch.setattr(mesh,'Mesh_PrepareCase',lambda root,case:calls.append(('mesh',case)))
    def Validate(root,scope,case):
        calls.append((scope,case));Storage_WriteJson(root/'work/validation/summary.json',{case+'_1d':{'time_passed':True,'spatial_passed':True}})
    monkeypatch.setattr(validation,'Validation_Run',Validate)
    monkeypatch.setattr(export,'Export_Run',lambda root,case:calls.append(('export',case)))
    monkeypatch.setattr(outputs,'Output_UpdateStatus',lambda *a:pytest.fail('unexpected global finalize'))
    monkeypatch.setattr(cases,'Case_SolvePairEvents',lambda *a:pytest.fail('unexpected other question solve'))
    monkeypatch.setattr(diagnostics,'Diagnostics_Open',lambda *a:None)
    monkeypatch.setattr(sys,'argv',['compute.py','--case','q1','--official-only'])
    assert module.Compute_Main()==0
    assert calls==[('mesh','q1'),('1d','q1'),('export','q1')]
