"""Unified entry point. All commands use this project's isolated Python environment."""
import argparse
import csv
import importlib.metadata
import json
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT/'src'))
from drying.diagnostics import Diagnostics_Open, Diagnostics_RecordException
from drying.storage import Storage_WriteJson


def Run_Main():
    parser = argparse.ArgumentParser(description='A题圆柱药材烘干数值求解')
    parser.add_argument('command', choices=['prepare', 'test', 'solve', 'validate', 'compare', 'export', 'plots', 'animate', 'all'])
    parser.add_argument('--source', default=str(_ROOT/'data/raw'))
    parser.add_argument('--case', choices=['q1', 'q23', 'q4', 'all'], default='all')
    parser.add_argument('--dim', choices=[1, 2], type=int, default=1)
    parser.add_argument('--nr', type=int)
    parser.add_argument('--nz', type=int)
    parser.add_argument('--dt', type=float)
    parser.add_argument('--cap', type=float)
    parser.add_argument('--tag', default='')
    parser.add_argument('--scope', choices=['1d', '2d', 'all'], default='all')
    args = parser.parse_args()
    for directory in ['cache','candidate','final','partial','tables','comparison','validation','figures','animations']:
        (_ROOT/'results'/directory).mkdir(parents=True,exist_ok=True)
    Diagnostics_Open(_ROOT)
    commands = ['prepare', 'test', 'solve1', 'validate1', 'solve2', 'validate2', 'compare', 'export', 'plots', 'animate'] if args.command == 'all' else [args.command]
    exit_code = 0
    for command in commands:
        try:
            if command == 'prepare':
                from drying.inputs import Input_Prepare
                source_path=Path(args.source).resolve()
                raw_path=(_ROOT/'data/raw').resolve()
                if source_path.is_dir() and source_path!=raw_path and raw_path.is_relative_to(source_path):
                    raise ValueError('INPUT_SCHEMA_ERROR: choose the A题 source folder or ZIP, not a parent of data/raw')
                manifest = Input_Prepare(_ROOT, args.source)
                print(json.dumps(manifest, ensure_ascii=False, indent=2))
                versions = {p: importlib.metadata.version(p) for p in ['numpy', 'scipy', 'numba', 'matplotlib', 'openpyxl', 'pillow', 'imageio', 'pytest', 'pypdf', 'psutil']}
                Storage_WriteJson(_ROOT/'results/dependencies.json', dict(python=sys.version, packages=versions))
            elif command == 'test':
                result = subprocess.run([sys.executable, '-m', 'pytest', str(_ROOT/'tests'), '-q'], cwd=_ROOT)
                if result.returncode:
                    raise RuntimeError('NUMERICAL_VALIDATION_FAILED: program tests')
            elif command in ('solve', 'solve1', 'solve2'):
                from drying.cases import Case_Solve
                dimension = int(command[-1]) if command[-1].isdigit() else args.dim
                cases = ['q1', 'q23', 'q4'] if args.case == 'all' else [args.case]
                for case in cases:
                    try:
                        Case_Solve(_ROOT, case, dimension, args.nr, args.nz, args.dt, args.tag, args.cap)
                    except Exception as error:
                        Diagnostics_RecordException(_ROOT, 'CASE_FAILED', error, case_id=case, dimension=dimension)
                        exit_code=1
                if dimension==2 and args.case=='all' and not args.tag and args.cap is None:
                    from drying.cases import Case_SolvePairEvents
                    Case_SolvePairEvents(_ROOT)
            elif command.startswith('validate'):
                from drying.validation import Validation_Run
                scope = command[-1]+'d' if command[-1].isdigit() else args.scope
                for case in (['q1','q23','q4'] if args.case=='all' else [args.case]):
                    try:
                        Validation_Run(_ROOT, scope, case)
                    except Exception as error:
                        Diagnostics_RecordException(_ROOT,'NUMERICAL_VALIDATION_FAILED',error,case_id=case,scope=scope)
                        exit_code=1
            elif command == 'compare':
                from drying.comparison import Comparison_Run
                Comparison_Run(_ROOT, args.case)
            elif command == 'export':
                from drying.export import Export_Run
                for case in (['q1','q23','q4'] if args.case=='all' else [args.case]):
                    try:
                        Export_Run(_ROOT,case)
                    except Exception as error:
                        Diagnostics_RecordException(_ROOT,'EXPORT_FAILED',error,case_id=case)
                        exit_code=1
            elif command == 'plots':
                from drying.plots import Plot_Run
                Plot_Run(_ROOT)
            elif command == 'animate':
                from drying.animations import Animation_Run
                Animation_Run(_ROOT, args.case)
        except Exception as error:
            Diagnostics_RecordException(_ROOT, str(error).split(':')[0] if ':' in str(error) else 'COMMAND_FAILED', error, command=command)
            exit_code = 1
            if command in ('prepare', 'test'):
                break
        finally:
            Run_UpdateStatus()
    return exit_code


def Run_UpdateStatus():
    cases = []
    for path in sorted((_ROOT/'results/cache').glob('*/status.json')):
        cases.append(json.loads(path.read_text(encoding='utf-8')))
    validation_path=_ROOT/'results/validation/summary.json'
    validation=json.loads(validation_path.read_text(encoding='utf-8')) if validation_path.exists() else {}
    comparison_path=_ROOT/'results/comparison/summary.json'
    comparison=json.loads(comparison_path.read_text(encoding='utf-8')) if comparison_path.exists() else {}
    for case in cases:
        for entry in validation.values():
            if entry['selected_id']==case['case_id']:
                case['validation']=entry['numerical_status']
                case['time_validation_passed']=entry['time_passed']
                case['spatial_accepted']=entry['spatial_passed']
    Storage_WriteJson(_ROOT/'results/status.json', dict(cases=cases,numerical_validation=validation,
        dimension_comparison=comparison,final_source='1D only',
        note='COMPUTED/DRY are integration statuses; spatial accuracy is not certified, official-format workbooks remain candidates'))
    diagnostics_path = _ROOT/'results/diagnostics.csv'
    with diagnostics_path.open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.writer(stream)
        writer.writerow(['case_id','time_s','Cmax_kg_kg','r_m','z_m','R_m','rho','cp','k','D'])
        for case in cases:
            for row in case.get('diagnostics', []):
                writer.writerow([case['case_id']]+[row[k] for k in ['time_s','Cmax','r_m','z_m','R_m','rho','cp','k','D']])
    Storage_WriteJson(_ROOT/'results/resource_usage.json',dict(
        completed_case_count=sum(bool(c.get('complete')) for c in cases),
        summed_solver_wall_s=sum(c.get('wall_s',0.) for c in cases),
        maximum_recorded_solver_rss_bytes=max((c.get('peak_rss_bytes',0) for c in cases),default=0),
        cases=[dict(case_id=c['case_id'],wall_s=c.get('wall_s'),
                    compile_or_cache_load_s=c.get('compile_or_load_s'),
                    sampled_peak_rss_bytes=c.get('peak_rss_bytes'),steps=c.get('steps'),
                    simulated_seconds_per_wall_second=c.get('simulated_time_s',0)/c['wall_s'] if c.get('wall_s') else None)
               for c in cases],
        note='Wall times measured locally; memory sampled at checkpoints, not a guaranteed OS peak; summed times may overlap with lightweight tasks'))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(Run_Main())
