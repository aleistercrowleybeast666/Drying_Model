"""Read completed thermal evidence without rebuilding or overwriting payload files."""
from pathlib import Path
import json
import sys

root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(root / 'src'))
from drying.studies.plot_contract import StudyPlot_ReadManifest, StudyPlot_Find

case = sys.argv[1] if len(sys.argv) > 1 else 'q1'
mode = sys.argv[2] if len(sys.argv) > 2 else 'M10'
manifest = StudyPlot_ReadManifest(root)
production = StudyPlot_Find(manifest, case, mode)['experiment_id']
for check in manifest['checks']:
    if check['production_id'] == production:
        print(json.dumps({key: check[key] for key in [
            'case', 'mode', 'status', 'max_abs_T_K', 'max_abs_C',
            'time_half_passed', 'full_schedule_reference_passed'
        ]}), flush=True)
for audit in manifest['thermal_audits']:
    if audit['experiment_id'] == production:
        print(json.dumps(audit), flush=True)
