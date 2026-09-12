"""Bounded integration QA on real completed data, without publishing results."""
import json,sys
from pathlib import Path
from openpyxl import Workbook
root=Path(__file__).resolve().parents[3];sys.path.insert(0,str(root/'src'))
from drying.studies.baseline import Baseline_ReadJson
from drying.studies.trajectory import Trajectory_GetSpec
from drying.studies.analysis import Analysis_ExtractSeries
from drying.studies.synthesis import Synthesis_Build
from drying.studies.export import Export_GetTimeseries,Export_AddTable,Export_SaveVerified
baseline=Baseline_ReadJson(root/'work/baseline_snapshot/baseline_manifest.json')
manifest=dict(baseline_id=baseline['baseline_id'],series={},specs={},statuses={},baseline_keys={},checks=[],end_effects=[],thermal_audits=[])
for case in ['q1','q23','q4']:
    spec=Trajectory_GetSpec(root,case);key=baseline['selected'][case+'_1d']['case_id'];spec['experiment_id']=key
    status=baseline['selected'][case+'_1d'];events=[status['event']['report_s']] if status.get('event') else []
    manifest['baseline_keys'][case]=key;manifest['specs'][key]=spec;manifest['statuses'][key]=status
    manifest['series'][key]=Analysis_ExtractSeries(root,spec,baseline=True,extra_times=events)
Synthesis_Build(root,manifest,publish=False)
json.dumps(manifest,allow_nan=False)
for name,tables in [('summary',manifest['summary_tables']),('timeseries',Export_GetTimeseries(root,manifest))]:
    book=Workbook();book.remove(book.active)
    for title,rows in tables.items():Export_AddTable(book,title,rows)
    record=Export_SaveVerified(root,book,root/f'work/studies/diagnostics/{name}_integration_test.xlsx')
    print(json.dumps(record),flush=True)
print('SUMMARY_TIMESERIES_INTEGRATION_PASS',flush=True)
