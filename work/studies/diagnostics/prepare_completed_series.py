"""Prepare completed scientific series while the serial reference queue continues."""
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[3];sys.path.insert(0,str(root/'src'))
from drying.studies.analysis import Analysis_GetExpectedIds,Analysis_GetBaselineSpec,Analysis_ExtractSeries
from drying.studies.baseline import Baseline_ReadJson
from drying.storage import Storage_WriteJson

index=Baseline_ReadJson(root/'results/studies/study_index.json')
baseline=Baseline_ReadJson(root/'work/baseline_snapshot/baseline_manifest.json')
expected=Analysis_GetExpectedIds(root);current={};specs={};statuses={};keys={};events={c:[] for c in ['q1','q23','q4']}
for case in events:
    spec=Analysis_GetBaselineSpec(root,case);key=spec['experiment_id'];keys[case]=key;specs[key]=spec
    statuses[key]=baseline['selected'][case+'_1d']
    if statuses[key].get('event'):events[case].append(statuses[key]['event']['report_s'])
for key in expected:
    result=index['experiments'].get(key,{})
    if not result.get('complete'):continue
    spec=Baseline_ReadJson(root/'work/studies/experiments'/key/'spec.json');current[key]=spec;statuses[key]=result;specs[key]=spec
    if spec['kind'] in ['production','fixed_radius','tail','matched'] and result.get('event'):
        events[spec['case']].append(result['event']['report_s'])
series={}
for case,key in keys.items():
    print('PREPARE_FROZEN '+case,flush=True)
    series[key]=Analysis_ExtractSeries(root,specs[key],baseline=True,extra_times=events[case])
for key,spec in current.items():
    print('PREPARE_SERIES '+key,flush=True)
    own=[statuses[key]['event']['report_s']] if statuses[key].get('event') else []
    times=events[spec['case']] if spec['kind'] in ['production','fixed_radius','tail'] else own
    series[key]=Analysis_ExtractSeries(root,spec,extra_times=times)
Storage_WriteJson(root/'work/studies/diagnostics/prepared_series.json',dict(series=series,specs=specs,statuses=statuses,baseline_keys=keys))
print('PREPARED_SERIES_COUNT '+str(len(series)),flush=True)
