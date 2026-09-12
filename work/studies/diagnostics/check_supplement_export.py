"""Exercise real template export early, writing the assembled test only to work/."""
from pathlib import Path
import sys
root=Path(__file__).resolve().parents[3];sys.path.insert(0,str(root/'src'))
from drying.studies.baseline import Baseline_ReadJson
from drying.studies.analysis import Analysis_ExtractSeries,Analysis_GetExpectedIds
from drying.studies import export
manifest=Baseline_ReadJson(root/'work/studies/plot_payload/study_manifest.json')
index=Baseline_ReadJson(root/'results/studies/study_index.json')
expected=Analysis_GetExpectedIds(root)
for key in list(manifest['series']):
    if manifest['series'][key]['mode']=='M10':
        for field in ['series','specs','statuses']:manifest[field].pop(key,None)
for key,value in index['experiments'].items():
    if key in expected and value.get('mode')=='M10' and value.get('kind')=='production' and value.get('complete'):
        spec=Baseline_ReadJson(root/'work/studies/experiments'/key/'spec.json')
        manifest['specs'][key]=spec;manifest['statuses'][key]=value;manifest['series'][key]=Analysis_ExtractSeries(root,spec)
original=export.Export_SaveVerified
export.Export_SaveVerified=lambda root,wb,path:original(root,wb,root/'work/studies/diagnostics/M10_supplement_export_test.xlsx')
print(export.Export_BuildSupplement(root,manifest,'M10'))
