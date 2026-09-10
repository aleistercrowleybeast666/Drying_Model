"""Question-specific presentation metadata; never advances a PDE state."""
import json
from pathlib import Path
from .cases import Case_GetId, Case_ReadStatus
from .storage import Storage_WriteJson, Storage_HashFiles


def Output_ReadJson(path, default=None):
    path = Path(path)
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else ({} if default is None else default)


def Output_PrepareFolders(root):
    for directory in ['results/tables', *[f'results/q{q}' for q in range(1, 5)],
                      *[f'work/{name}' for name in ['cache', 'checkpoints', 'validation', 'comparison', 'diagnostics']]]:
        (Path(root)/directory).mkdir(parents=True, exist_ok=True)


def Output_GetSelected(root, case, dimension):
    validation = Output_ReadJson(Path(root)/'work/validation/summary.json')
    return validation.get(f'{case}_{dimension}d', {}).get('selected_id', Case_GetId(case, dimension))


def Output_GetEnd(question, status):
    if question <= 2:
        return float({1: 1800, 2: 10800}[question])
    return float(status['event']['report_s'] if status.get('event') else status['cap'])


def Output_UpdateSummary(root, question, **values):
    path = Path(root)/f'results/q{question}/q{question}_summary.json'
    summary = Output_ReadJson(path)
    summary.update(values)
    Storage_WriteJson(path, summary)


def Output_UpdateStatus(root):
    root = Path(root)
    validation = Output_ReadJson(root/'work/validation/summary.json')
    comparison = Output_ReadJson(root/'work/comparison/summary.json')
    manifest = Output_ReadJson(root/'work/diagnostics/export_manifest.json')
    questions = {}
    for q, case in [(1, 'q1'), (2, 'q23'), (3, 'q23'), (4, 'q4')]:
        case_id = Output_GetSelected(root, case, 1)
        if not (root/'work/cache'/case_id/'status.json').exists():
            continue
        status = Case_ReadStatus(root, case_id)
        end = Output_GetEnd(q, status)
        entry = validation.get(f'{case}_1d', {})
        check = comparison.get(f'q{q}', {})
        export = next((item for item in manifest.get('outputs', []) if item['question'] == q), {})
        table = root/f'results/tables/result{q}.xlsx'
        generated = (export.get('fingerprint') == status['fingerprint'] and
                     export.get('dimension') == 1 and table.exists() and
                     export.get('workbook_hash') == Storage_HashFiles([table]))
        dry = bool(status.get('event') and status['event']['report_s'] <= end + 1e-8)
        time_passed = bool(entry.get('time_passed') and entry.get('time_full_time'))
        space_passed = bool(entry.get('spatial_passed') and entry.get('spatial_full_time'))
        two_id = Output_GetSelected(root, case, 2)
        two_path = root/'work/cache'/two_id/'status.json'
        two_status = Case_ReadStatus(root, two_id) if two_path.exists() else {}
        completed = bool(check.get('comparison_completed') and check.get('one_id') == case_id and
                         check.get('one_fingerprint') == status['fingerprint'] and
                         check.get('two_id') == two_id and two_status.get('complete') and
                         check.get('two_fingerprint') == two_status.get('fingerprint') and
                         check.get('time_range_s') == [0., end] and
                         (root/f'results/q{q}/q{q}_compare.csv').exists())
        record = dict(source_case=case, official_source='1D', one_id=case_id,
            simulation_end=end, drying_time=status['drying_time_h']*3600 if dry else None,
            drying_completed=dry, time_convergence_passed=time_passed,
            spatial_convergence_passed=space_passed, two_dimensional_check_completed=completed,
            official_output_generated=generated, table=f'results/tables/result{q}.xlsx',
            summary=f'results/q{q}/q{q}_summary.json', time_unit='s',
            time_convergence_status='PASSED' if time_passed else 'PENDING_OR_INCOMPLETE',
            space_convergence_status='PASSED' if space_passed else
                ('QUANTIFIED_NOT_CERTIFIED' if entry.get('spatial_quantified') else 'PENDING'),
            drying_note=('DRY' if dry else 'NOT_DRY_WITHIN_72H' if q >= 3 and end >= 259200 else
                         'FIXED_TIME_WINDOW' if q <= 2 else 'INCOMPLETE_TIME_RANGE'))
        Output_UpdateSummary(root, q, **record)
        questions[f'q{q}'] = record
    Storage_WriteJson(root/'results/status.json', dict(questions=questions,
        time_convergence_passed=len(questions) == 4 and all(v['time_convergence_passed'] for v in questions.values()),
        spatial_convergence_passed=len(questions) == 4 and all(v['spatial_convergence_passed'] for v in questions.values()),
        two_dimensional_check_completed=len(questions) == 4 and all(v['two_dimensional_check_completed'] for v in questions.values()),
        drying_completed=all(questions.get(q, {}).get('drying_completed', False) for q in ['q3', 'q4']),
        official_output_generated=len(questions) == 4 and all(v['official_output_generated'] for v in questions.values()),
        validation_details='work/validation/summary.json', comparison_details='work/comparison/summary.json',
        solver_details='work/cache', diagnostics='work/diagnostics',
        note='Validation flags describe the stored evidence. 2D comparison completion does not certify spatial convergence.'))
