"""Verify stored time refinements really bisect every accepted baseline interval."""
import json
import sys
from pathlib import Path
import numpy as np

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'src'))
from drying.storage import Storage_WriteJson

records=[]
for status_file in sorted((root/'work/cache').glob('*/status.json')):
    status=json.loads(status_file.read_text(encoding='utf-8'))
    if not status.get('replay_id') or not status['complete']:
        continue
    fine_folder=status_file.parent; base_folder=root/'work/cache'/status['replay_id']
    matched=0; fine_steps=0; start=0.; max_fine_dt=0.
    for fine_path in sorted(fine_folder.glob('chunk_*.npz')):
        with np.load(fine_path) as cache: fine=cache['step_ends']
        with np.load(base_folder/fine_path.name) as cache: base=cache['step_ends']
        base=base[base<=fine[-1]+1e-9]
        middle=(np.r_[start,base[:-1]]+base)/2
        wanted=np.sort(np.r_[middle,base])
        locations=np.searchsorted(fine,wanted)
        assert np.all(locations<len(fine)), 'missing parent boundary/midpoint'
        assert np.max(abs(fine[locations]-wanted))<1e-9, 'partition not genuinely halved'
        max_fine_dt=max(max_fine_dt,float(np.max(np.diff(np.r_[start,fine]))))
        matched+=len(base); fine_steps+=len(fine); start=float(fine[-1])
    records.append(dict(case_id=status['case_id'],base_id=status['replay_id'],
        covered_until_s=start,base_steps=matched,refined_steps=fine_steps,
        maximum_refined_dt_s=max_fine_dt,all_baseline_midpoints_and_endpoints_present=True))
Storage_WriteJson(root/'work/validation/actual_partition_audit.json',records)
print(json.dumps(records,indent=2))
