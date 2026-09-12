"""Explicit conservative mesh choices for supplemental modes only."""
import json
from pathlib import Path


def Selection_GetFactor(root,case,mode):
    if mode=='M00':return 1
    path=Path(root)/'configs/studies_numerics.json'
    data=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    factor=data.get('thermal_spatial_factors',{}).get(case,{}).get(mode,1)
    if factor not in [1,2,4]:raise ValueError('INVALID_SUPPLEMENTAL_SPATIAL_FACTOR')
    return factor
