"""Read-only publication consistency; does not imply recomputing numerical proofs."""
import json
from pathlib import Path
from .recompute import Recompute_Hash


def Publication_Check(root):
    root = Path(root)
    manifest_path = root/'release_manifest.json'
    if not manifest_path.exists(): manifest_path = root/'work/release/publication_manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    records = manifest['publication_sha256']
    for name, digest in records.items():
        if not (root/name).is_file() or Recompute_Hash(root/name) != digest:
            raise RuntimeError('PUBLICATION_HASH_MISMATCH: '+name)
    if manifest.get('distribution_kind')=='minimal' and not (root/'results/paper_facts.json').exists():
        print(json.dumps(dict(status='PASS',scope='BUNDLE_ONLY: bundled source/config/input integrity; no numerical results certified',
            files_checked=len(records),results_available=False,pde_solves=0),ensure_ascii=False),flush=True)
        return 0
    facts = json.loads((root/'results/paper_facts.json').read_text(encoding='utf-8'))
    status = json.loads((root/'results/status.json').read_text(encoding='utf-8'))
    for q in ['Q1','Q2','Q3','Q4']:
        row = facts['official'][q]; current = status['questions'][q.lower()]
        assert row['convergence_status']['time'] == current['time_convergence_passed']
        assert row['convergence_status']['spatial'] == current['spatial_convergence_passed']
        if q in ['Q3','Q4']: assert abs(row['drying_time_h']*3600-current['drying_time']) < 1e-7
    aux = status['two_dimensional_auxiliary_validation']
    assert facts['two_dimensional_auxiliary_validation'] == aux
    assert aux['two_dimensional_auxiliary_validation_passed'] and not aux['two_dimensional_grid_independence_certified']
    print(json.dumps(dict(status='PASS',scope='published hashes and status/facts consistency; no PDE or cache certification',
        files_checked=len(records),Q3_h=facts['official']['Q3']['drying_time_h'],Q4_h=facts['official']['Q4']['drying_time_h'],
        auxiliary='PASS',grid_independence='PARTIAL_2D',pde_solves=0),ensure_ascii=False),flush=True)
    return 0
