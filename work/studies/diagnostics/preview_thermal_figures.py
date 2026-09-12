"""Preliminary layout check from completed production fields; work/ outputs only."""
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[3];sys.path.insert(0,str(root/'src'))
from drying.studies.baseline import Baseline_ReadJson
from drying.studies.synthesis import Synthesis_Build
from drying.studies.analysis import Analysis_Compare
from drying.studies import plots
from drying.storage import Storage_WriteJson

manifest=Baseline_ReadJson(root/'work/studies/diagnostics/prepared_series.json')
manifest.update(baseline_id=Baseline_ReadJson(root/'work/baseline_snapshot/baseline_manifest.json')['baseline_id'],
    checks=[],thermal_audits=[],end_effects=[],remesh_front_audits=[],historical_checks=[],
    experiments=Baseline_ReadJson(root/'results/studies/study_index.json')['experiments'],qa_only=True)
for key in manifest['specs']:
    comparison=root/'work/studies/validation'/f'{key}_comparison.json'
    if comparison.exists():
        check=Baseline_ReadJson(comparison)
        if any('Cmax' not in event for event in check['events']):
            target=check['production_id']
            check=Analysis_Compare(root,manifest['specs'][target],manifest['specs'][key],
                manifest['series'][target],manifest['series'][key],manifest['statuses'][target],manifest['statuses'][key],
                left_baseline=manifest['specs'][target]['mode']=='M00')
        manifest['checks'].append(check)
    audit=root/'work/studies/validation'/f'{key}_thermal_audit.json'
    if audit.exists():manifest['thermal_audits'].append({k:v for k,v in Baseline_ReadJson(audit).items() if k not in ['samples','remesh']})
Synthesis_Build(root,manifest,publish=False)
Storage_WriteJson(root/'work/studies/diagnostics/prepared_visual_manifest.json',manifest)
original=plots.StudyPlot_Finish
def Preview_Finish(fig,axes,path):
    return original(fig,axes,root/'work/studies/diagnostics/visual_previews'/Path(path).name)
plots.StudyPlot_Finish=Preview_Finish;plots.StudyPlot_SetStyle()
for name in ['thermal_modes','thermal_interactions']:
    plots.StudyPlot_Draw(root,manifest,name);print('LAYOUT_PREVIEW '+name,flush=True)
