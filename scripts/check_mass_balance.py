"""Verify published solver mass audits and frozen artifacts without solving PDEs."""
from pathlib import Path
import json
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from drying.storage import Storage_WriteJson
from drying.studies.baseline import Baseline_Check, Baseline_ReadJson, Baseline_HashFile
from drying.studies.mass_report import MassReport_ReadSummary, MassReport_GetLines, MassReport_Assess


def MassCheck_Run():
    folder=ROOT/'work/validation/mass_balance';summary=Baseline_ReadJson(folder/'summary.json')
    brief=MassReport_ReadSummary(ROOT);baseline=Baseline_Check(ROOT);rows=[]
    assert summary['completed_case_count']==12 and not summary['missing_cases']
    assert {(r['case'],r['mode']) for r in summary['cases']}=={(q,m) for q in ['q1','q23','q4'] for m in ['M00','M10','M01','M11']}
    policy=Baseline_ReadJson(folder/'policy.json')
    assert policy['residual_used_to_fit_tolerance'] is False and policy['existing_space_and_time_thresholds_changed'] is False
    for case in summary['cases']:
        record=Baseline_ReadJson(ROOT/case['source_file']);ledger=record['solver_mass_balance'];count=0;found_max=False
        assert Baseline_HashFile(ROOT/case['source_file'])==case['source_sha256']
        for name,digest in record['source']['source_files'].items():
            assert Baseline_HashFile(ROOT/name)==digest
            if Path(name).name.startswith('chunk_'):
                with np.load(ROOT/name) as data:
                    ends=data['step_ends'];count+=len(ends)
                    found_max=found_max or bool(np.any(ends==ledger['time_of_max_error_s']))
        for name,digest in record['source']['numerical_sources'].items():assert Baseline_HashFile(ROOT/name)==digest
        assert count==ledger['accepted_steps'] and found_max
        assert record['full_accepted_partition_verified'] and record['replay_verification']['status']=='PASS'
        assert record['export_mass_balance']['affects_pass'] is False
        assert MassReport_Assess(record,policy)['status']==case['status']
        for entry in record['audit_files']:
            assert Baseline_HashFile(ROOT/entry['path'])==entry['sha256']
            with np.load(ROOT/entry['path']) as data:
                assert data['time_s'][0]==0. and data['time_s'][-1]==record['observation_end_s']
                assert np.all(np.diff(data['time_s'])>=0.)
                error=(data['remaining_water_mass_kg']-ledger['initial_water_mass_kg'])+data['cumulative_outflow_water_mass_kg']
                assert np.max(abs(error-data['mass_balance_signed_error_kg']))<=4*np.finfo(float).eps*ledger['initial_water_mass_kg']
                assert np.max(abs(error))<=ledger['max_mass_balance_abs_error_kg']+4*np.finfo(float).eps*ledger['initial_water_mass_kg']
                assert abs(data['remaining_water_mass_kg'][-1]-ledger['remaining_water_mass_kg'])<1e-16
        rows.append(dict(case=case['case'],mode=case['mode'],status=case['status'],accepted_steps=count,
            maximum_error_is_an_actual_accepted_time=found_max))
    for name in ['results/studies/validation_summary.json','results/paper_facts.json']:
        assert Baseline_ReadJson(ROOT/name)['solver_mass_balance']==brief
    for name in ['results/studies/overview.md','results/paper_facts.md']:
        text=(ROOT/name).read_text(encoding='utf-8')
        assert all(line in text for line in MassReport_GetLines(brief) if line)
    manifest=Baseline_ReadJson(ROOT/'work/studies/plot_payload/study_manifest.json')
    assert all(Baseline_HashFile(ROOT/r['path'])==r['sha256'] for r in manifest['workbooks'])
    protected=Baseline_ReadJson(ROOT/'work/studies/technical/protected_existing.json')
    assert all(Baseline_HashFile(ROOT/name)==digest for name,digest in protected.items())
    frozen=Baseline_ReadJson(ROOT/'work/baseline_snapshot/baseline_manifest.json')
    expected_gifs={name for name in set(frozen['protected_files'])|set(protected) if name.startswith('results/') and name.endswith('.gif')}
    migration=Baseline_ReadJson(ROOT/'work/baseline_snapshot/gif_migration.json')['paths']
    expected_gifs={migration.get(name,name) for name in expected_gifs}
    actual_gifs={p.relative_to(ROOT).as_posix() for p in (ROOT/'results').rglob('*.gif')}
    assert actual_gifs==expected_gifs and len(actual_gifs)==7
    visual=Baseline_ReadJson(ROOT/'work/studies/technical/validation/visual_review.json')
    assert all(Baseline_HashFile(ROOT/r['path'])==r['sha256'] for r in visual['figures_reviewed'])
    result=dict(status=summary['status'],cases=rows,accepted_steps_checked=sum(r['accepted_steps'] for r in rows),
        published_json_summaries_identical=True,published_markdown_summaries_identical=True,
        source_arrays_unchanged=True,baseline=baseline,existing_study_workbooks_and_figures_unchanged=True,
        additional_GIF_created=False)
    Storage_WriteJson(folder/'acceptance.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if summary['status']!='PASS':raise RuntimeError('MASS_BALANCE_FAILED: inspect the individual case records')


if __name__=='__main__':MassCheck_Run()
