"""Bounded source-release, GUI and evidence tests; never integrates a PDE."""
import json
import os
from pathlib import Path
import pytest
from drying.pipeline_plan import Catalog_Read,Catalog_GetPresets,PipelinePlan_Build

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def window(monkeypatch):
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from drying.gui.catalog_panel import CatalogPanel
    import drying.gui.judge_window as module
    monkeypatch.setattr(CatalogPanel,'Cache_Refresh',lambda self:None)
    monkeypatch.setattr(module,'Runner_GetProcess',lambda root:None)
    app=QApplication.instance() or QApplication([]);widget=module.JudgeWindow(ROOT)
    widget.external_timer.stop();widget.progress_timer.stop()
    yield widget
    widget.close();widget.deleteLater();app.processEvents()


def test_unknown_eta_keeps_structural_progress(window):
    event=dict(schema_version=1,event='progress',overall_fraction=.1,structural_fraction=.1,
        progress_confidence='unknown',eta_confidence='unknown',elapsed_s=10,eta_s=None,running_tasks=[],message='积分中')
    window.Progress_ApplyEvent(event);first=window.outer.value()
    window.Progress_ApplyEvent(dict(event,structural_fraction=.3,elapsed_s=30))
    assert first==1000 and window.outer.value()==3000
    assert '正在校准' in window.current.text() and window.outer.maximum()==10000


def test_full_preset_includes_disabled_phase_two_and_survives_refresh(window,monkeypatch):
    panel=window.catalog_panel;panel.select_buttons[2].click()
    assert all(c.isChecked() for c in panel.checks.values())
    snapshot=dict(items={k:dict(enabled=r['mode'] in ['A','B'],complete=False,missing=[],status='缺前置') for k,r in panel.catalog.items()},scanned_at='test')
    panel.Cache_Apply(snapshot)
    assert all(c.isChecked() for c in panel.checks.values())
    plan=PipelinePlan_Build(ROOT,[k for k,c in panel.checks.items() if c.isChecked()])
    assert {j['layer'] for j in plan['steps']}==set('ABCD') and not plan['missing_prerequisites']
    first={j['key'] for j in plan['steps'] if j['phase']==1}
    assert all(first<=set(j['dependencies']) for j in plan['steps'] if j['phase']==2)
    panel.select_buttons[3].click();panel.mode_buttons['C'][0].click()
    assert not any(c.isChecked() for c in panel.checks.values())


def test_all_thirty_renderer_dependencies_cover_actual_accesses():
    catalog=Catalog_Read(ROOT);plots=[r for r in catalog.values() if r['mode']=='C']
    assert len(plots)==30
    thermal={'innovation.full.'+c for c in ['q23','q4']}|{f'innovation.thermal.{m}.{c}' for c in ['q23','q4'] for m in ['M10','M01','M11']}
    studies={
        'thermal_moisture':thermal,'thermal_temperature':thermal,'thermal_modes':thermal,'thermal_interactions':thermal,
        'end_effect_extent':{f'innovation.{kind}.{c}' for kind in ['matched','2d','full'] for c in ['q23','q4']},
        'geometry_property_cross':{'innovation.full.q23','innovation.full.q4','innovation.cross.p3_shrink','innovation.cross.p4_fixed'},
        'environment_robustness':{'innovation.full.q23','innovation.full.q4'}|{f'innovation.tail.{c}.{n}' for c in ['q23','q4'] for n in [30,90]},
        'verification_evidence':{'official.q1','official.q23','official.q4'}}
    for row in plots:
        name=row['renderer']
        if row['path'].startswith('results/studies/'):
            expected=studies.get(name,{'innovation.full.q23','innovation.full.q4'})
        elif row['animation']:
            cases=['q23','q4'] if name.startswith('q3_q4') else ['q23' if name.startswith('q3') else 'q4']
            expected={('official.' if 'radial_section' in name else 'innovation.2d.')+c for c in cases}
        else:
            case={'1':'q1','2':'q23','3':'q23','4':'q4'}[name[1]]
            expected={('innovation.2d.' if name.endswith('_3d') else 'official.')+case}
            if name.endswith(('_compare','_max_error_section')):expected.add('innovation.2d.'+case)
        assert expected<=set(row['requires']),row['key']


def test_source_paths_and_worker_commands(tmp_path):
    from drying.runtime import Runtime_GetCode,Runtime_GetData,Runtime_BuildRecomputeCommand
    from drying.official_cli import Official_GetCode,Official_GetData,Official_GetCommand
    (tmp_path/'dependencies/src/drying').mkdir(parents=True);(tmp_path/'dependencies/data').mkdir()
    (tmp_path/'dependencies/backend.py').write_text('');(tmp_path/'main.py').write_text('')
    assert Runtime_GetCode(tmp_path)==Official_GetCode(tmp_path)==tmp_path/'dependencies'
    assert Runtime_GetData(tmp_path)==Official_GetData(tmp_path)==tmp_path/'dependencies/data'
    assert Runtime_BuildRecomputeCommand(['--worker-json','one.json'],tmp_path)[-3:]==[str(tmp_path/'dependencies/backend.py'),'--worker-json','one.json']
    assert Official_GetCommand(tmp_path,'q4')[-3:]==[str(tmp_path/'main.py'),'--worker','q4']


def test_independent_raw_inputs_keep_original_identity(tmp_path,monkeypatch):
    import importlib.util
    import shutil
    import numpy as np
    from drying.runtime import Runtime_GetRawData,Runtime_PrepareInputs,Runtime_GetTemplate,Runtime_StageRaw
    spec=importlib.util.spec_from_file_location('final_prepare',ROOT/'scripts/prepare_release_v5_final.py')
    prep=importlib.util.module_from_spec(spec);spec.loader.exec_module(prep)
    package=tmp_path/'standalone';files=prep.Prepare_RawInputs(package)
    assert len(files)==7 and not (package/'dependencies/data/raw').exists()
    assert Runtime_GetRawData(package)==package/'原始题目数据'
    manifest=json.loads((package/'dependencies/data/input_manifest.json').read_text(encoding='utf-8'))
    assert not Path(manifest['source']).is_absolute()
    assert Runtime_GetTemplate(package,manifest,4)==package/'原始题目数据/附件3/result4.xlsx'
    workspace=tmp_path/'parser'
    result=Runtime_PrepareInputs(package,workspace)
    expected=json.loads((ROOT/'data/input_manifest.json').read_text(encoding='utf-8'))
    assert result['hash']==expected['hash'] and not Path(result['source']).is_absolute()
    with np.load(ROOT/'data/inputs.npz') as original,np.load(workspace/'data/inputs.npz') as actual:
        assert original.files==actual.files
        assert all(np.array_equal(original[key],actual[key]) for key in original.files)
    terminal=tmp_path/'terminal-work'
    Runtime_StageRaw(package,terminal,templates_only=True)
    assert len(list((terminal/'data/raw').rglob('*.xlsx')))==4
    assert not list((terminal/'data/raw').rglob('*.pdf'))
    assert Runtime_GetRawData(ROOT)==ROOT/'data/raw'
    path=package/'原始题目数据/附件1.xlsx';path.write_bytes(b'changed')
    with pytest.raises(ValueError,match='RAW_INPUT_HASH_MISMATCH'):
        Runtime_PrepareInputs(package,tmp_path/'bad')


def test_cost_alias_and_analysis_source_locks():
    from drying.judge_progress import Progress_GetCostAlias,Progress_GetCosts,Progress_ReadReference
    from drying.judge_schedule import Schedule_CanStart
    assert Progress_GetCostAlias(dict(key='B.2d.q23',kind='twod_base'))=='B.2d.q23.base'
    assert Progress_GetCostAlias(dict(key='D.2d.q4.radial',kind='twod_radial'))=='B.2d.q4.radial'
    plan=PipelinePlan_Build(ROOT,Catalog_GetPresets(ROOT)['validation'])
    jobs=[j for j in plan['steps'] if j.get('validation_kind','').startswith('thermal_')]
    left=next(j for j in jobs if j['mode']=='M10' and j['case']=='q23')
    same=next(j for j in jobs if j['mode']=='M10' and j['case']=='q23' and j['key']!=left['key'])
    other=next(j for j in jobs if j['mode']=='M11' and j['case']=='q23')
    assert 'analysis-source:innovation.thermal.M10.q23' in left['locks']
    assert not Schedule_CanStart(same,[left],6)
    assert Schedule_CanStart(other,[left],6)
    costs=Progress_GetCosts(ROOT,plan,Progress_ReadReference(ROOT))
    assert len(costs)==len(plan['steps']) and all(r['weight']>0 for r in costs.values())
    directional=[j for j in plan['steps'] if j['kind'] in ['twod_radial','twod_axial']]
    assert all('validation.2d.'+j['case']+'.seed' in j['requires'] for j in directional)


def test_d_evidence_merge_hydrate_and_missing_file_rejects_assess(tmp_path,monkeypatch):
    import drying.artifact_contract as contract
    from drying.pipeline_runtime import Pipeline_Merge
    from drying.validation_layer import Validation_Execute
    monkeypatch.setattr(contract,'Artifact_GetIdentity',lambda root:{'science':1,'input_hash':'i','numerical_source_hash':'n','frozen_mesh_hash':'f','frozen_schedule_hash':'s'})
    root=tmp_path;runtime=root/'runtime';workspace=root/'private'
    names=['work/cache/fine/status.json','work/cache/fine/mesh.npz','work/cache/fine/chunk_000.npz',
        'work/validation/q23_2d_endpoint_radial.npz','work/validation/q23_2d_endpoint_radial.json',
        'work/validation/judge_2d/q23/radial.json']
    for name in names:
        path=workspace/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fake evidence')
    job=dict(key='D.2d.q23.radial',kind='twod_radial',validation_kind='twod_radial',artifact='validation.2d.q23.radial',layer='D',requires=[])
    Pipeline_Merge(root,runtime,job,workspace,dict(result=dict(status='MEASURED',fine_id='fine')))
    entry=contract.Artifact_Require(root,[job['artifact']])[job['artifact']]
    hydrated=root/'assess';contract.Artifact_Hydrate(root,hydrated,{job['artifact']:entry})
    assert all((hydrated/name).read_bytes()==b'fake evidence' for name in names)
    (runtime/'work/cache/fine/chunk_000.npz').unlink()
    assert not contract.Artifact_Verify(root,job['artifact'])['complete']
    with pytest.raises(RuntimeError,match='VALIDATION_PREREQUISITE_MISSING'):
        Validation_Execute(hydrated,dict(dataset_root=root,requires=[job['artifact']],artifact='validation.2d.assess',validation_kind='twod_assess'))
