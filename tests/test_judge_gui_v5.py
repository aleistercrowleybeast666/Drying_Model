"""Small GUI-only regressions; no solver, plotting or package execution."""
import os
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def window(monkeypatch):
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from drying.gui.catalog_panel import CatalogPanel
    import drying.gui.judge_window as module
    monkeypatch.setattr(CatalogPanel,'Cache_Refresh',lambda self:None)
    monkeypatch.setattr(module,'Runner_GetProcess',lambda root:None)
    app=QApplication.instance() or QApplication([])
    widget=module.JudgeWindow(ROOT)
    widget.external_timer.stop();widget.progress_timer.stop()
    yield widget
    widget.close();widget.deleteLater();app.processEvents()


def test_progress_never_cycles_or_moves_back_and_keeps_failure(window):
    event=dict(schema_version=1,event='progress',overall_fraction=.4,elapsed_s=10,eta_s=15,
        progress_confidence='measured',eta_confidence='measured',running_tasks=[],message='运行中')
    window.Progress_ApplyEvent(event)
    high=window.outer.value()
    window.Progress_ApplyEvent(dict(event,overall_fraction=.1,progress_confidence='unknown'))
    window.Progress_Animate(.2)
    assert window.outer.maximum()==10000 and window.outer.value()>=high
    window.Progress_ApplyEvent(dict(event,overall_fraction=.1))
    assert window.outer.value()>=high
    window.Progress_ApplyEvent(dict(event,event='run_failed',overall_fraction=.1))
    window.Progress_Animate(.2)
    assert window.outer.format()=='失败' and window.outer.value()>=high
    assert window.outer.value()<10000


def test_running_row_finishes_and_stop_stays_outside_catalog(window):
    panel=window.catalog_panel
    panel.Progress_Apply(dict(run_id='one',running_tasks=[dict(task_key='C.q1_curves')]))
    assert panel.status_labels['plot.q1_curves'].text()=='正在绘图'
    panel.Progress_Apply(dict(run_id='one',running_tasks=[],task_states={'C.q1_curves':'PASS'}))
    assert '已完成' in panel.status_labels['plot.q1_curves'].text()
    assert not window.controls_scroll.widget().isAncestorOf(window.stop)
    assert not window.controls_scroll.widget().isAncestorOf(window.start)
    window.Controls_Set(True)
    assert window.stop.isEnabled() and window.refresh_button.isEnabled()
    assert not panel.checks['plot.q4_curves'].isEnabled()


def test_cache_scan_failure_clears_display_and_disables_c_d(window):
    panel=window.catalog_panel
    panel.snapshot=dict(items={'plot.q1_curves':dict(complete=True,enabled=True)})
    window.Results_Refresh(dict(official={'q23':dict(drying_time_h=57.6215)}))
    assert '本机缓存已核验' in window.official_values.text()
    panel.Cache_Failed('文件被占用')
    assert panel.snapshot is None
    assert '暂无有效本机数据' in window.official_values.text()
    assert all(not c.isEnabled() for k,c in panel.checks.items() if panel.catalog[k]['mode'] in ['C','D'])


def test_assessment_requires_validation_evidence(monkeypatch,tmp_path):
    from drying.pipeline_plan import Catalog_Read
    import drying.catalog_cache as module
    catalog=Catalog_Read(ROOT)
    key=next(k for k,r in catalog.items() if r.get('kind')=='twod_assess')
    row=catalog[key]
    available=set(row['requires'])
    monkeypatch.setattr(module,'Artifact_GetIdentity',lambda root:{})
    monkeypatch.setattr(module,'Artifact_ReadManifest',lambda *args:{})
    monkeypatch.setattr(module,'Artifact_GetStatus',lambda root,k,*args:dict(complete=k in available,status='MISSING'))
    state=module.Catalog_ScanCache(tmp_path,catalog)['items'][key]
    assert not state['enabled']
    assert {r['key'] for r in state['missing']}==set(row['validation_requires'])
    available.update(row['validation_requires'])
    assert module.Catalog_ScanCache(tmp_path,catalog)['items'][key]['enabled']


def test_gui_workspace_copy_without_developer_scripts(tmp_path):
    from drying.judge_pipeline import Judge_CopyResources
    code=tmp_path/'package/code';data=tmp_path/'package/data';target=tmp_path/'runtime'
    for folder,name in [(code/'src','module.py'),(code/'configs','config.json'),(data,'input.npz')]:
        folder.mkdir(parents=True,exist_ok=True);(folder/name).write_bytes(b'fixture')
    Judge_CopyResources(code,data,target)
    assert (target/'src/module.py').read_bytes()==b'fixture'
    assert (target/'data/input.npz').read_bytes()==b'fixture'
    assert not (target/'scripts').exists()
