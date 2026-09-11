import importlib.util
from pathlib import Path
import numpy as np
import pytest
from scipy.linalg import expm
from scipy.special import j0,j1,jn_zeros
from scipy.optimize import brentq
from drying.mesh import Mesh_Check,MeshCheckResult,Mesh_Equidistribute,Mesh_GetHash
from drying.geometry import Geometry_GetCells,Geometry_GetGrid
from drying.operators import Operator_Evaluate
from drying.sampling import Sampling_Reconstruct,Sampling_GetRadial
from drying.cases import Case_LoadInputs,Case_LoadConfig
from drying.rk4 import Rk4_Advance


def Mesh_TestFaces(n):
    x=np.linspace(0,1,4097)
    return Mesh_Equidistribute(x,1+2*x,n)[0]


def Operator_TestMesh(state,mesh,constant=None,h=0,hm=0,ends=False):
    derivative=np.empty_like(state);rows=np.empty_like(state);props=np.empty((4,*state.shape[1:]))
    result=Operator_Evaluate(state,.02,301.15,2.55,1,h,hm,ends,derivative,props,rows,
        np.zeros(4) if constant is None else constant,*mesh)
    assert result[1]==0
    return derivative,props,rows


def test_equidistribution_is_nested_and_valid():
    root=Path(__file__).resolve().parents[1];cfg=Case_LoadConfig(root)['mesh']
    a,b,c=[Mesh_TestFaces(n) for n in [40,80,160]]
    assert all(Mesh_Check(f,cfg)==MeshCheckResult.VALID for f in [a,b,c])
    np.testing.assert_array_equal(a,b[::2]);np.testing.assert_array_equal(b,c[::2])
    assert np.diff(a)[-1]<np.diff(a)[0]
    invalid=a.copy();invalid[2]=invalid[1]
    assert Mesh_Check(invalid,cfg)==MeshCheckResult.MESH_NON_MONOTONIC
    assert Mesh_GetHash(a)!=Mesh_GetHash(a+1e-9)


def test_nonuniform_geometry_volume_and_shrink_topology():
    mesh=(Mesh_TestFaces(40),Mesh_TestFaces(125))
    for R in [.02,.015,.01198]:
        rf,rc,dr,zf,zc,dz=Geometry_GetGrid(40,125,R,*mesh)
        assert rf[0]==0 and rf[-1]==R and zf[-1]==.125
        assert np.all(dr>0) and np.all(dz>0)
        np.testing.assert_allclose(rf/R,mesh[0],atol=2e-16)
        volumes=Geometry_GetCells(40,125,R,mesh=mesh)[2]
        assert volumes.sum()==pytest.approx(np.pi*R*R*.125,rel=3e-16)


def test_nonuniform_constant_and_shared_flux_antisymmetry():
    mesh=(Mesh_TestFaces(12),Mesh_TestFaces(10))
    state=np.empty((2,12,10));state[0]=301.15;state[1]=2.55
    assert np.array_equal(Operator_TestMesh(state,mesh)[0],np.zeros_like(state))
    rng=np.random.default_rng(29);state+=rng.random(state.shape)
    derivative,props,_=Operator_TestMesh(state,mesh)
    volume=Geometry_GetCells(12,10,.02,mesh=mesh)[2]
    assert abs(np.sum(derivative[0]*props[0]*props[1]*volume))<1e-12
    assert abs(np.sum(derivative[1]*volume))<1e-20
    # Independently assemble each oriented interior face, once per pair.
    rf,rc,dr,zf,zc,dz=Geometry_GetGrid(12,10,.02,*mesh)
    flux=np.zeros_like(state)
    for p in [0,1]:
        for i in range(11):
            for j in range(10):
                G=rf[i+1]*dz[j]/((rf[i+1]-rc[i])/props[p+2,i,j]+(rc[i+1]-rf[i+1])/props[p+2,i+1,j])
                value=G*(state[p,i+1,j]-state[p,i,j]);flux[p,i,j]+=value;flux[p,i+1,j]-=value
        for i in range(12):
            for j in range(9):
                G=.5*(rf[i+1]**2-rf[i]**2)/((zf[j+1]-zc[j])/props[p+2,i,j]+(zc[j+1]-zf[j+1])/props[p+2,i,j+1])
                value=G*(state[p,i,j+1]-state[p,i,j]);flux[p,i,j]+=value;flux[p,i,j+1]-=value
        capacity=props[0]*props[1] if p==0 else 1
        np.testing.assert_allclose(derivative[p]*capacity*volume,flux[p]*2*np.pi,rtol=2e-14,atol=1e-16)


def test_uniform_operator_regression_against_frozen_implementation():
    path=Path(__file__).parent/'fixtures/uniform_operators.py'
    spec=importlib.util.spec_from_file_location('uniform_reference',path);legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
    rng=np.random.default_rng(8)
    for nr,nz,R in [(8,1,.02),(13,7,.017),(40,125,.01198)]:
        state=np.empty((2,nr,nz));state[0]=310+rng.random((nr,nz));state[1]=.3+rng.random((nr,nz))
        actual=[]
        for function in [legacy.Operator_Evaluate,Operator_Evaluate]:
            out=np.empty_like(state);rows=np.empty_like(state);props=np.empty((4,nr,nz))
            result=function(state,R,320.,.05,4,25.,8e-7,nz>1,out,props,rows,np.zeros(4))
            actual.append((result,out.copy(),rows.copy()))
        np.testing.assert_allclose(actual[0][1],actual[1][1],rtol=3e-12,atol=2e-12)
        np.testing.assert_allclose(actual[0][2],actual[1][2],rtol=1e-13,atol=2e-12)


def test_uniform_short_trajectory_matches_saved_pilot():
    root=Path(__file__).resolve().parents[1];inputs=Case_LoadInputs(root)
    for case,model in [('q1',1),('q23',3)]:
        path=root/f'work/cache/{case}_1d_nr40_nz1_dt0.25/chunk_0000.npz'
        if not path.exists():
            pytest.skip('Legacy local pilot cache is optional on a new machine')
        with np.load(path) as saved:
            times=saved['time_s'];states=saved['fields'];initial=states[0];expected=states[np.flatnonzero(times==2)[0]]
        result=Rk4_Advance(initial,0.,2.,.25,model,*inputs,False,False,.5,1e-8,20,1000,301.15,324.,np.empty(0))
        assert result[4]==0
        np.testing.assert_allclose(result[0],expected,rtol=1e-13,atol=1e-12)


def test_arbitrary_cell_average_quadratic_symmetry_reconstruction():
    xi,eta=Mesh_TestFaces(10),Mesh_TestFaces(12)
    rf,zf=.02*xi,.125*eta
    r2=(rf[:-1]**2+rf[1:]**2)/2;z2=(zf[:-1]**2+zf[:-1]*zf[1:]+zf[1:]**2)/3
    state=np.empty((2,10,12));state[0]=301.15+r2[:,None]+z2;state[1]=2.55+r2[:,None]+z2
    values=Sampling_Reconstruct(state,.02,301.15,2.55,1,0.,0.,False,xi,eta)
    np.testing.assert_allclose(values[:,0,0],[301.15,2.55],atol=2e-13,rtol=0)


def test_nonuniform_sampling_surface_and_outside_domain():
    mesh=(Mesh_TestFaces(20),np.array([0.,1.]))
    inputs=(np.array([[0.,301.15,.05],[259200.,323.15,.05]]),np.array([[0.,.02],[259200.,.012]]),np.array([323.15,.05]))
    state=np.empty((2,20,1));state[0]=310;state[1]=.3
    values,valid,surface,R=Sampling_GetRadial(state,259200.,4,inputs,[0,.003,.012,.02],mesh)
    assert valid.tolist()==[True,True,True,False]
    np.testing.assert_allclose(values[:,0],[310,.3],atol=1e-13)
    np.testing.assert_allclose(values[:,1],[310,.3],atol=1e-13)
    np.testing.assert_array_equal(values[:,2],surface)
    assert np.isnan(values[:,3]).all()


def test_nonuniform_robin_diffusion_has_decreasing_analytic_error():
    alpha=.36/(820*2600);Bi=25*.02/.36;t=600.
    zeros=jn_zeros(0,30)
    roots=[brentq(lambda x:x*j1(x)-Bi*j0(x),1e-10,zeros[0]-1e-10)]
    roots += [brentq(lambda x:x*j1(x)-Bi*j0(x),a+1e-10,b-1e-10) for a,b in zip(zeros[:-1],zeros[1:])]
    errors=[]
    for n in [20,40,80]:
        faces=Mesh_TestFaces(n);mesh=(faces,np.array([0.,1.]))
        state=np.empty((2,n,1));state[0]=301.15;state[1]=2.55
        baseline=Operator_TestMesh(state,mesh,h=25)[0][0,:,0]
        matrix=np.empty((n,n))
        for col in range(n):
            unit=state.copy();unit[0,col,0]+=1
            matrix[:,col]=Operator_TestMesh(unit,mesh,h=25)[0][0,:,0]-baseline
        computed=expm(matrix*t)@np.ones(n);exact=np.zeros(n)
        for root in roots:
            coefficient=2*j1(root)/(root*(j0(root)**2+j1(root)**2))
            average=2*(faces[1:]*j1(root*faces[1:])-faces[:-1]*j1(root*faces[:-1]))/(root*np.diff(faces**2))
            exact+=coefficient*np.exp(-alpha*root**2*t/.02**2)*average
        errors.append(float(np.max(abs(computed-exact))))
    assert errors[0]/errors[1]>3 and errors[1]/errors[2]>3
    from drying.storage import Storage_WriteJson
    Storage_WriteJson(Path(__file__).resolve().parents[1]/'work/validation/nonuniform_analytic.json',dict(n=[20,40,80],errors=errors))
