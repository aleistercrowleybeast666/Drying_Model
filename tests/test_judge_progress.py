"""Display and process ownership must not change numerical meaning."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import pytest
from drying.judge_progress import (ProgressTracker,ProgressConsole,ProgressRunResult,
    Progress_ReadReference,Progress_GetCosts,Progress_GetIdentity,Progress_Hash)

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def qt_app():
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    yield app


class Clock:
    now=0.
    def __call__(self):return self.now


def Progress_MakeTracker(preparation=()):
    clock=Clock();jobs=[dict(key=k,label=k,group='original',kind='original',dependencies=[]) for k in ['A.q1','A.q23','A.q4']]
    costs={k:dict(weight=w) for k,w in [('A.q1',10),('A.q23',190),('A.q4',55)]}
    tracker=ProgressTracker(dict(steps=jobs,worker_count=2),costs,preparation,clock)
    return tracker,clock


def test_weighted_progress_is_not_task_count():
    t,c=Progress_MakeTracker();t.Progress_FinishTask('A.q1')
    assert t.Progress_Snapshot()['structural_fraction']==pytest.approx(10/255)


def test_parallel_q23_and_q4_both_contribute():
    t,c=Progress_MakeTracker()
    for key in ['A.q23','A.q4']:t.Progress_Start(key);t.Progress_Update(key,.5)
    assert t.Progress_Snapshot()['structural_fraction']==pytest.approx((190+55)*.5/255)


def test_internal_steps_and_monotonic_stale_fallback():
    t,c=Progress_MakeTracker();t.Progress_Start('A.q23');values=[]
    for f in [.1,.25,.05,.6]:
        t.Progress_Update('A.q23',f);values.append(t.Progress_Snapshot()['structural_fraction'])
    assert values==sorted(values) and values[1]>values[0]
    assert values[2]==values[1]


@pytest.mark.parametrize('result',[ProgressRunResult.FAILED,ProgressRunResult.STOPPED])
def test_failure_or_stop_never_means_complete(result):
    t,c=Progress_MakeTracker();t.Progress_Start('A.q23');c.now=10000
    prior=t.Progress_Snapshot()['overall_fraction'];t.Progress_Terminate(result)
    assert t.Progress_Snapshot()['overall_fraction']==prior<1


def test_success_requires_all_receipts_and_exact_one():
    t,c=Progress_MakeTracker()
    with pytest.raises(ValueError):t.Progress_Terminate(ProgressRunResult.COMPLETE)
    for key in t.jobs:t.Progress_FinishTask(key,cache_reused=True)
    t.Progress_Terminate(ProgressRunResult.COMPLETE)
    assert t.Progress_Snapshot()['overall_fraction']==1


def test_preparation_and_jit_have_internal_progress():
    t,c=Progress_MakeTracker([('prepare.jit','JIT',25.)]);t.Progress_Start('prepare.jit');c.now=10
    assert 0<t.Progress_Snapshot()['overall_fraction']<1
    assert t.Progress_Snapshot()['running_tasks'][0]['task_label']=='JIT'


def test_forecasts_hold_below_receipt_and_exact_target_does_not_drift():
    t,c=Progress_MakeTracker();t.Progress_Start('A.q23');c.now=1e6
    assert t.Progress_Snapshot()['running_tasks'][0]['task_fraction']<=.95
    t.Progress_Start('A.q4');t.Progress_Update('A.q4',.3);c.now+=1e6
    assert t.jobs['A.q4']['fraction']==.3
    t.Progress_Snapshot();assert t.jobs['A.q4']['fraction']==.3


@pytest.mark.parametrize('workers',[1,2,3])
def test_eta_obeys_worker_parallelism(workers):
    t,c=Progress_MakeTracker();t.workers=workers
    eta=t.Progress_GetEta(c())
    assert eta=={1:255,2:190,3:190}[workers]


def test_cache_hit_completes_and_new_cost_does_not_trust_receipt(tmp_path):
    from drying.judge_pipeline import Judge_GetPlan
    receipt=tmp_path/'work/recompute/runtime/work/recompute/receipts/A.q23.json';receipt.parent.mkdir(parents=True)
    receipt.write_text('{"status":"PASS"}')
    plan=Judge_GetPlan(tmp_path,['q23']);cost=Progress_GetCosts(tmp_path,plan,{})
    assert plan['steps'][0]['expected_cache_hit'] and cost['A.q23']['weight']>10
    t,c=Progress_MakeTracker();t.Progress_FinishTask('A.q23',True)
    assert t.Progress_Snapshot()['cache_reused']


def test_corrupt_or_stale_reference_is_nonfatal(tmp_path,monkeypatch):
    import drying.runtime as runtime
    monkeypatch.setattr(runtime,'Runtime_GetCode',lambda root:tmp_path)
    directory=tmp_path/'configs';directory.mkdir()
    p=directory/'progress_reference.json';p.write_text('broken')
    assert Progress_ReadReference(tmp_path)=={}
    value=dict(identity={},tasks={},preparation=[]);value['seal']=Progress_Hash(value);p.write_text(json.dumps(value))
    assert Progress_ReadReference(tmp_path)=={}


def test_reference_matches_real_core_and_stage_metadata():
    value=Progress_ReadReference(ROOT);assert value
    assert value['identity']==Progress_GetIdentity(ROOT)
    for case in ['q1','q23','q4']:
        row=value['tasks']['A.'+case]
        assert sum(s['steps'] for s in row['stages'])==row['accepted_steps']
        assert row['actual_end_s']==row['stages'][-1]['t_end']
    assert value['tasks']['A.q23']['actual_end_s']<259200


def test_input_metadata_refresh_does_not_disable_stage_weights(tmp_path):
    import shutil
    identity=Progress_GetIdentity(ROOT)
    for name in identity['numerical_sources']:
        path=tmp_path/f'src/drying/{name}.py';path.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/f'src/drying/{name}.py',path)
    shutil.copytree(ROOT/'configs/frozen_mesh',tmp_path/'configs/frozen_mesh')
    for name in ['default.toml','stage_schedule.json','progress_reference.json']:
        shutil.copy2(ROOT/'configs'/name,tmp_path/'configs'/name)
    path=tmp_path/'data/input_manifest.json';path.parent.mkdir()
    manifest=json.loads((ROOT/'data/input_manifest.json').read_text(encoding='utf-8'))
    manifest['descriptive_metadata']='refreshed in private runtime'
    path.write_text(json.dumps(manifest),encoding='utf-8')
    assert Progress_GetIdentity(tmp_path)==identity and Progress_ReadReference(tmp_path)
    manifest['hash']='different numerical inputs';path.write_text(json.dumps(manifest),encoding='utf-8')
    assert Progress_ReadReference(tmp_path)=={}


class Stream(io.StringIO):
    def __init__(self,tty):super().__init__();self.tty=tty
    def isatty(self):return self.tty


@pytest.mark.parametrize('tty',[True,False])
def test_cli_refresh_and_warning_line(tty):
    t,c=Progress_MakeTracker();s=Stream(tty);console=ProgressConsole(s,clock=c)
    console.Progress_Write(t.Progress_Snapshot());c.now=2;console.Progress_Write(t.Progress_Snapshot())
    assert s.getvalue().count('[  0.0%]')==1
    console.Progress_Log('WARNING test')
    output=s.getvalue();assert ('\r' in output)==tty and '\nWARNING test\n' in output


def test_machine_progress_is_json_from_same_snapshot():
    t,c=Progress_MakeTracker();s=Stream(False);console=ProgressConsole(s,machine=True)
    value=t.Progress_Snapshot();console.Progress_Write(value)
    assert json.loads(s.getvalue().split(' ',1)[1])==value


def test_progress_kept_out_of_scientific_identity():
    # File-byte hashes are the actual scientific cache contract, not a test copy
    # of the formula. The sealed pre-change run supplies the expected identity.
    frozen=Progress_ReadReference(ROOT)['identity']['numerical_sources']
    import hashlib
    for name,digest in frozen.items():assert hashlib.sha256((ROOT/f'src/drying/{name}.py').read_bytes()).hexdigest()==digest
    for name in ['table_solver.py','cases.py','stages.py','rk4.py']:
        assert 'judge_progress' not in (ROOT/'src/drying'/name).read_text(encoding='utf-8')


def test_observer_calls_kernel_once_and_keeps_return_identity(tmp_path):
    from drying.judge_observer import Progress_ObserveTask
    import drying.table_solver as table
    original=table.Rk4_Advance
    with Progress_ObserveTask(tmp_path,dict(key='A.q1',kind='original',case='q1')):
        assert table.Rk4_Advance.__wrapped__ is original
    assert table.Rk4_Advance is original


def test_gui_point_one_percent_and_no_overshoot(qt_app,tmp_path):
    from drying.gui.judge_window import JudgeWindow
    t,c=Progress_MakeTracker();event=t.Progress_Snapshot();event.update(overall_fraction=.473,elapsed_s=47.3,eta_s=52.7)
    window=JudgeWindow(tmp_path);window.Progress_ApplyEvent(event)
    assert window.outer.maximum()==10000 and window.outer.value()==4730 and window.outer.format()=='47.3%'
    for _ in range(40):window.Progress_Animate()
    assert window.outer.value()==4730
    window.close()


def test_gui_external_close_never_kills_cli(qt_app,tmp_path):
    from drying.gui.judge_window import JudgeWindow
    import psutil
    script=tmp_path/'offline_recompute.py';script.write_text('import time;time.sleep(30)')
    process=subprocess.Popen([sys.executable,str(script)],cwd=tmp_path)
    folder=tmp_path/'work/recompute';folder.mkdir(parents=True)
    (folder/'runner.lock').write_text(str(process.pid))
    (folder/'runner_identity.json').write_text(json.dumps(dict(pid=process.pid,created_at=psutil.Process(process.pid).create_time())))
    try:
        window=JudgeWindow(tmp_path);window.show();qt_app.processEvents()
        assert window.external_run_detected and not window.owns_run
        assert window.stop.text()=='停止外部复算'
        window.close();qt_app.processEvents();assert process.poll() is None
    finally:process.terminate();process.wait(timeout=3)


def test_output_group_matches_actual_end_effect_dag():
    from drying.judge_pipeline import Judge_GetPlan
    config=json.loads((ROOT/'configs/output_groups.json').read_text(encoding='utf-8'))
    row=next(v for v in config['outputs'] if v['path'].endswith('01_end_effect_extent.png'))
    assert row['group']=='extension' and any(s.startswith('D:') for s in row['required_sources'])
    b=Judge_GetPlan(ROOT,['one-dimensional','aux-2d'])
    assert not any(j['group']=='extension' for j in b['steps'])
    d=Judge_GetPlan(ROOT,['extensions']);assert any(j['kind']=='extension_publish' for j in d['steps'])
    listed={v['path'] for v in config['outputs']}
    actual={p.relative_to(ROOT).as_posix() for p in (ROOT/'results').rglob('*')
        if p.suffix.lower() in ['.png','.gif','.xlsx'] and not p.name.startswith('~$')}
    assert len(listed)==len(config['outputs']) and listed==actual
    all_jobs={j['key']:j for j in Judge_GetPlan(ROOT,['q1','q23','q4','one-dimensional','aux-2d','mass-balance','consistency','static','gif','extensions'])['steps']}
    assert all(all_jobs[key]['group']==row['group'] for row in config['outputs'] for key in row['producer_tasks'])


def test_external_stop_requires_confirmation(qt_app,tmp_path,monkeypatch):
    from drying.gui.judge_window import JudgeWindow
    import drying.gui.judge_window as gui
    from PySide6.QtWidgets import QMessageBox
    import psutil
    process=psutil.Process()
    monkeypatch.setattr(gui,'Runner_GetProcess',lambda root:process)
    monkeypatch.setattr(gui,'Runner_Stop',lambda *a,**k:pytest.fail('unconfirmed external stop'))
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.StandardButton.No)
    window=JudgeWindow(tmp_path);window.Task_Stop();window.close()


def test_external_identity_changed_after_confirmation_is_not_stopped(qt_app,tmp_path,monkeypatch):
    from drying.gui.judge_window import JudgeWindow
    import drying.gui.judge_window as gui
    from drying.runner_control import RunnerStopResult
    from PySide6.QtWidgets import QMessageBox
    import psutil
    process=psutil.Process();calls=[]
    monkeypatch.setattr(gui,'Runner_GetProcess',lambda root:process)
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.StandardButton.Yes)
    def Stop(root,owned_pid,expected_identity):
        calls.append(expected_identity);return RunnerStopResult.NO_TASK
    monkeypatch.setattr(gui,'Runner_Stop',Stop)
    window=JudgeWindow(tmp_path);window.Task_Stop()
    assert calls[0]['pid']==process.pid and not window.stop_requested
    assert '未停止其他' in window.current.text();window.close()
