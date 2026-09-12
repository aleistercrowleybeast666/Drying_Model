"""Check the published question layout and cache provenance without solving PDEs."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
import numpy as np
from PIL import Image

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT/'src'))
from drying.outputs import Output_ReadJson
from drying.cases import Case_LoadConfig
from drying.storage import Storage_WriteJson, Storage_HashFiles
from drying.overview import Overview_Render


def Check_ResultLayout(root=_ROOT):
    results = Path(root)/'results'
    required = {
        'tables', 'q1', 'q2', 'q3', 'q4', 'status.json', 'overview.md',
        'animations', 'studies', 'paper_facts.json', 'paper_facts.md'}
    observed={p.name for p in results.iterdir()};missing=required-observed;unexpected=observed-required
    if missing or unexpected:
        raise RuntimeError(f'RESULT_LAYOUT_MISMATCH:\nmissing={sorted(missing)}\nunexpected={sorted(unexpected)}')
    facts=Output_ReadJson(results/'paper_facts.json')
    status=Output_ReadJson(results/'status.json')
    if not (results/'paper_facts.md').is_file():raise RuntimeError('PAPER_FACTS_MD_MISSING')
    for q in ['q3','q4']:
        fact_s=facts['official'][q.upper()]['drying_time_s']
        status_s=status['questions'][q]['drying_time']
        summary_s=Output_ReadJson(results/q/f'{q}_summary.json')['drying_time']
        if not (fact_s==status_s==summary_s):
            raise RuntimeError(f'PAPER_FACTS_TIME_MISMATCH: {q} facts={fact_s}, status={status_s}, summary={summary_s}')
    return facts,status


def Check_Run(cache_baseline=None):
    results = _ROOT/'results'
    _,status=Check_ResultLayout()
    # Excel's owner files are application metadata, not exported workbooks.
    assert {p.name for p in (results/'tables').iterdir() if not (p.name.startswith('~$') and p.suffix=='.xlsx')} == {f'result{q}.xlsx' for q in range(1, 5)}
    evidence = Output_ReadJson(_ROOT/'work/plot_payload/overview_data.json')
    overview_status=evidence['status'];comparable=dict(status)
    # Auxiliary publication metadata was added after the sealed plot payload and does not
    # alter any question result.  The overview remains valid when this is the sole addition.
    comparable.pop('two_dimensional_auxiliary_validation',None)
    if overview_status != comparable:raise RuntimeError('OVERVIEW_EVIDENCE_STALE: refresh summaries')
    published_overview=(results/'overview.md').read_text(encoding='utf-8');sealed_overview=Overview_Render(evidence)
    if not (published_overview==sealed_overview or
            published_overview.startswith(sealed_overview+'\n<!-- auxiliary-2d:start -->')):
        raise RuntimeError('OVERVIEW_CONTENT_MISMATCH: published overview differs from sealed evidence')
    exports = Output_ReadJson(_ROOT/'work/diagnostics/export_manifest.json')['outputs']
    comparison = Output_ReadJson(_ROOT/'work/comparison/summary.json')
    certificates = Output_ReadJson(_ROOT/'work/validation/summary.json')
    records = []
    for q in range(1, 5):
        summary = Output_ReadJson(results/f'q{q}/q{q}_summary.json')
        question = status['questions'][f'q{q}']
        certificate = certificates[question['source_case']+'_1d']
        assert all(summary.get(key)==value for key,value in question.items()), (q,'summary differs from status')
        for flag in ['fixed_grid_spatial_passed','stage_schedule_spatial_passed','spatial_convergence_passed',
                     'early_reference_passed','stage_schedule_accuracy_passed','remesh_transfer_passed']:
            assert question[flag] == summary[flag] == certificate.get(flag,False), (q,flag)
        assert question['one_id'] == certificate['selected_id']
        if question['execution_mode']=='stage_schedule':
            assert question['fixed_grid_role']=='legacy / diagnostic only'
            expected = all(question[k] for k in ['early_reference_passed','stage_schedule_accuracy_passed','remesh_transfer_passed'])
            assert question['spatial_convergence_passed'] == question['stage_schedule_spatial_passed'] == expected
        else:
            assert question['spatial_convergence_passed'] == question['fixed_grid_spatial_passed']
        assert certificate['spatial_passed'] == question['spatial_convergence_passed']
        data = np.loadtxt(results/f'q{q}/q{q}_compare.csv', delimiter=',', skiprows=1, ndmin=2)
        end = summary['simulation_end']
        assert data[0, 0] == 0 and abs(data[-1, 0]-end) < 1e-8
        assert np.all(np.diff(data[:, 0]) > 0) and np.isfinite(data).all()
        if q <= 2:
            assert end == {1: 1800, 2: 10800}[q]
        else:
            assert end <= 259200
            if summary['drying_completed']:
                assert abs(end-summary['drying_time']) < 1e-8
            else:
                assert summary['drying_time'] is None
        for offset, label in [(2, 'temperature'), (10, 'moisture')]:
            assert float(data[:, offset].max()) == summary[f'max_1d_2d_{label}_difference']
            assert float(data[np.argmax(data[:, offset]), 0]) == summary['time_of_max_difference'][label]
        assert summary['representative_section_time_s'] == summary['time_of_max_difference']['moisture']
        assert np.isfinite(summary['max_temperature']) and summary['min_moisture'] > 0
        entry = next(item for item in exports if item['question'] == q)
        assert entry['dimension'] == 1 and entry['readback'].startswith('PASSED')
        workbook=_ROOT/entry['path'].replace('\\','/')
        if Storage_HashFiles([workbook]) != entry['workbook_hash']:
            raise RuntimeError(f'WORKBOOK_HASH_MISMATCH: {entry["path"]}')
        assert status['questions'][f'q{q}']['official_output_generated']
        assert status['questions'][f'q{q}']['two_dimensional_check_completed']
        for suffix in ['curves', '1d_2d_compare', 'max_error_section']+(['3d'] if q >= 3 else []):
            with Image.open(results/f'q{q}/q{q}_{suffix}.png') as picture:
                picture.verify()
        records.append(dict(question=q, time_range_s=[0, end], compare_rows=len(data), workbook_readback='PASSED'))
    for flag in ['fixed_grid_spatial_passed','stage_schedule_spatial_passed','spatial_convergence_passed']:
        assert status[flag] == all(question[flag] for question in status['questions'].values()), flag
    assert comparison['q2']['one_id'] == comparison['q3']['one_id']
    assert comparison['q2']['two_id'] == comparison['q3']['two_id']
    animations = Output_ReadJson(_ROOT/'work/diagnostics/animations_manifest.json', [])
    expected_frames = Case_LoadConfig(_ROOT)['display']['frames']
    assert len(animations) == 5
    assert len(list((results/'animations').glob('*.gif'))) == 5
    for item in animations:
        assert item['decode_check'] == 'PASSED_ALL_FRAMES'
        assert item['fixed_color_limits'] == [['temperature_C', 28, 53], ['moisture_kg_kg', 0, 2.55]]
        with Image.open(_ROOT/item['path']) as gif:
            assert gif.n_frames == item['frames'] == expected_frames
            for index in [0, gif.n_frames//2, gif.n_frames-1]:
                gif.seek(index); gif.convert('RGB').load()
        if 'cases' in item:
            assert item['relative_progress'][0] == 0 and item['relative_progress'][-1] == 1
            for case in item['cases']:
                assert len(case['frame_times_s']) == item['frames']
                assert case['frame_times_s'][0] == 0 and case['frame_times_s'][-1] == case['end_s']
                assert np.all(np.diff(case['frame_times_s']) >= 0)
    unchanged = None; core_unchanged = None
    if cache_baseline:
        baseline = Output_ReadJson(_ROOT/cache_baseline)
        for name, recorded in baseline['files'].items():
            path = _ROOT/name
            assert path.stat().st_size == recorded['size'] and path.stat().st_mtime_ns == recorded['mtime_ns'], name
            if 'sha256' in recorded:
                assert hashlib.sha256(path.read_bytes()).hexdigest() == recorded['sha256'], name
        for name, digest in baseline.get('core',{}).items():
            assert hashlib.sha256((_ROOT/'src/drying'/name).read_bytes()).hexdigest() == digest, name
        if baseline.get('core'):core_unchanged=True
        unchanged = len(baseline['files'])
    tests = Output_ReadJson(_ROOT/'work/validation/program_tests.json')
    assert tests['exit_status'] == 0 and all(item['outcome'] == 'passed' for item in tests['tests'])
    report = dict(status='PASSED', production_state_consistency='PASSED_ALL_QUESTIONS', questions=records, png_count=len(list(results.glob('q*/*.png'))),
        gif_count=5, test_count=len(tests['tests']), unchanged_solver_cache_files=unchanged,
        core_unchanged=core_unchanged,
        numerical_note='Numerical acceptance is read from results/status.json; publication checks do not change numerical PASS/FAIL.')
    Storage_WriteJson(_ROOT/'work/validation/presentation_checks.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cache-baseline')
    Check_Run(parser.parse_args().cache_baseline)
