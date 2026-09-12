"""Lightweight numeric comparison, never a convergence certificate."""
import json
from pathlib import Path

import numpy as np

from .frozen_mesh import Frozen_HashFile
from .storage import Storage_WriteJson


def Table_SealProduction(root, case, status):
    """Seal immutable source arrays independently of optional later diagnostics."""
    root=Path(root)
    path=root/f'work/recompute/table_cache_{case}.json'
    if path.exists():
        prior=json.loads(path.read_text(encoding='utf-8'))
        if prior['fingerprint']==status['fingerprint']:
            for name,digest in prior['files'].items():
                if not (root/name).is_file() or Frozen_HashFile(root/name)!=digest:
                    raise RuntimeError('TABLE_CACHE_MISMATCH: '+name)
            return prior
    files={}
    for case_id in [status['case_id']]+[s['case_id'] for s in status['stages']]:
        folder=root/'work/cache'/case_id
        paths=[folder/'status.json',folder/'mesh.npz',*sorted(folder.glob('chunk_*.npz'))]
        if (folder/'event.npz').exists():paths.append(folder/'event.npz')
        for source in paths:
            files[source.relative_to(root).as_posix()]=Frozen_HashFile(source)
    record=dict(fingerprint=status['fingerprint'],source_case_id=status['case_id'],files=files)
    Storage_WriteJson(path,record)
    return record


def Table_CheckReference(root, case, status):
    root = Path(root)
    reference = json.loads((root/'configs/table_reference/manifest.json').read_text(encoding='utf-8'))
    rows = []
    for q in dict(q1=[1], q23=[2, 3], q4=[4])[case]:
        expected = reference['questions'][str(q)]
        source = root/'configs/table_reference'/expected['file']
        if Frozen_HashFile(source) != expected['sha256']:
            raise RuntimeError('TABLE_REFERENCE_RESOURCE_CORRUPT: '+str(q))
        errors = {}
        with np.load(source) as prior, np.load(root/f'work/cache/exports/result{q}_full_precision.npz') as current:
            for name in ['time_s', 'temperature_C', 'moisture', 'R_m', 'surface_C']:
                a, b = prior[name], current[name]
                if a.shape != b.shape or not np.array_equal(np.isnan(a), np.isnan(b)):
                    raise RuntimeError('TABLE_RECOMPUTE_REFERENCE_MISMATCH: Q'+str(q)+' '+name+' shape/mask')
                error = float(np.nanmax(np.abs(a-b)))
                errors[name] = error
                if error > reference['tolerances'][name]:
                    raise RuntimeError('TABLE_RECOMPUTE_REFERENCE_MISMATCH: Q'+str(q)+' '+name+' '+str(error))
        if q >= 3:
            for name in ['report_s', 'report_max_C']:
                errors['event_'+name] = abs(status['event'][name]-expected['event'][name])
                if errors['event_'+name] > reference['tolerances']['event_'+name]:
                    raise RuntimeError('TABLE_RECOMPUTE_REFERENCE_MISMATCH: event '+name)
        rows.append(dict(question=q, status='PASS', max_errors=errors, reference_sha256=expected['sha256']))
    record = dict(status='PASS', check='TABLE_RECOMPUTE_REFERENCE_MATCH', case=case,
        source_case_id=status['case_id'], fingerprint=status['fingerprint'],
        convergence_validation='NOT_RERUN_IN_TABLE_ONLY_MODE', questions=rows,
        tolerances=reference['tolerances'])
    Storage_WriteJson(root/f'work/recompute/table_reference_{case}.json', record)
    print('TABLE_RECOMPUTE_REFERENCE_MATCH: PASS '+case, flush=True)
    return record
