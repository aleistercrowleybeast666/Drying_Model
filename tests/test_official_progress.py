import io
import json
from pathlib import Path
import pytest
from drying.official_progress import (OfficialProgress,OfficialProgress_GetCaseFraction,
    OfficialProgress_GetHistory,OfficialProgress_GetWork)

ROOT=Path(__file__).resolve().parents[1]


def Status_Write(root,at,parent_complete=False):
    parent=root/'work/runtime/q1/work/cache/q1_1d_stage_schedule_table_dt0.25_sabc/status.json'
    child=parent.parent.parent/'q1_1d_nr200_stagepart_abc_0/status.json'
    parent.parent.mkdir(parents=True,exist_ok=True);child.parent.mkdir(parents=True,exist_ok=True)
    parent.write_text(json.dumps(dict(case='q1',purpose='table_production',fingerprint='abc',
        complete=parent_complete,simulated_time_s=0)),encoding='utf-8')
    child.write_text(json.dumps(dict(case='q1',tag='stagepart_abc_0',nr=200,start_time=0,simulated_time_s=at)),encoding='utf-8')
    return child


@pytest.fixture
def progress(tmp_path,monkeypatch):
    monkeypatch.setattr('drying.official_progress.OfficialProgress_GetMachine',lambda:{'host':'test'})
    clock=[0.];stream=io.StringIO()
    value=OfficialProgress(tmp_path,ROOT,['q1'],{'science':1},{},1,clock=lambda:clock[0],stream=stream)
    value.OfficialProgress_StartCase('q1');value.since['q1']=0
    return value,clock,stream


def test_real_grid_weight_and_current_stagepart_only(tmp_path):
    schedule=[dict(t_start=0,t_end=10,nr=200),dict(t_start=10,t_end=20,nr=100)]
    assert OfficialProgress_GetWork(schedule,20)==90_000_000
    Status_Write(tmp_path,5)
    row=OfficialProgress_GetCaseFraction(tmp_path,'q1',schedule,20)
    assert row['fraction']==pytest.approx(40/90)
    rogue=tmp_path/'work/runtime/q1/work/cache/other_stagepart_old_0/status.json'
    rogue.parent.mkdir();rogue.write_text(json.dumps(dict(case='q1',tag='stagepart_old_0',nr=200,simulated_time_s=10000)))
    assert OfficialProgress_GetCaseFraction(tmp_path,'q1',schedule,20)['fraction']==row['fraction']


def test_pause_corrupt_status_and_lower_state_never_advance_clock(progress):
    value,clock,_=progress;path=Status_Write(value.root,30)
    first=value.OfficialProgress_GetSnapshot()
    clock[0]=120
    assert value.OfficialProgress_GetSnapshot()['overall_fraction']==first['overall_fraction']
    path.write_text('{unfinished')
    assert value.OfficialProgress_GetSnapshot()['overall_fraction']==first['overall_fraction']
    Status_Write(value.root,10)
    assert value.OfficialProgress_GetSnapshot()['overall_fraction']==first['overall_fraction']


def test_first_run_eta_waits_for_observed_advance(progress):
    value,clock,_=progress;Status_Write(value.root,0)
    assert value.OfficialProgress_GetSnapshot()['eta_s'] is None
    clock[0]=10;Status_Write(value.root,60)
    event=value.OfficialProgress_GetSnapshot()
    assert event['eta_s']>0 and event['eta_confidence']=='observed'
    clock[0]=60
    held=value.OfficialProgress_GetSnapshot()
    assert held['overall_fraction']==event['overall_fraction'] and held['eta_s'] is None


def test_parent_complete_is_not_success_receipt(progress):
    value,_,_=progress;Status_Write(value.root,1800,True)
    assert value.OfficialProgress_GetSnapshot()['cases']['q1']['fraction']<1
    value.OfficialProgress_CompleteCase('q1',dict(production={'actual_end_s':1800},cache_reused=True))
    row=value.OfficialProgress_GetSnapshot('PASS')
    assert row['overall_fraction']==1 and row['cases']['q1']['state']=='CACHED'


@pytest.mark.parametrize('outcome',['FAIL','STOPPED'])
def test_failed_or_stopped_below_100(progress,outcome):
    value,_,stream=progress;Status_Write(value.root,100000)
    event=value.OfficialProgress_Write(outcome,force=True)
    assert event['overall_fraction']<1 and event['eta_s'] is None
    assert '100.0%' not in stream.getvalue()


def test_redirect_has_no_cr_ansi_and_throttles(progress):
    value,clock,stream=progress;Status_Write(value.root,10)
    value.OfficialProgress_Write();clock[0]=2;value.OfficialProgress_Write()
    assert len(stream.getvalue().splitlines())==1
    clock[0]=6;value.OfficialProgress_Write()
    assert len(stream.getvalue().splitlines())==2
    assert '\r' not in stream.getvalue() and '\x1b' not in stream.getvalue()
    logs=[json.loads(s) for s in (value.root/'logs/progress.jsonl').read_text(encoding='utf-8').splitlines()]
    assert all('timestamp' in row and 'cases' in row for row in logs)


def test_successful_same_machine_same_science_history_only():
    old=dict(status='PASS',scientific_identity={'x':1},machine={'host':'same'},selected_cases=['q1'],
        cases=[dict(case='q1',status='PASS',wall_s=30,cache_reused=False)])
    assert OfficialProgress_GetHistory(old,{'x':1},['q1'],{'host':'same'})=={'q1':30}
    for bad in [dict(old,status='FAIL'),dict(old,status='STOPPED'),dict(old,cases=[]),
        dict(old,scientific_identity={'x':2}),dict(old,machine={'host':'else'}),
        dict(old,cases=[dict(case='q1',status='PASS',wall_s=1,cache_reused=True)])]:
        assert OfficialProgress_GetHistory(bad,{'x':1},['q1'],{'host':'same'})=={}
    assert OfficialProgress_GetHistory(old,{'x':1},['q4'],{'host':'same'})=={}
