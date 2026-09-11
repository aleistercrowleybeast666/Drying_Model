import json
import shutil
from pathlib import Path
import numpy as np
import pytest
from drying.stages import Stage_NormalizeSchedule, Stage_ProjectState, Stage_Solve
from drying.cases import Case_IterFields, Case_LoadMesh
from drying.validation import Validation_CompareCaches


def test_stage_schedule_rejects_gaps_and_incomplete_coverage():
    good = [dict(t_start=0,t_end=3,nr=8,nz=1),dict(t_start=3,t_end=None,nr=4,nz=1)]
    assert Stage_NormalizeSchedule(good,10)[-1]['t_end'] == 10
    with pytest.raises(ValueError,match='contiguously'):
        Stage_NormalizeSchedule([good[0],dict(good[1],t_start=4)],10)
    with pytest.raises(ValueError,match='does not reach'):
        Stage_NormalizeSchedule(good[:1],10)


def test_stage_transfer_is_positive_volume_conservative_and_reports_lost_variation():
    old = (np.array([0.,.05,.15,.35,.6,1.]),np.array([0.,1.]))
    new = (np.array([0.,.15,.6,1.]),np.array([0.,1.]))
    state = np.array([[301,302,304,307,313],[2.5,2.4,2.1,1.2,.3]])[:,:,None]
    transferred,metrics = Stage_ProjectState(state,old,new,3600)
    assert transferred.shape == (2,3,1)
    assert metrics['projection_max_abs_C'] > 0
    assert metrics['volume_integral_relative_error_C'] < 1e-14
    assert metrics['volume_integral_relative_error_T'] < 1e-14
    assert state[0].min() <= transferred[0].min() <= transferred[0].max() <= state[0].max()
    assert np.all(transferred[1] > 0)
    constant,metrics = Stage_ProjectState(np.ones_like(state),old,new,3600)
    np.testing.assert_allclose(constant,1.)
    assert metrics['projection_max_abs_T'] < 1e-14


def test_real_stage_trajectory_switch_restart_and_half_partition(tmp_path):
    root = Path(__file__).resolve().parents[1]
    for folder in ['src/drying','data','configs']:
        (tmp_path/folder).mkdir(parents=True,exist_ok=True)
    for p in (root/'src/drying').glob('*.py'):
        shutil.copy2(p,tmp_path/'src/drying'/p.name)
    for name in ['inputs.npz','input_manifest.json']:
        shutil.copy2(root/'data'/name,tmp_path/'data'/name)
    text = (root/'configs/default.toml').read_text(encoding='utf-8').replace('mode = "adaptive"','mode = "uniform"')
    (tmp_path/'configs/default.toml').write_text(text,encoding='utf-8')
    schedule = [dict(t_start=0.,t_end=3.,nr=8,nz=1),dict(t_start=3.,t_end=7.,nr=4,nz=1)]
    base = Stage_Solve(tmp_path,'q1',schedule)
    rows = list(Case_IterFields(tmp_path,base['case_id']))
    assert [t for t,_ in rows] == list(range(8))
    assert rows[2][1].shape == (2,8,1) and rows[3][1].shape == (2,4,1)
    assert len(Case_LoadMesh(tmp_path,base['case_id'],3)[0]) == 5
    assert len(base['transfers']) == 1 and len(base['stage_dt_statistics']) == 2
    again = Stage_Solve(tmp_path,'q1',schedule)
    assert again['fingerprint'] == base['fingerprint']
    half = Stage_Solve(tmp_path,'q1',schedule,dt=.125,replay_id=base['case_id'],label='half_steps')
    value,_ = Validation_CompareCaches(tmp_path,base['case_id'],half['case_id'])
    assert value['reference_complete'] and value['official_temperature']['value'] < 1e-6
