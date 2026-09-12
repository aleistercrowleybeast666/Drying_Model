"""Serial final technical studies; separate identities and no second PDE solver."""
from enum import IntEnum
from pathlib import Path
import traceback
from ..storage import Storage_WriteJson
from .baseline import Baseline_Check, Baseline_ReadJson
from .cache import Cache_SealExperiment
from .cross_spec import Cross_GetPlan
from .trajectory import Trajectory_Solve


class TechnicalRunResult(IntEnum):
    COMPLETE = 0
    STOPPED = 1
    FAILED = 2


def Technical_Run(root, args):
    root = Path(root)
    Baseline_Check(root)
    folder = root / 'work/studies/technical'
    folder.mkdir(parents=True, exist_ok=True)
    index_path = folder / 'index.json'
    index = Baseline_ReadJson(index_path) if index_path.exists() else dict(schema_version=1, experiments={})
    if args.group == 'refine2d':
        from .refinement2d import Refinement_Run
        return Refinement_Run(root, args)
    specs = Cross_GetPlan(root)
    if args.dry_run:
        for spec in specs:
            path = root / 'work/studies/experiments' / spec['experiment_id'] / 'status.json'
            saved = Baseline_ReadJson(path) if path.exists() else {}
            print(spec['experiment_id'], 'CACHE_READY' if saved.get('complete') else 'COMPUTE_REQUIRED', flush=True)
        return TechnicalRunResult.COMPLETE
    if not args.payload_only:
        for spec in specs:
            if (root / 'work/studies/STOP').exists():
                return TechnicalRunResult.STOPPED
            key = spec['experiment_id']
            path = root / 'work/studies/experiments' / key / 'status.json'
            print('TECHNICAL_START ' + key, flush=True)
            try:
                if spec['replay'] and not index['experiments'].get(spec['replay'], {}).get('complete'):
                    raise RuntimeError('STUDY_REFERENCE_INCOMPLETE: own production replay is required')
                result = Baseline_ReadJson(path) if path.exists() else {}
                if result.get('complete'):
                    result = Cache_SealExperiment(root, spec, result)
                else:
                    if result and not args.resume:
                        raise RuntimeError('STUDY_RESUME_REQUIRED: use --resume')
                    result = Trajectory_Solve(root, spec, resume=args.resume)
                    if result.get('complete'):
                        result = Cache_SealExperiment(root, spec, result)
                index['experiments'][key] = result
                Storage_WriteJson(index_path, index)
                if result.get('status') == 'STOPPED':
                    return TechnicalRunResult.STOPPED
            except Exception as exc:
                index['experiments'][key] = dict(complete=False, status='FAILED', error=str(exc), traceback=traceback.format_exc())
                Storage_WriteJson(index_path, index)
                print('TECHNICAL_FAILED ' + key + ': ' + str(exc), flush=True)
    if args.solve_only:
        Baseline_Check(root)
        return TechnicalRunResult.COMPLETE if all(index['experiments'].get(s['experiment_id'], {}).get('complete') for s in specs) else TechnicalRunResult.FAILED
    from .technical_analysis import Technical_Summarize
    summary=Technical_Summarize(root, index)
    Baseline_Check(root)
    return TechnicalRunResult.COMPLETE if summary['status']=='PASS' else TechnicalRunResult.FAILED
