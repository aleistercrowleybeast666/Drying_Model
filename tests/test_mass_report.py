"""Classification isolates solver balance from optional export diagnostics."""
from copy import deepcopy
from drying.studies.mass_report import MassReport_Assess


def MassTest_GetRecord():
    return dict(complete=True,full_accepted_partition_verified=True,replay_verification=dict(status='PASS'),
        solver_mass_balance=dict(initial_water_mass_kg=.2,max_mass_balance_abs_error_kg=2e-15,
            max_mass_balance_rel_error=1e-14),remesh=[dict(remesh_water_mass_jump_rel=2e-16)],
        export_mass_balance=dict(status='DIAGNOSTIC_ONLY',max_mass_balance_rel_error=.1))


def test_export_residual_never_overrides_solver_pass():
    policy=dict(relative_tolerance=1e-10,remesh_relative_tolerance=1e-12)
    result=MassReport_Assess(MassTest_GetRecord(),policy)
    assert result['status']=='PASS' and result['export_mass_balance_affects_pass'] is False


def test_independent_mode_failure_and_remesh_failure_are_reported():
    policy=dict(relative_tolerance=1e-10,remesh_relative_tolerance=1e-12)
    original=MassTest_GetRecord(); faulty=deepcopy(original)
    faulty['solver_mass_balance'].update(max_mass_balance_abs_error_kg=2e-8,max_mass_balance_rel_error=1e-7)
    assert MassReport_Assess(faulty,policy)['status']=='FAIL'
    assert MassReport_Assess(original,policy)['status']=='PASS'
    faulty=deepcopy(original);faulty['remesh'][0]['remesh_water_mass_jump_rel']=1e-8
    result=MassReport_Assess(faulty,policy)
    assert result['status']=='FAIL' and result['nonphysical_mass_source_or_sink_detected']
    assert result['checks']['integrated_mass_balance'] and not result['checks']['remesh_mass_balance']


def test_missing_actual_partition_cannot_claim_solver_pass():
    record=MassTest_GetRecord();record['full_accepted_partition_verified']=False
    assert MassReport_Assess(record,dict(relative_tolerance=1e-10,remesh_relative_tolerance=1e-12))['status']=='FAIL'
