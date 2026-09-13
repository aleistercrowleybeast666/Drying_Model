import json
import os
from pathlib import Path
import pytest
from drying.pipeline_plan import Catalog_Read,Catalog_GetPresets,PipelinePlan_Build,Pipeline_CheckPrerequisites
from drying.catalog_cache import Catalog_ScanCache
from drying.artifact_contract import Artifact_Seal,Artifact_GetIdentity
from drying.judge_schedule import Schedule_GetResources,Schedule_CanStart,Schedule_GetMemoryFailure

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def data_root(tmp_path,monkeypatch):
    import drying.artifact_contract as contract
    import drying.catalog_cache as scan
    identity=Artifact_GetIdentity(ROOT)
    monkeypatch.setattr(contract,'Artifact_GetIdentity',lambda root:identity)
    monkeypatch.setattr(scan,'Artifact_GetIdentity',lambda root:identity)
    return tmp_path


def Cache_Create(root,key):
    path=root/'work/datasets'/key/'fields.bin';path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'sealed data')
    Artifact_Seal(root,key,'test',[path.relative_to(root).as_posix()])
    return path


def test_partial_cache_enables_only_corresponding_c_and_d(data_root):
    catalog=Catalog_Read(ROOT)
    Cache_Create(data_root,'official.q1');Cache_Create(data_root,'official.q23')
    states=Catalog_ScanCache(data_root,catalog)['items']
    for key in ['plot.q1_curves','plot.q2_curves','plot.q3_curves','validation.m00.q1.spatial','validation.m00.q23.time']:
        assert states[key]['enabled']
    for key in ['plot.q4_curves','validation.m00.q4.spatial','plot.q1_1d_2d_compare','validation.2d.q1.radial']:
        assert not states[key]['enabled'] and states[key]['missing']
    Cache_Create(data_root,'innovation.2d.q1')
    states=Catalog_ScanCache(data_root,catalog)['items']
    assert states['plot.q1_1d_2d_compare']['enabled']
    assert states['validation.2d.q1.radial']['enabled']
    assert not states['plot.q4_curves']['enabled']


def test_refresh_deleted_or_corrupt_cache_and_empty_folders(data_root):
    catalog=Catalog_Read(ROOT);path=Cache_Create(data_root,'official.q1')
    assert Catalog_ScanCache(data_root,catalog)['items']['plot.q1_curves']['enabled']
    path.write_bytes(b'corruption')
    assert not Catalog_ScanCache(data_root,catalog)['items']['plot.q1_curves']['enabled']
    path=Cache_Create(data_root,'official.q1');path.unlink()
    assert not Catalog_ScanCache(data_root,catalog)['items']['plot.q1_curves']['enabled']


def test_catalog_all_producers_and_modes_are_independent():
    catalog=Catalog_Read(ROOT);presets=Catalog_GetPresets(ROOT)
    assert sum(r['mode']=='A' for r in catalog.values())==3
    assert sum(r['mode']=='C' for r in catalog.values())==30
    assert sum(r['mode']=='D' for r in catalog.values())==59
    assert all(catalog[k]['mode'] in ['A','B'] for k in presets['paper'])
    assert all(catalog[k]['mode']=='D' for k in presets['validation'])
    assert all(r.get('mode_id') in ['M00','M10','M01','M11'] for r in catalog.values() if r.get('kind')=='mass')


def test_missing_c_d_never_add_production(tmp_path):
    from unittest.mock import patch
    with patch('drying.pipeline_plan.Catalog_Read',lambda root:Catalog_Read(ROOT)),patch('drying.judge_progress.Progress_GetIdentity',return_value={}):
        for key,code in [('plot.q4_curves','PLOT_INPUT_MISSING'),('validation.m00.q1.spatial','VALIDATION_PREREQUISITE_MISSING')]:
            plan=PipelinePlan_Build(tmp_path,[key])
            assert all(j['layer'] in ['C','D'] for j in plan['steps'])
            with pytest.raises(RuntimeError,match=code):Pipeline_CheckPrerequisites(plan)


def test_all_plan_barrier_and_aliases():
    plan=PipelinePlan_Build(ROOT,Catalog_GetPresets(ROOT)['all'])
    phase1={j['key'] for j in plan['steps'] if j['phase']==1}
    assert all(phase1<=set(j['dependencies']) for j in plan['steps'] if j['phase']==2)
    assert len([j for j in plan['steps'] if j['layer']=='B' and j['artifact']=='innovation.full.q4'])==1
    assert not plan['missing_prerequisites']


@pytest.mark.parametrize('total,available,expected',[(2048,1433.6,384),(4096,1638.4,491.52),(8192,3000,983.04),(16384,6000,1966.08),(32768,12000,2048)])
def test_dynamic_memory_reserve(total,available,expected):
    r=Schedule_GetResources(total_mb=total,available_mb=available,cpu_count=8)
    assert r['reserve_mb']==pytest.approx(expected)
    assert r['cpu_tokens']>=1
    assert Schedule_CanStart(dict(memory_estimate_mb=512),[],r['cpu_tokens'],r['memory_budget_mb'],available,r['reserve_mb'])


def test_large_task_fails_and_persistent_rss_is_incremental():
    r=Schedule_GetResources(total_mb=4096,available_mb=1600,cpu_count=8)
    large=dict(key='large2d',memory_estimate_mb=2048)
    assert not Schedule_CanStart(large,[],1,4096,1600,r['reserve_mb'])
    reason=Schedule_GetMemoryFailure(large,1600,r)
    assert all(s in reason for s in ['MEMORY_REQUIREMENT_UNSATISFIED','expected=2048.0','available=1600.0','reserve=491.5'])
    worker=dict(memory_estimate_mb=1200,resident_rss_mb=900)
    assert Schedule_CanStart(worker,[],1,2000,850,r['reserve_mb'])
    assert not Schedule_CanStart(dict(memory_estimate_mb=1200),[],1,2000,850,r['reserve_mb'])


def test_gui_refresh_mode_selection_and_busy_controls(data_root,monkeypatch):
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from drying.gui.catalog_panel import CatalogPanel
    import drying.gui.catalog_panel as panel_module
    catalog=Catalog_Read(ROOT)
    monkeypatch.setattr(panel_module,'Catalog_Read',lambda root:catalog)
    monkeypatch.setattr(panel_module,'Catalog_GetPresets',lambda root:Catalog_GetPresets(ROOT))
    app=QApplication.instance() or QApplication([]);panel=CatalogPanel(data_root)
    Cache_Create(data_root,'official.q1');Cache_Create(data_root,'official.q23')
    panel.Cache_Apply(Catalog_ScanCache(data_root,catalog))
    before={k for k,c in panel.checks.items() if c.isChecked()}
    panel.mode_buttons['C'][0].click()
    assert panel.checks['plot.q1_curves'].isChecked()
    assert not panel.checks['plot.q4_curves'].isEnabled()
    assert not panel.checks['plot.q4_curves'].isChecked()
    assert before<={k for k,c in panel.checks.items() if c.isChecked()}
    assert '问题4正式数据' in panel.checks['plot.q4_curves'].toolTip()
    path=data_root/'work/datasets/official.q1/fields.bin';path.unlink()
    panel.Cache_Apply(Catalog_ScanCache(data_root,catalog))
    assert not panel.checks['plot.q1_curves'].isChecked()
    assert panel.checks['plot.q2_curves'].isChecked()
    panel.mode_buttons['C'][1].click()
    assert all(not c.isChecked() for k,c in panel.checks.items() if catalog[k]['mode']=='C')
    panel.deleteLater();app.processEvents()


def test_render_guard_forbids_reintegration():
    from drying.render_layer import Render_BlockSolvers
    from drying.studies import analysis,trajectory
    original=trajectory.Trajectory_Solve
    with Render_BlockSolvers():
        with pytest.raises(RuntimeError,match='PLOT_SOLVER_CALL_FORBIDDEN'):trajectory.Trajectory_Solve(None,None)
        with pytest.raises(RuntimeError,match='PLOT_SOLVER_CALL_FORBIDDEN'):analysis.Analysis_GetExactState(None,None,1)
    assert trajectory.Trajectory_Solve is original
