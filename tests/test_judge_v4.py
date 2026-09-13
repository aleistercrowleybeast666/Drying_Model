"""V4 scope, resource safety, explicit identities and task-local workers."""
import json
import os
from pathlib import Path
import shutil
import pytest
from drying.judge_pipeline import Judge_GetPlan,Judge_PreparePrivate,PAPER_TASKS,DEVELOPER_TASKS
from drying.judge_schedule import Schedule_GetResources,Schedule_GetSlots,Schedule_CanStart,Schedule_GetPriorities,Schedule_GetDispatch,Schedule_Deduplicate,Schedule_Estimate
from drying.judge_resources import Resource_CopyFile
from drying.storage import Storage_WriteJson

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('name,case',[('ref_q1_force_123','q1'),('ref_q23_force_123','q23'),('ref_q4_force_123','q4'),('two_q23','q23'),('dev_q4','q4'),('full_q1','q1'),('opaque_directory','q1')])
def test_private_workspace_case_never_parsed_from_name(tmp_path,name,case):
    runtime=tmp_path/'runtime'
    Storage_WriteJson(runtime/'work/recompute/production.json',{case:dict(case_id='actual',stages=[])})
    Storage_WriteJson(runtime/'work/cache/actual/status.json',{'complete':True})
    target=Judge_PreparePrivate(runtime,name,source_case=case)
    assert json.loads((target/'work/recompute/production.json').read_text())=={case:dict(case_id='actual',stages=[])}
    assert (target/'work/cache/actual/status.json').exists()


def test_hardlink_replacement_never_changes_shared_source(tmp_path):
    source=tmp_path/'source';target=tmp_path/'target';new=tmp_path/'new'
    source.write_text('old');new.write_text('new');Resource_CopyFile(source,target);Resource_CopyFile(new,target)
    assert source.read_text()=='old' and target.read_text()=='new'


def test_developer_preserves_18_thermal_12_mass_force_is_separate():
    paper=Judge_GetPlan(ROOT,PAPER_TASKS);dev=Judge_GetPlan(ROOT,DEVELOPER_TASKS)
    strict=lambda j:j.get('mode') in ['M10','M01','M11'] and j.get('experiment_kind') in ['full_reference','time_half']
    assert sum(strict(j) for j in dev['steps'])==18 and not any(strict(j) for j in paper['steps'])
    assert sum(j['kind']=='mass_measure' for j in dev['steps'])==12
    assert not any(j['force_reference'] for j in dev['steps'])
    forced=Judge_GetPlan(ROOT,DEVELOPER_TASKS+['force-reference'])
    assert any(j['force_reference'] for j in forced['steps'])
    jobs={j['key']:j for j in dev['steps']}
    for mode in ['M10','M01','M11']:
        for case in ['q1','q23','q4']:
            p=f'D.{mode}.{case}.production'
            assert all(p in jobs[k]['dependencies'] for k in [p.replace('production','full_reference'),p.replace('production','time_half'),f'B.mass.{mode}.{case}'])
    assert all(j['persistent'] for j in dev['steps'] if j['kind'] in ['experiment','mass_measure'])


@pytest.mark.parametrize('case',['q1','q23','q4'])
def test_twod_independent_directions_and_required_endpoint(case):
    jobs={j['key']:j for j in Judge_GetPlan(ROOT,DEVELOPER_TASKS)['steps']};p='B.2d.'+case
    assert jobs[p+'.radial']['dependencies']==jobs[p+'.axial']['dependencies']==[p+'.seed']
    assert jobs[p+'.time_half']['dependencies']==[p+'.base']
    assert (p+'.endpoint.radial' in jobs)==(case!='q1')
    assert not jobs[p]['pde'] and jobs[p]['kind']=='twod_assess'
    assert jobs[p+'.radial']['cpu_demand']==1


@pytest.mark.parametrize('cores,expected',[(1,1),(4,3),(6,5),(8,6),(16,6)])
def test_cpu_token_auto_leaves_core_for_gui(cores,expected):assert Schedule_GetSlots('auto',cpu_count=cores)==expected


def test_memory_budget_and_live_floor_both_enforced():
    resources=Schedule_GetResources('5',10000,6);assert resources['memory_budget_mb']==7200
    one={'kind':'experiment','cpu_demand':1,'memory_estimate_mb':1000}
    two=dict(one,memory_estimate_mb=3000)
    assert Schedule_CanStart(two,[one,one,one,one],5,7200,10000)
    assert not Schedule_CanStart(two,[one,one,one,one],5,6500,10000)
    assert not Schedule_CanStart(one,[],5,7200,1900)
    assert not Schedule_CanStart(one,[],5,7200,2800)


def test_memory_wait_has_no_fabricated_eta():
    from drying.judge_progress import ProgressTracker
    plan=Judge_GetPlan(ROOT,['q1'],'1')
    tracker=ProgressTracker(plan,{j['key']:dict(weight=10,confidence='calibrated') for j in plan['steps']})
    tracker.memory_waiting=True
    snap=tracker.Progress_Snapshot()
    assert snap['eta_s'] is None and snap['progress_confidence']=='unknown'
    assert snap['structural_fraction']==0


def test_short_writer_can_run_beside_independent_pde():
    pde=dict(kind='experiment',cpu_demand=1,memory_estimate_mb=1000,locks=[])
    writer=dict(kind='baseline',cpu_demand=1,memory_estimate_mb=100,locks=['baseline_manifest'])
    assert Schedule_CanStart(writer,[pde]*4,5,7200,10000)
    assert not Schedule_CanStart(writer,[writer],5,7200,10000)


def test_critical_path_priority_replaces_fixed_mass_priority():
    jobs=[dict(key='production',dependencies=[],kind='experiment'),dict(key='ref',dependencies=['production'],kind='experiment'),dict(key='mass',dependencies=['production'],kind='mass_measure')]
    costs=dict(production=5,ref=100,mass=3);priorities=Schedule_GetPriorities(jobs,costs)
    assert priorities['production']==105
    assert [j['key'] for j in Schedule_GetDispatch(jobs[1:],priorities,costs)]==['ref','mass']
    assert Schedule_Estimate(jobs,costs,2)[0]==105


def test_numerical_identity_ignores_display_kind_only_with_full_spec():
    spec=dict(initial='uniform',mode='M00',case='q1',mesh=[200,160,80],dt=.25,horizon=1800,replay=None)
    jobs=[dict(key=k,kind=k,numerical_spec=spec,pde=True,dependencies=[]) for k in ['reference_role','production_role']]
    unique,aliases=Schedule_Deduplicate(jobs);assert len(unique)==1 and aliases=={'production_role':'reference_role'}
    other=dict(key='half',kind='reference_role',numerical_spec=dict(spec,replay='actual'),pde=True,dependencies=[])
    assert len(Schedule_Deduplicate([*unique,other])[0])==2


def test_q1_full_alias_is_explicit_and_guarded():
    from drying.judge_identity import Identity_CheckQ1Alias
    plan=Judge_GetPlan(ROOT,DEVELOPER_TASKS);jobs={j['key']:j for j in plan['steps']}
    assert not jobs['D.full.q1']['pde'] and plan['experiment_aliases']['D.full.q1']=='A.q1'
    with pytest.raises(FileNotFoundError):Identity_CheckQ1Alias(ROOT/'work/absent_alias_probe')


def test_worker_limits_nested_threads():
    from drying.judge_worker import Worker_GetEnvironment
    env=Worker_GetEnvironment(ROOT)
    assert all(env[k]=='1' for k in ['OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS','NUMBA_NUM_THREADS'])


def test_twod_preparation_reuses_sealed_component_hardlink(tmp_path):
    from drying.judge_pipeline import Judge_PreparePrivate
    from drying.judge_resources import Resource_CopyFile
    runtime=tmp_path/'runtime'
    Storage_WriteJson(runtime/'work/recompute/production.json',{'q1':{'case_id':'q1_official'}})
    component=runtime/'work/validation/judge_2d/q1/base.json'
    Storage_WriteJson(component,{'case_id':'q1_two'})
    first=Judge_PreparePrivate(runtime,'two_q1_seed',source_case='q1',include_twod=True)
    local=first/'work/validation/judge_2d/q1/base.json'
    assert local.samefile(component)
    Judge_PreparePrivate(runtime,'two_q1_seed',source_case='q1',include_twod=True)
    Storage_WriteJson(local,{'case_id':'different'})
    assert json.loads(component.read_text())['case_id']=='q1_two'
    Resource_CopyFile(component,local)
    assert local.samefile(component)


def test_task_observer_restores_kernel_even_on_error(tmp_path):
    from drying.judge_observer import Progress_ObserveTask
    from drying import table_solver,cases
    before=table_solver.Rk4_Advance;other=cases.Rk4_Advance
    with pytest.raises(RuntimeError):
        with Progress_ObserveTask(tmp_path,dict(key='test',kind='twod_base',case='q1')):raise RuntimeError('injected')
    assert table_solver.Rk4_Advance is before and cases.Rk4_Advance is other


def test_gui_developer_button_does_not_select_force(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from drying.gui.judge_window import JudgeWindow
    app=QApplication.instance() or QApplication([]);window=JudgeWindow(ROOT)
    window.catalog_panel.mode_buttons['D'][0].click()
    assert not window.catalog_panel.force_validation.isChecked()
    assert not window.catalog_panel.force_data.isChecked()
    assert all(not v.isChecked() for k,v in window.checks.items() if not v.isEnabled())
    window.external_timer.stop();window.progress_timer.stop();window.close()


@pytest.mark.parametrize('case',['q1','q23','q4'])
def test_twod_subdag_matches_v3_bundle_evidence(tmp_path,monkeypatch,case):
    import copy
    from drying import cases,validation,comparison
    from drying.judge_validation import Judge_Validate2d
    from drying.judge_twod import TwoDimensional_GetPlan,TwoDimensional_Execute
    config=cases.Case_LoadConfig(ROOT);statuses={};calls=[]
    def Config_Load(root):return copy.deepcopy(config)
    def Case_Run(root,case,dim,nr=None,nz=None,cap=None,tag='',**kwargs):
        cap=cap or (1800 if case=='q1' else 259200);key=f'{case}_{nr}_{nz}_{cap}_{tag}'
        value=dict(case=case,dim=dim,case_id=key,fingerprint=key,nr=nr,nz=nz,cap=cap,complete=True,event=None)
        statuses[key]=value;calls.append((nr,nz,cap,tag));return value
    def Compare_Run(root,a,b,**kwargs):
        return dict(time_range_s=[0,min(statuses[a]['cap'],statuses[b]['cap'])],fine_id=b,coarse_id=a),[]
    for module in [cases,validation]:
        monkeypatch.setattr(module,'Case_LoadConfig',Config_Load)
        monkeypatch.setattr(module,'Case_Solve',Case_Run)
        monkeypatch.setattr(module,'Case_ReadStatus',lambda root,key:statuses[key])
    monkeypatch.setattr(cases,'Case_SolvePairEvents',lambda root:None)
    monkeypatch.setattr(validation,'Validation_CheckTime',lambda root,base:{'passed':True})
    monkeypatch.setattr(validation,'Validation_CheckEndpoint',lambda root,base,nr,nz,direction:dict(direction=direction,nr=nr,nz=nz))
    monkeypatch.setattr(validation,'Validation_CompareCaches',Compare_Run)
    monkeypatch.setattr(validation,'Validation_SaveComparison',lambda *a:None)
    monkeypatch.setattr(comparison,'Comparison_Run',lambda root,case:{'q':dict(one_id=case+'_official',max_abs_temperature={'time_s':900},max_abs_moisture={'time_s':1300})})
    for name in ['old','new']:
        root=tmp_path/name
        Storage_WriteJson(root/'configs/auxiliary_2d_validation.json',json.loads((ROOT/'configs/auxiliary_2d_validation.json').read_text(encoding='utf-8')))
        Storage_WriteJson(root/'work/recompute/production.json',{case:dict(case_id=case+'_official',fingerprint='formal')})
    original=Judge_Validate2d(tmp_path/'old',case)[case+'_2d'];prior_calls=list(calls);calls.clear()
    for task in TwoDimensional_GetPlan(case):TwoDimensional_Execute(tmp_path/'new',task)
    split=json.loads((tmp_path/'new/work/validation/summary.json').read_text(encoding='utf-8'))[case+'_2d']
    assert split==original and calls==prior_calls
