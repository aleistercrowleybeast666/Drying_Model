"""Regression checks for question boundaries, cache-only output and real geometry."""
import json
import numpy as np
import pytest
from drying.outputs import Output_GetEnd, Output_PrepareFolders, Output_UpdateStatus
from drying.comparison import Comparison_WriteQuestions
from drying.plots import Plot_MirrorSection
from drying.animations import Animation_MapRadial, Animation_GetProgress
from drying.diagnostics import Diagnostics_RecordException
from drying.storage import Storage_WriteJson, Storage_HashFiles


def test_question_windows_and_not_dry_endpoint():
    status = dict(cap=259200., event=dict(report_s=208488.96))
    assert [Output_GetEnd(q, status) for q in range(1, 5)] == [1800, 10800, 208488.96, 208488.96]
    assert Output_GetEnd(4, dict(cap=259200., event=None)) == 259200


def test_q23_comparison_splits_peak_times_without_solver(tmp_path, monkeypatch):
    import drying.comparison as comparison
    import drying.cases as cases
    def Solver_RejectCall(*args, **kwargs):
        raise AssertionError('Presentation invoked a PDE solve')
    monkeypatch.setattr(cases, 'Case_Solve', Solver_RejectCall)
    monkeypatch.setattr(cases, 'Rk4_Advance', Solver_RejectCall)
    Output_PrepareFolders(tmp_path)
    data = np.zeros((5, 18))
    data[:, 0] = [0, 10800, 12000, 18000.24, 20000]
    data[:, 2] = [0, 1, 3, 2, 99]
    data[:, 10] = [0, 2, 4, 3, 99]
    path = tmp_path/'work/comparison/q23_pointwise.csv'
    np.savetxt(path, data, delimiter=',', header=','.join(['time_s']+[f'v{i}' for i in range(17)]), comments='')
    Storage_WriteJson(tmp_path/'work/comparison/case_summary.json', {'q23': dict(one_id='one', two_id='two')})
    monkeypatch.setattr(comparison, 'Case_ReadStatus', lambda *_: dict(cap=259200, event=dict(report_s=18000.24)))
    summary = Comparison_WriteQuestions(tmp_path, 'q23')
    assert summary['q2']['max_abs_moisture']['time_s'] == 10800
    assert summary['q3']['max_abs_moisture']['time_s'] == 12000
    assert summary['q3']['max_abs_moisture']['value'] == 4
    assert summary['q2']['time_range_s'] == [0, 10800]
    assert summary['q3']['time_range_s'] == [0, 18000.24]
    assert not (tmp_path/'results/q23').exists()
    # Missing the precise drying endpoint must be explicit, never silently truncated.
    data[3, 0] = 18000
    np.savetxt(path, data, delimiter=',', header=','.join(['time_s']+[f'v{i}' for i in range(17)]), comments='')
    with pytest.raises(RuntimeError, match='paired endpoint'):
        Comparison_WriteQuestions(tmp_path, 'q23')


def test_full_section_keeps_actual_axial_variation():
    r, z = np.array([0, .01, .02]), np.array([0, .1, .125])
    values = np.arange(18).reshape(2, 3, 3)
    rr, zz, full = Plot_MirrorSection(r, z, values)
    assert full.shape == (2, 5, 5)
    np.testing.assert_array_equal(full[:, 2:, 2:], values)
    np.testing.assert_array_equal(full[:, ::-1, :], full)
    np.testing.assert_array_equal(full[:, :, ::-1], full)
    assert rr[0] == -.02 and zz[-1] == .125
    assert not np.array_equal(full[:, :, 0], full[:, :, 2])


def test_circular_section_shrinks_in_fixed_physical_coordinates():
    coordinates = np.linspace(-.02, .02, 81)
    large = Animation_MapRadial([0, .02], [2, 0], coordinates)
    small = Animation_MapRadial([0, .012], [2, 0], coordinates)
    assert small.count() < large.count()*.4
    assert small[40, 40] == 2
    assert small.mask[40, 70] and not large.mask[40, 70]
    np.testing.assert_allclose(small, small.T)
    progress = Animation_GetProgress(240)
    assert progress[0] == 0 and progress[-1] == 1 and np.all(np.diff(progress) > 0)


def test_numerical_failure_keeps_traceback_and_properties(tmp_path):
    fields = dict(case_id='q4', dimension=2, simulated_time_s=30, dt_s=.25, rk_stage=3,
                  cell_index=[4, 2], r_m=.01, z_m=.1, T_K=310, C=.3, D=1e-9,
                  rho=600, cp=2000, k=.2, R_m=.018)
    try:
        raise RuntimeError('test numerical failure')
    except RuntimeError as error:
        Diagnostics_RecordException(tmp_path, 'NUMERICAL_FAILURE', error, **fields)
    records = [json.loads((tmp_path/path).read_text(encoding='utf-8'))
               for path in ['logs/events.jsonl', 'work/diagnostics/failures.jsonl']]
    assert records[0] == records[1]
    assert 'Traceback' in records[0]['traceback']
    assert all(records[0][key] == value for key, value in fields.items())


def test_status_separates_official_location_from_validation(tmp_path, monkeypatch):
    import drying.outputs as outputs
    Output_PrepareFolders(tmp_path)
    status = dict(cap=259200., complete=True, event=None, drying_time_h=None, fingerprint='fp')
    monkeypatch.setattr(outputs, 'Case_ReadStatus', lambda *_: status)
    monkeypatch.setattr(outputs, 'Output_GetEndpoint', lambda *_: {})
    validation, exports = {}, []
    for q, case in [(1, 'q1'), (2, 'q23'), (3, 'q23'), (4, 'q4')]:
        case_id = outputs.Output_GetSelected(tmp_path, case, 1)
        Storage_WriteJson(tmp_path/'work/cache'/case_id/'status.json', status)
        validation[case+'_1d'] = dict(time_passed=True, time_full_time=True, spatial_quantified=True, spatial_passed=False)
        (tmp_path/f'results/tables/result{q}.xlsx').touch()
        exports.append(dict(question=q, fingerprint='fp', dimension=1,
                            workbook_hash=Storage_HashFiles([tmp_path/f'results/tables/result{q}.xlsx'])))
    Storage_WriteJson(tmp_path/'work/validation/summary.json', validation)
    Storage_WriteJson(tmp_path/'work/diagnostics/export_manifest.json', dict(outputs=exports))
    Output_UpdateStatus(tmp_path)
    result = json.loads((tmp_path/'results/status.json').read_text(encoding='utf-8'))
    assert result['official_output_generated'] and result['time_convergence_passed']
    assert not result['spatial_convergence_passed'] and not result['drying_completed']
    assert result['questions']['q4']['drying_time'] is None
    assert result['questions']['q4']['drying_note'] == 'NOT_DRY_WITHIN_72H'
    assert {p.name for p in (tmp_path/'results').iterdir()} == {'q1', 'q2', 'q3', 'q4', 'tables', 'status.json'}


@pytest.mark.parametrize('passed',[True,False])
def test_overview_official_rows_follow_status_instead_of_old_evidence(passed):
    from drying.overview import Overview_Render
    questions={}
    for q,case in [(1,'q1'),(2,'q23'),(3,'q23'),(4,'q4')]:
        questions[f'q{q}']=dict(source_case=case,one_id=case+'_current_stage',
            solver_completed=True,time_convergence_passed=True,spatial_convergence_passed=passed,
            stage_schedule_enabled=True,stage_schedule_passed=passed,stage_schedule_spatial_passed=passed,
            fixed_grid_spatial_passed=False,execution_mode='stage_schedule',drying_time=7200 if q>2 else None,
            stage_dt_statistics=[dict(t_start=0,t_end=7200,nr=200)])
    data=dict(generated_at='now',input_hash='input',source_hash='source',
        config=dict(numerics=dict(dt_s=.25),validation=dict(spatial=dict(temperature_abs_K=.01,moisture_abs=.01,drying_time_relative=.002))),
        status=dict(questions=questions),validation={case+'_1d':dict(spatial_passed=not passed) for case in ['q1','q23','q4']},
        sources={case+'_1d':dict(case_id='old_fixed',execution_mode='fixed',complete=False) for case in ['q1','q23','q4']},comparison={})
    text=Overview_Render(data); flag='PASS' if passed else 'FAIL'
    for q in range(1,5):
        assert f'| Q{q} | PASS/PASS/{flag}/{flag} |' in text
        assert f'| Q{q} | FAIL | {flag} | {flag} |' in text
    assert 'legacy / diagnostic only' in text
    assert 'old_fixed' not in text
    assert ('SPATIAL_CONVERGENCE_FAILED' in text)==(not passed)
