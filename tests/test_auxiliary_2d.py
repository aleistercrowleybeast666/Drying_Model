"""Purpose-specific gates must not disguise strict errors or alter formal data."""
import numpy as np
import pytest

from drying.auxiliary2d import (AuxiliaryCache, Auxiliary_CheckCoverage,
    Auxiliary_CheckGates, Auxiliary_CheckMetadata, Auxiliary_CheckSpatial, Auxiliary_HashFile,
    Auxiliary_ReadSummary, Auxiliary_WriteJson, KEY, REPORT)


@pytest.mark.parametrize('failed', ['temporal_pass', 'critical_window_refinement_completed',
    'radial_refinement_available', 'axial_refinement_available', 'endpoint_sensitivity_pass_if_applicable',
    'qualitative_spatial_consistency', 'no_solver_failure', 'all_outputs_finite'])
def test_each_required_gate_vetoes_auxiliary_acceptance(failed):
    gates = dict.fromkeys(['temporal_pass', 'critical_window_refinement_completed',
        'radial_refinement_available', 'axial_refinement_available', 'endpoint_sensitivity_pass_if_applicable',
        'qualitative_spatial_consistency', 'no_solver_failure', 'all_outputs_finite'], True)
    assert Auxiliary_CheckGates(gates)
    gates[failed] = False
    assert not Auxiliary_CheckGates(gates)


def test_q23_requires_actual_continuation_to_5086():
    assert not Auxiliary_CheckCoverage([[0, 5085]], 5086)
    assert not Auxiliary_CheckCoverage([[0, 5085], [5085.5, 5086]], 5086)
    assert Auxiliary_CheckCoverage([[0, 5085], [5085, 5086]], 5086)


def test_missing_exact_snapshot_never_integrates(tmp_path):
    folder = tmp_path/'work/cache/example'; folder.mkdir(parents=True)
    Auxiliary_WriteJson(folder/'status.json', {'complete': True, 'fingerprint': 'example'})
    np.savez(folder/'chunk_0000.npz', time_s=[0., 2.], fields=np.zeros((2, 2, 2, 2)))
    with pytest.raises(LookupError):
        AuxiliaryCache(tmp_path).State_Read('example', 1.)


def test_qualitative_boundary_layer_can_exceed_strict_linf_but_reversal_fails():
    rf = np.linspace(0, 1, 5); zf = np.linspace(0, 1, 11)
    config = dict(physics=dict(L_m=.25, T0_K=300., C0=2.),
        comparison=dict(end_zone_z_min_m=.1, middle_zone_z_max_m=.0625))
    one = np.ones((2, 4, 1))*np.array([301., 1.9])[:, None, None]
    state = np.repeat(one, 10, axis=2)
    state[0, :, -1] += .5; state[1, :, -1] -= .3
    check = Auxiliary_CheckSpatial(state, (rf, zf), one, (rf, [0., 1.]), config)
    assert check['passed'] and check['fields'][1]['max_difference'] > .01
    state = state[:, :, ::-1].copy()
    assert not Auxiliary_CheckSpatial(state, (rf, zf), one, (rf, [0., 1.]), config)['passed']


def test_metadata_exception_does_not_allow_formal_result_changes(tmp_path, monkeypatch):
    import drying.auxiliary2d as module
    original = {'questions': {'q4': {'drying_time': 184256.64, 'spatial_convergence_passed': True}}}
    prior = tmp_path/'work/validation/auxiliary_2d/prior_status.json'
    Auxiliary_WriteJson(prior, original)
    digest = Auxiliary_HashFile(prior)
    brief = {'cases': {}, 'two_dimensional_auxiliary_validation_passed': True}
    Auxiliary_WriteJson(tmp_path/REPORT, {})
    monkeypatch.setattr(module, 'Auxiliary_GetSummary', lambda report: brief)
    current = dict(original); current[KEY] = brief
    path = tmp_path/'results/status.json'; Auxiliary_WriteJson(path, current)
    assert Auxiliary_CheckMetadata(tmp_path, 'results/status.json', digest)
    current['questions']['q4']['drying_time'] += 1
    Auxiliary_WriteJson(path, current)
    assert not Auxiliary_CheckMetadata(tmp_path, 'results/status.json', digest)
    assert not Auxiliary_CheckMetadata(tmp_path, 'results/q4/q4_summary.json', digest)


def test_stale_validation_is_rejected(tmp_path):
    path = tmp_path/'work/validation/summary.json'; Auxiliary_WriteJson(path, {'time_passed': True})
    Auxiliary_WriteJson(tmp_path/REPORT, {'source_sha256': {'work/validation/summary.json': Auxiliary_HashFile(path)}})
    Auxiliary_WriteJson(path, {'time_passed': False})
    with pytest.raises(RuntimeError, match='STALE_2D_AUXILIARY_EVIDENCE'):
        Auxiliary_ReadSummary(tmp_path)
