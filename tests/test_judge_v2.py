"""V2 routing/resource contracts; real cold-run evidence is recorded separately."""
import json
from pathlib import Path
import shutil
import sys

import numpy as np
import pytest

from drying.judge_pipeline import Judge_GetPlan, Judge_Main, TASKS

ROOT=Path(__file__).resolve().parents[1]


def test_default_entry_only_three_original_solves(tmp_path,capsys):
    assert Judge_Main(tmp_path,['--dry-run'])==0
    plan=json.loads(capsys.readouterr().out)
    assert [row['key'] for row in plan['steps']]==['A.q23','A.q4','A.q1']
    assert plan['worker_count']==2 and plan['automatic_dependencies']==[]
    assert {row['kind'] for row in plan['steps']}=={'original'}
    assert not (tmp_path/'work').exists()


def test_all_dag_is_acyclic_unique_and_has_separate_full_horizon_sources(tmp_path):
    plan=Judge_GetPlan(tmp_path,list(TASKS));jobs=plan['steps']
    assert len({j['key'] for j in jobs})==len(jobs)
    done=set()
    for row in jobs:
        assert set(row['dependencies'])<=done
        done.add(row['key'])
    assert len([j for j in jobs if j['kind']=='mass_measure'])==12
    assert len([j for j in jobs if j['kind']=='full_production'])==3
    assert len([j for j in jobs if j['kind']=='original'])==3
    assert all(j.get('private')==j['case'] for j in jobs if j['kind']=='validation_1d')
    for forbidden in ['pilot','fixed40','fixed80','fixed160','Stage_Validate','Validation_Run(1d)']:
        assert forbidden not in json.dumps(jobs)


def test_plot_only_missing_dependencies_never_adds_pdes(tmp_path):
    from drying.judge_plots import Judge_DrawOriginal
    plan=Judge_GetPlan(tmp_path,['static','gif'])
    assert not plan['requires_pde'] and all(not j['pde'] for j in plan['steps'])
    with pytest.raises(RuntimeError,match='PLOT_INPUT_MISSING'):
        Judge_DrawOriginal(tmp_path,'static')
    assert not (tmp_path/'work').exists()


def test_frozen_mesh_detects_corruption_without_pilot(tmp_path,monkeypatch):
    from drying.mesh import Mesh_PrepareCase
    import drying.mesh as mesh
    for directory in ['configs','data','src']:
        shutil.copytree(ROOT/directory,tmp_path/directory,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    monkeypatch.setenv('DRYING_JUDGE_FROZEN_MESH','1')
    monkeypatch.setattr(mesh,'Mesh_GetPilot',lambda *a:pytest.fail('Judge runtime must never call pilot'))
    result=Mesh_PrepareCase(tmp_path,'q23')
    assert result['profiles']['radial']['monitor_hash']
    path=tmp_path/'configs/frozen_mesh/q23_radial_monitor.npz'
    path.write_bytes(b'corrupt release resource')
    with pytest.raises(RuntimeError,match='FROZEN_MESH_CONFIGURATION_MISSING_OR_MISMATCH'):
        Mesh_PrepareCase(tmp_path,'q23')


def test_frozen_schedule_matches_actual_accepted_paper_schedule():
    data=json.loads((ROOT/'configs/frozen_mesh/manifest.json').read_text(encoding='utf-8'))
    assert [s['nr'] for s in data['schedules']['q23']]==[200,160,80]
    assert data['schedules']['q23'][-1]['t_end']==259200
    assert [s['nr'] for s in data['schedules']['q1']]==[200,160,80,40]
    assert [s['nr'] for s in data['schedules']['q4']]==[200,160,80,40]


def test_original_worker_bypasses_legacy_and_exports_explicit_id(tmp_path,monkeypatch):
    from drying.judge_tasks import Task_Execute
    import drying.table_solver as solver
    import drying.export as export
    import drying.table_reference as reference
    import drying.validation as validation
    import drying.cases as cases
    status=dict(case_id='table_id',fingerprint='f',case='q23')
    monkeypatch.setattr(solver,'Table_SolveSchedule',lambda root,case:status)
    monkeypatch.setattr(validation,'Validation_Run',lambda *a,**k:pytest.fail('hidden validation'))
    monkeypatch.setattr(cases,'Case_GetSelected',lambda *a:pytest.fail('implicit source selection'))
    calls=[]
    monkeypatch.setattr(export,'Export_Run',lambda root,case,source_case_id:calls.append((case,source_case_id)))
    monkeypatch.setattr(reference,'Table_CheckReference',lambda *a:dict(status='PASS'))
    monkeypatch.setattr(reference,'Table_SealProduction',lambda *a:dict())
    Task_Execute(tmp_path,dict(kind='original',case='q23'))
    assert calls==[('q23','table_id')]


def test_early_stop_orchestrator_uses_same_kernel_without_changing_full_horizon():
    import drying.table_solver as table
    import drying.cases as cases
    from drying.rk4 import Rk4_Advance
    from drying.events import Event_Locate
    assert table.Rk4_Advance is Rk4_Advance and cases.Rk4_Advance is Rk4_Advance
    assert table.Event_Locate is Event_Locate
    import inspect
    assert 'stop_on_event' not in inspect.signature(cases.Case_Solve).parameters
    assert inspect.signature(table.Table_SolveSchedule).parameters['stop_on_event'].default is True


def test_build_refuses_old_release_even_if_it_does_not_exist(tmp_path,monkeypatch):
    import importlib.util
    spec=importlib.util.spec_from_file_location('build_v2_test',ROOT/'scripts/build_release.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    target=ROOT/'release'/'must_not_be_created_by_test'
    target_before=target.exists()
    monkeypatch.setattr(module,'NAME',target.name)
    monkeypatch.setattr(sys,'argv',['build_release.py','--dist-dir',str(ROOT/'release'),'--stage-only'])
    with pytest.raises(RuntimeError,match='OLD_RELEASE_PROTECTED'):
        module.Build_Run()
    assert target.exists()==target_before


def test_cached_table_rejects_changed_event_but_allows_new_diagnostic(tmp_path):
    from drying.table_reference import Table_SealProduction
    folder=tmp_path/'work/cache/q4_table';folder.mkdir(parents=True)
    for name in ['status.json','mesh.npz','chunk_00000.npz','event.npz']:
        (folder/name).write_bytes(b'original source')
    status=dict(case_id='q4_table',fingerprint='frozen',stages=[])
    sealed=Table_SealProduction(tmp_path,'q4',status)
    (folder/'paired_events.npz').write_bytes(b'new auxiliary evidence')
    assert Table_SealProduction(tmp_path,'q4',status)==sealed
    (folder/'event.npz').write_bytes(b'corrupted event')
    with pytest.raises(RuntimeError,match='TABLE_CACHE_MISMATCH'):
        Table_SealProduction(tmp_path,'q4',status)
