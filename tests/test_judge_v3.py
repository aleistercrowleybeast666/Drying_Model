"""V3 acceptance: evidence, confidence, real dependencies and immutable V2."""
import io
import json
import os
from pathlib import Path
import sys
import pytest
from drying.judge_progress import ProgressConsole,ProgressTracker,Progress_GetCosts,Progress_ReadReference,Progress_GetConfidenceText
from drying.judge_schedule import Schedule_GetSlots,Schedule_CanStart,Schedule_Deduplicate,Schedule_Estimate
from drying.judge_pipeline import Judge_GetPlan,PAPER_TASKS,TASKS

ROOT=Path(__file__).resolve().parents[1]


class Clock:
    now=0.
    def __call__(self):return self.now


class Stream(io.StringIO):
    def __init__(self,tty=True):super().__init__();self.tty=tty
    def isatty(self):return self.tty


def Make_Event(fraction=.1,confidence='calibrated',eta=90):
    return dict(schema_version=1,event='progress',overall_fraction=fraction,elapsed_s=10.,eta_s=eta,
        eta_confidence=confidence,progress_confidence=confidence,message='正在计算',running_tasks=[])


def test_normal_stability_is_info_once_and_verbose_preserves_details():
    line='[A.q23] WARNING DT_LIMITED_BY_STABILITY {"requested_dt_s":0.25,"accepted_dt_s":0.01,"grid":[200,1]}'
    stream=Stream(False);console=ProgressConsole(stream)
    console.Progress_Log(line);console.Progress_Log(line)
    assert stream.getvalue().count('稳定性约束')==1 and 'WARNING' not in stream.getvalue()
    stream=Stream(False);ProgressConsole(stream,verbose=True).Progress_Log(line)
    assert 'INFO' in stream.getvalue() and 'requested_dt_s' in stream.getvalue() and 'NORMAL_STABILITY_LIMIT' in stream.getvalue()


@pytest.mark.parametrize('line',['WARNING RK_REJECTION count=25','WARNING MAX_STEPS_REACHED','WARNING VALIDATION_FAIL',
    'WARNING DT_LIMITED_BY_STABILITY {"accepted_dt_s":1e-8}'])
def test_real_solver_or_validation_warning_is_not_suppressed(line):
    stream=Stream(False);ProgressConsole(stream).Progress_Log(line);assert 'WARNING' in stream.getvalue()


@pytest.mark.parametrize('ansi',[True,False])
@pytest.mark.parametrize('times',[(605,599),(120,720),(720,120)])
def test_chinese_console_erases_complete_line(ansi,times):
    stream=Stream();clock=Clock();console=ProgressConsole(stream,ansi=ansi,clock=clock)
    for i,eta in enumerate(times):
        event=Make_Event(eta=eta);event['message']='二维辅助 很长的中文任务' if i==0 else 'Q1'
        clock.now+=6;console.Progress_Write(event)
    output=stream.getvalue()
    if ansi:assert output.count('\r\x1b[2K')==2
    else:assert output.count('\r'+' '*120+'\r')==2 or ' '*40 in output


def test_redirected_never_contains_ansi_or_carriage_return():
    stream=Stream(False);ProgressConsole(stream,ansi=True).Progress_Write(Make_Event())
    assert '\x1b' not in stream.getvalue() and '\r' not in stream.getvalue() and stream.getvalue().endswith('\n')


def test_elapsed_never_writes_task_fraction_or_pretends_ninety_percent():
    clock=Clock();job=dict(key='two',kind='validation_2d',group='validation',dependencies=[])
    tracker=ProgressTracker(dict(steps=[job],worker_count=3),{'two':dict(weight=1,confidence='unknown')},[],clock)
    tracker.Progress_Start('two')
    for t in [1,100,100000]:
        clock.now=t;event=tracker.Progress_Snapshot()
        assert event['task_fraction']==0 and event['progress_confidence']=='unknown' and event['eta_s'] is None


def test_structural_observation_holds_even_with_old_upper_hint():
    clock=Clock();job=dict(key='one',kind='original',group='original',dependencies=[])
    tracker=ProgressTracker(dict(steps=[job],worker_count=1),{'one':dict(weight=10,confidence='calibrated')},[],clock)
    tracker.Progress_Start('one');tracker.Progress_Update('one',.2,upper=.95,expected_s=1)
    clock.now=10000;assert tracker.Progress_Snapshot()['task_fraction']==.2


def test_rough_eta_is_range_measured_eta_is_precise():
    assert '～' in Progress_GetConfidenceText(Make_Event(confidence='rough'))
    assert Progress_GetConfidenceText(Make_Event(confidence='measured'))=='约 1:30'
    assert Progress_GetConfidenceText(Make_Event(confidence='unknown'))=='正在校准'


@pytest.fixture(scope='module')
def app():
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    yield QApplication.instance() or QApplication([])


def test_gui_large_gap_is_rate_limited(app,tmp_path):
    from drying.gui.judge_window import JudgeWindow
    window=JudgeWindow(tmp_path);window.show();window.outer.setValue(100)
    event=Make_Event(.187,eta=10*(1-.187)/.187);window.Progress_ApplyEvent(event)
    for _ in range(5):window.Progress_Animate(.2)
    assert 100<window.outer.value()<=180 and window.progress_target==1870
    for _ in range(300):window.Progress_Animate(.2)
    assert window.outer.value()<=1870;window.close()


@pytest.mark.parametrize('confidence',['rough','calibrated','unknown'])
def test_gui_conflicting_percent_eta_downgrades(app,tmp_path,confidence):
    from drying.gui.judge_window import JudgeWindow
    window=JudgeWindow(tmp_path);event=Make_Event(.839,confidence,10800);event['elapsed_s']=3960
    window.Progress_ApplyEvent(event)
    assert window.outer.maximum()==0 and '正在校准' in window.current.text();window.close()


def test_2d_cost_uses_2d_records_not_one_dimensional_multiple():
    plan=Judge_GetPlan(ROOT,['aux-2d']);costs=Progress_GetCosts(ROOT,plan,Progress_ReadReference(ROOT))
    for case in ['q1','q23','q4']:
        row=costs['B.2d.'+case+'.base']
        assert row['source'].startswith('work/cache/') and row['weight']>0


def test_missing_2d_history_is_unknown(tmp_path):
    costs=Progress_GetCosts(tmp_path,Judge_GetPlan(tmp_path,['aux-2d']),{})
    assert all(v['confidence']=='unknown' for k,v in costs.items() if k.startswith('B.2d.') and k.endswith('.base'))


def test_d_thermal_independent_of_auxiliary_and_mass_follows_production():
    jobs={j['key']:j for j in Judge_GetPlan(ROOT,PAPER_TASKS)['steps']}
    def ancestors(key):return set(jobs[key]['dependencies']).union(*(ancestors(k) for k in jobs[key]['dependencies']))
    for mode in ['M10','M01','M11']:
        for case in ['q1','q23','q4']:
            production=f'D.{mode}.{case}.production';mass=f'B.mass.{mode}.{case}'
            assert 'B.auxiliary' not in ancestors(production)
            assert production in jobs[mass]['dependencies'] and 'D.publish' not in ancestors(mass)
    assert 'B.auxiliary' in ancestors('D.M00.q23.matched')


def test_duplicate_reference_has_one_worker_and_explicit_aliases():
    plan=Judge_GetPlan(ROOT,PAPER_TASKS)
    assert plan['deduplicated_experiments']==4
    for case in ['q1','q23','q4']:
        assert plan['experiment_aliases'][f'D.M00.{case}.full_reference']=='B.reference.'+case
        assert sum(j['kind']=='reference_1d' and j['case']==case for j in plan['steps'])==1


def test_identity_does_not_alias_different_horizon_or_replay():
    jobs=[dict(key=str(i),case='q4',mode='M00',kind='experiment',experiment_kind='production',horizon=h,replay=r,pde=True,dependencies=[]) for i,(h,r) in enumerate([(100,None),(200,None),(100,'half')])]
    assert len(Schedule_Deduplicate(jobs)[0])==3


@pytest.mark.parametrize('gb,expected',[(4,6),(8,6),(15,6),(16,6),(32,6)])
def test_auto_resource_slots(gb,expected):assert Schedule_GetSlots('auto',gb,8)==expected


def test_slots_allow_three_1d_or_two_dimensional_plus_one_dimensional():
    one=dict(key='one',kind='experiment',dependencies=[]);two=dict(key='two',kind='validation_2d',dependencies=[])
    assert Schedule_CanStart(one,[one,one],3) and not Schedule_CanStart(one,[one,one,one],3)
    assert Schedule_CanStart(one,[two],3) and Schedule_CanStart(two,[two],3)


def test_paper_all_omits_all_animations_developer_includes_advanced():
    paper=Judge_GetPlan(ROOT,PAPER_TASKS);developer=Judge_GetPlan(ROOT,list(TASKS))
    assert not any(j.get('selection')=='gif' or j.get('gifs') for j in paper['steps'])
    assert not any(j['kind']=='developer_diagnostic' for j in paper['steps'])
    assert any(j.get('gifs') for j in developer['steps']) and any(j.get('force_reference') for j in developer['steps'])
    assert sum(j['kind']=='mass_measure' for j in paper['steps'])==12


def test_v2_stop_is_refused_before_process_access(tmp_path,monkeypatch):
    import drying.runner_control as runner
    monkeypatch.setattr(runner.psutil,'Process',lambda *a:pytest.fail('must not inspect/kill V2 for stop'))
    assert runner.Runner_Stop(tmp_path/'release_v2'/'package',123)==runner.RunnerStopResult.FAILED


def test_v2_build_refused_before_any_mutation(monkeypatch):
    import importlib.util
    spec=importlib.util.spec_from_file_location('build_v3_guard',ROOT/'scripts/build_release.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setattr(sys,'argv',['build_release.py','--dist-dir',str(ROOT/'release_v2'),'--update-code'])
    with pytest.raises(RuntimeError,match='PROTECTED'):module.Build_Run()


def test_parallel_2d_merge_does_not_overwrite_formal_1d(tmp_path):
    from drying.judge_pipeline import Judge_MergeWorker
    from drying.storage import Storage_WriteJson
    runtime=tmp_path/'runtime';workspace=tmp_path/'two'
    Storage_WriteJson(runtime/'work/validation/summary.json',{'q1_1d':{'numerical_status':'PASS'}})
    Storage_WriteJson(workspace/'work/validation/summary.json',{'q1_1d':{'numerical_status':'NOT_RERUN'},'q1_2d':{'value':'new'}})
    Judge_MergeWorker(runtime,dict(kind='validation_2d',case='q1'),workspace,{})
    result=json.loads((runtime/'work/validation/summary.json').read_text(encoding='utf-8'))
    assert result['q1_1d']['numerical_status']=='PASS' and result['q1_2d']['value']=='new'


def test_estimator_prioritizes_longest_ready_path():
    jobs=[dict(key=k,kind=kind,dependencies=deps,exclusive=exclusive) for k,kind,deps,exclusive in
          [('a','experiment',[],False),('barrier','publish',['a'],True),
           ('heavy','experiment',['a'],False),('mass','mass_measure',['a'],False)]]
    duration,path=Schedule_Estimate(jobs,dict(a=1,barrier=2,heavy=10,mass=3),1)
    assert duration==16 and path==['a','heavy','mass','barrier']


def test_extension_publish_waits_for_final_one_dimensional_validation():
    jobs={j['key']:j for j in Judge_GetPlan(ROOT,PAPER_TASKS)['steps']}
    assert 'B.1d.publish' in jobs['D.publish']['dependencies']


def test_reference_cache_hit_is_not_learned_as_cold_cost(tmp_path,monkeypatch):
    from drying import judge_tasks
    from drying.studies import trajectory,cache
    from drying.storage import Storage_WriteJson
    status={'complete':True,'fingerprint':'sealed'}
    Storage_WriteJson(tmp_path/'work/studies/experiments/reference/status.json',status)
    monkeypatch.setattr(judge_tasks,'Task_PrepareBaseline',lambda root:None)
    monkeypatch.setattr(trajectory,'Trajectory_GetSpec',lambda *a,**kw:{'experiment_id':'reference'})
    monkeypatch.setattr(trajectory,'Trajectory_Solve',lambda *a,**kw:status)
    monkeypatch.setattr(cache,'Cache_SealExperiment',lambda root,spec,value:value)
    assert judge_tasks.Task_Execute(tmp_path,{'kind':'reference_1d','case':'q1'})['cache_reused']


def test_paper_extension_render_never_calls_animation(tmp_path,monkeypatch):
    from drying import judge_plots
    from drying.studies import plot_contract,plots,animations
    monkeypatch.setattr(plot_contract,'StudyPlot_ReadManifest',lambda root:{'seal':'test'})
    monkeypatch.setattr(plot_contract,'StudyPlot_GetHash',lambda path:'test')
    monkeypatch.setattr(plots,'StudyPlot_SetStyle',lambda:None)
    monkeypatch.setattr(plots,'StudyPlot_Draw',lambda root,manifest,name:root/(name+'.png'))
    monkeypatch.setattr(animations,'StudyAnimation_Write',lambda *a:pytest.fail('paper rendering requested GIF'))
    judge_plots.Judge_DrawExtensions(tmp_path,gifs=False)
    receipt=json.loads((tmp_path/'work/studies/diagnostics/render_manifest.json').read_text(encoding='utf-8'))
    assert len(receipt['files'])==8 and receipt['pde_solves']==0 and not receipt['animations_selected']
