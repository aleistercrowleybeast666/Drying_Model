from pathlib import Path
import sys
root=Path(__file__).resolve().parents[3];sys.path.insert(0,str(root/'src'))
from drying.studies.baseline import Baseline_ReadJson
from drying.studies.analysis import Analysis_ExtractSeries,Analysis_EndEffects
from drying.studies.audit import Audit_CheckBaselineRemesh
from drying.studies.trajectory import Trajectory_GetSpec
manifest=Baseline_ReadJson(root/'work/studies/plot_payload/study_manifest.json')
index=Baseline_ReadJson(root/'results/studies/study_index.json')
baseline=Baseline_ReadJson(root/'work/baseline_snapshot/baseline_manifest.json')
for case in ['q1','q23','q4']:
    key=next(k for k,v in index['experiments'].items() if v.get('case')==case and v.get('kind')=='matched' and v.get('complete'))
    spec=Baseline_ReadJson(root/'work/studies/experiments'/key/'spec.json')
    entry=Analysis_ExtractSeries(root,spec)
    print(Analysis_EndEffects(root,case,spec,entry,manifest['series'][manifest['baseline_keys'][case]]),flush=True)
for case in ['q1','q23','q4']:
    audit=Audit_CheckBaselineRemesh(root,Trajectory_GetSpec(root,case),baseline['selected'][case+'_1d'])
    print('REMESH',case,audit['status'],[row['relative_volume_integral_C_error'] for row in audit['records']],flush=True)
