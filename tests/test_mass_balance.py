"""Numerical conservation tests independent of exported time samples."""
from pathlib import Path
import json
import numpy as np
import pytest
from drying.studies.mass_kernel import MassBalance_BuildOperator, MassBalance_BuildKernel
from drying.studies.mass_balance import MassBalance_GetWeights, MassBalance_GetPhysicalMass
from drying.studies.trajectory import Trajectory_GetInputs, Trajectory_GetAdvance
from drying.materials import Material_Evaluate
from drying.operators import Operator_Evaluate
from drying.stages import Stage_ProjectState

ROOT = Path(__file__).resolve().parents[1]


def test_captured_boundary_is_signed_and_identical_to_original_operator():
    nr = 9; u = np.empty((2, nr, 1)); u[0] = 301.15; u[1, :, 0] = np.linspace(.3, .8, nr)
    xi = np.linspace(0., 1., nr+1)**1.3; eta = np.array([0., 1.])
    b0 = 250.; R0 = .02; R = .014
    capture = MassBalance_BuildOperator(); weights = MassBalance_GetWeights((xi, eta), b0, R0)
    for humidity in [.1, 2.]:
        out = np.empty_like(u); original = out.copy(); props = np.empty((4, nr, 1)); rows = out.copy()
        constant = np.zeros(5)
        result = capture(u, R, 323.15, humidity, 4, 25., 8e-7, False, out, props, rows, constant, xi, eta)
        Operator_Evaluate(u, R, 323.15, humidity, 4, 25., 8e-7, False, original, props, rows, np.zeros(4), xi, eta)
        assert result[1] == 0 and np.array_equal(out, original)
        flow = constant[4]*b0*(R0/R)**2*4*np.pi
        assert np.sign(flow) == (1 if humidity < .8 else -1)
        assert abs(np.sum(weights*out[1])+flow) < 1e-18


@pytest.mark.parametrize('mode', ['M00', 'M10', 'M01', 'M11'])
def test_instrumented_rk4_preserves_all_modes_and_counts_only_accepted_steps(mode):
    manifest = json.loads((ROOT/'work/studies/plot_payload/study_manifest.json').read_text(encoding='utf-8'))
    spec = next(s for s in manifest['specs'].values() if s['kind']=='production' and s['case']=='q4' and s['mode']==mode)
    p = spec['physics']; n = spec['numerics']; mesh = (np.linspace(0., 1., 13), np.array([0., 1.]))
    u = np.empty((2, 12, 1)); u[0] = p['T0_K']; u[1] = p['C0']
    real = Trajectory_GetAdvance(ROOT, spec, mesh)(u, 0., 2.)
    b0 = Material_Evaluate(4, p['T0_K'], p['C0'])[0]/(1+p['C0']); weights = MassBalance_GetWeights(mesh, b0, p['R0_m'])
    audit = np.zeros(20); audit[0] = np.sum(weights*u[1]); inputs = Trajectory_GetInputs(ROOT, spec)
    Tmin = min(p['T0_K'], inputs[0][:, 1].min(), inputs[2][0]); Tmax = max(p['T0_K'], inputs[0][:, 1].max(), inputs[2][0])
    if mode != 'M00':
        Tmin, Tmax = spec['water']['temperature_range_K']; Tmin += .05; Tmax -= .05
    kernel = MassBalance_BuildKernel(spec, b0)
    # No replay partition: large requested dt induces rejected stability trials.
    result = kernel(u, 0., 16., 16., 4, *inputs, True, False, n['safety'], n['min_dt_s'],
        n['max_rejections'], 10000, Tmin, Tmax, np.empty(0), p['h'], p['hm'], p['threshold'], *mesh, audit, weights)
    assert result[4] == 0 and int(audit[8]) == len(result[2])
    assert result[5] > 0
    assert audit[4]/audit[0] < 1e-13
    # Original production partition reproduces physical arrays exactly.
    audit[:] = 0.; audit[0] = np.sum(weights*u[1])
    result = kernel(u, 0., 2., spec['dt_max_s'], 4, *inputs, True, False, n['safety'], n['min_dt_s'],
        n['max_rejections'], len(real[2])+2, Tmin, Tmax, real[2], p['h'], p['hm'], p['threshold'], *mesh, audit, weights)
    assert np.array_equal(result[0], real[0]) and np.array_equal(result[2], real[2])
    assert audit[4]/audit[0] < 1e-13


def test_shrinking_mass_and_remesh_conserve_full_cylinder_dry_basis():
    old = (np.array([0., .1, .4, .8, 1.]), np.array([0., 1.]))
    new = (np.array([0., .3, .7, 1.]), old[1])
    state = np.array([[[303.], [306.], [310.], [318.]], [[2.4], [1.9], [.8], [.3]]])
    target, _ = Stage_ProjectState(state, old, new, 3600.)
    expected = np.sum(MassBalance_GetWeights(old, 250., .02)*state[1])
    for radius in [.02, .017, .012]:
        assert abs(MassBalance_GetPhysicalMass(state, old, radius, 250., .02)-expected) < 1e-16
        assert abs(MassBalance_GetPhysicalMass(target, new, radius, 250., .02)-expected) < 1e-16
