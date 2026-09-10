import numpy as np
import pytest
from scipy.linalg import expm
from scipy.optimize import brentq
from scipy.special import j0, j1, jn_zeros
from drying.materials import Material_Evaluate
from drying.operators import Operator_Evaluate
from drying.rk4 import Rk4_ScalarStep, Rk4_Advance
from drying.sampling import Sampling_Reconstruct, Sampling_GetRadial
from drying.inputs import Input_AtTime, Input_ReadTable, Input_ExtractZip
from drying.geometry import Geometry_GetCells


def Operator_Test(U, R=.02, h=0., hm=0., ends=False, model=3, constant=None):
    out, rows = np.empty_like(U), np.empty_like(U)
    props = np.empty((4, *U.shape[1:]))
    result = Operator_Evaluate(U, R, 301.15, 2.55, model, h, hm, ends, out, props, rows,
                               np.zeros(4) if constant is None else np.asarray(constant))
    assert result[1] == 0
    return out, props


def test_material_initial_regressions():
    np.testing.assert_allclose(Material_Evaluate(3, 301.15, 2.55),
        [976.4, 3415.295774647887, .48295774647887324, 5.641680373025668e-9], rtol=2e-14)
    np.testing.assert_allclose(Material_Evaluate(4, 301.15, 2.55),
        [989.5, 3394.366197183099, .26366197183098594, 1.0471122989493634e-9], rtol=2e-14)


def test_rk4_order_and_polynomial():
    errors = []
    for count in (10, 20, 40):
        value = 1.
        for i in range(count):
            value = Rk4_ScalarStep(lambda t, y: y, i/count, value, 1/count)
        errors.append(abs(value-np.e))
    assert all(14 < a/b < 18 for a,b in zip(errors, errors[1:]))
    assert Rk4_ScalarStep(lambda t, y: 4*t**3, 0, 0, 1) == pytest.approx(1.)


def test_zero_exchange_uniform_shrink():
    U = np.empty((2, 8, 6)); U[0] = 301.15; U[1] = 2.55
    for R in (.02, .015, .01198):
        derivative, _ = Operator_Test(U, R, model=4)
        assert np.array_equal(derivative, np.zeros_like(U))


def test_shared_flux_cancellation_and_local_balance():
    rng = np.random.default_rng(41)
    U = np.empty((2, 8, 6)); U[0] = 301+rng.random((8, 6)); U[1] = 1+rng.random((8, 6))
    derivative, props = Operator_Test(U)
    volumes = Geometry_GetCells(8, 6, .02)[2]
    assert abs(np.sum(derivative[1]*volumes)) < 1e-20
    assert abs(np.sum(derivative[0]*props[0]*props[1]*volumes)) < 1e-12
    # Both exposed boundary types counted once, including the corner cell.
    derivative, props = Operator_Test(U, h=25, hm=8e-7, ends=True)
    from drying.boundaries import Boundary_GetConductance
    residuals=[]
    for p, exchange, outside in [(0, 25., 301.15), (1, 8e-7, 2.55)]:
        side = sum(2*np.pi*.02*(.125/6)*Boundary_GetConductance(props[p+2, -1, j], .02/16, exchange)*(U[p, -1, j]-outside) for j in range(6))
        end = sum(volumes[i, -1]/(.125/6)*Boundary_GetConductance(props[p+2, i, -1], .125/12, exchange)*(U[p, i, -1]-outside) for i in range(8))
        capacity = props[0]*props[1] if p == 0 else 1.
        residual=float(np.sum(derivative[p]*capacity*volumes)+side+end)
        residuals.append(dict(field='heat_effective_W' if p==0 else 'normalized_moisture_m3_s',residual=residual,side_flux=side,end_flux=end))
        assert abs(residual) < (1e-12 if p == 0 else 1e-20)
    from pathlib import Path
    from drying.storage import Storage_WriteJson
    Storage_WriteJson(Path(__file__).resolve().parents[1]/'work/validation/flux_residuals.json',residuals)


def test_closed_ends_reduce_to_1d():
    U = np.empty((2, 12, 1)); U[0, :, 0] = np.linspace(302, 310, 12); U[1, :, 0] = np.linspace(2.4, 1., 12)
    one = Operator_Test(U, h=25, hm=8e-7)[0]
    two = Operator_Test(np.repeat(U, 7, axis=2), h=25, hm=8e-7)[0]
    np.testing.assert_allclose(two, np.repeat(one, 7, axis=2), rtol=1e-13, atol=1e-13)


def test_axis_and_midplane_cell_average_reconstruction():
    n, m = 10, 12
    rf = np.linspace(0, .02, n+1)
    zf = np.linspace(0, .125, m+1)
    r2 = (rf[1:]**2+rf[:-1]**2)/2
    z2 = (zf[1:]**2+zf[1:]*zf[:-1]+zf[:-1]**2)/3
    U = np.empty((2, n, m)); U[0] = 301.15+r2[:,None]+z2; U[1] = 2.55+r2[:,None]+z2
    reconstructed = Sampling_Reconstruct(U, .02, 301.15, 2.55, 3, 0, 0, False)
    np.testing.assert_allclose(reconstructed[:, 0, 0], [301.15, 2.55], atol=6e-14, rtol=0)


def test_input_sides_and_radius_range():
    env = np.array([[0.,301.,.02], [14400.,324.,.06]])
    radius = np.array([[0.,.02], [259200.,.01198]])
    tail = np.array([323.,.05])
    assert Input_AtTime(14400,env,radius,tail,False)[0] == 324.
    assert Input_AtTime(14400,env,radius,tail,False,True)[0] == 323.
    with pytest.raises(ValueError):
        Input_AtTime(259201,env,radius,tail,True)


def test_rk4_constant_radius_fourth_appendix():
    U = np.empty((2, 5, 1)); U[0] = 301.15; U[1] = 2.55
    env = np.array([[0., 310., .05], [14400., 310., .05]])
    radius = np.array([[0., .02], [259200., .02]])
    args = (U, 0., 2., .1, 4, env, radius, np.array([310., .05]))
    a = Rk4_Advance(*args, True, False, .5, 1e-8, 20, 1000, 301.15, 310., np.empty(0))[0]
    b = Rk4_Advance(*args, False, False, .5, 1e-8, 20, 1000, 301.15, 310., np.empty(0))[0]
    assert np.array_equal(a,b)


def test_production_rk4_heat_time_order():
    n=4
    initial=np.empty((2,n,1)); initial[0]=310.; initial[1]=2.55
    env=np.array([[0.,301.15,2.55],[14400.,301.15,2.55]])
    radius=np.array([[0.,.02],[259200.,.02]])
    equilibrium=initial.copy(); equilibrium[0]=301.15
    matrix=np.empty((n,n))
    for column in range(n):
        unit=equilibrium.copy(); unit[0,column,0]+=1
        matrix[:,column]=Operator_Test(unit,h=25,model=1)[0][0,:,0]
    exact=301.15+expm(matrix*120)@np.full(n,8.85)
    errors=[]
    for dt in [10.,5.,2.5]:
        result=Rk4_Advance(initial,0.,120.,dt,1,env,radius,np.array([301.15,2.55]),
            False,False,.5,1e-8,20,1000,301.15,310.,np.empty(0))
        assert result[4]==0 and result[5]==0
        errors.append(np.max(abs(result[0][0,:,0]-exact)))
    assert 12<errors[0]/errors[1]<20 and 12<errors[1]/errors[2]<20


def test_production_shrinking_uniform_field_without_exchange():
    initial=np.empty((2,6,3)); initial[0]=301.15; initial[1]=2.55
    env=np.array([[0.,301.15,2.55],[14400.,301.15,2.55]])
    radius=np.array([[0.,.02],[1800.,.019],[259200.,.01198]])
    result=Rk4_Advance(initial,0.,1800.,.25,4,env,radius,np.array([301.15,2.55]),
        True,True,.5,1e-8,20,10000,301.15,301.15,np.empty(0),0.,0.)
    assert result[4]==0
    assert np.array_equal(result[0],initial)


def test_independent_robin_cylinder_series():
    # Constant appendix-2 heat equation, exact Robin eigenfunction series.
    rho, cp, k, _ = Material_Evaluate(1, 301.15, 2.55)
    Bi, alpha, R, t = 25*.02/k, k/(rho*cp), .02, 600.
    zeros = jn_zeros(0, 35)
    roots = [brentq(lambda x: x*j1(x)-Bi*j0(x), 1e-10, zeros[0]-1e-10)]
    for low, high in zip(zeros[:-1], zeros[1:]):
        roots.append(brentq(lambda x: x*j1(x)-Bi*j0(x), low+1e-10, high-1e-10))
    errors = []
    for n in (20, 40, 80):
        U = np.empty((2, n, 1)); U[0] = 301.15; U[1] = 2.55
        baseline = Operator_Test(U, h=25, model=1)[0][0,:,0]
        matrix = np.empty((n,n))
        for column in range(n):
            test = U.copy(); test[0,column,0] += 1
            matrix[:,column] = Operator_Test(test, h=25, model=1)[0][0,:,0]-baseline
        computed = expm(matrix*t) @ np.ones(n)
        edges = np.linspace(0,1,n+1)
        exact = np.zeros(n)
        for root in roots:
            coefficient = 2*j1(root)/(root*(j0(root)**2+j1(root)**2))
            average = 2*(edges[1:]*j1(root*edges[1:])-edges[:-1]*j1(root*edges[:-1]))/(root*np.diff(edges**2))
            exact += coefficient*average*np.exp(-root*root*alpha*t/R**2)
        errors.append(float(np.max(np.abs(computed-exact))))
    assert errors[-1] < 2e-5
    assert errors[0]/errors[1] > 3.5 and errors[1]/errors[2] > 3.5
    from pathlib import Path
    from drying.storage import Storage_WriteJson
    Storage_WriteJson(Path(__file__).resolve().parents[1]/'work/validation/analytic_cylinder.json',
        dict(time_s=t,Nr=[20,40,80],maximum_cell_average_error=errors,series_terms=len(roots),
             benchmark='Appendix-2 constant heat equation, cylindrical Bessel Robin series vs exact semidiscrete matrix exponential'))
