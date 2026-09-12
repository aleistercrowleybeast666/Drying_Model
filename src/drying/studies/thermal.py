"""Additive 1D thermal closures; the production FV and RK4 code are reused."""
import types
from functools import lru_cache
from pathlib import Path
import numpy as np
from numba import njit
from ..boundaries import Boundary_GetConductance
from ..geometry import Geometry_GetGrid
from ..materials import Material_Evaluate
from ..operators import Operator_Evaluate
from ..rk4 import Rk4_Advance
from .water import Water_GetValue, Water_LoadTable


@njit(cache=True)
def Thermal_SolveBoundary(Ti,Ci,Te,He,k,D,distance,h,hm,b,latent,grid,Lv):
    jc=Boundary_GetConductance(D,distance,hm)*(Ci-He)
    Cs=He+jc/hm if hm>0 else Ci
    Ts=(h*Te+k/distance*Ti)/(h+k/distance)
    residual=0.
    if latent:
        for _ in range(12):
            value,slope=Water_GetValue(Ts,grid,Lv)
            if not np.isfinite(value):return Ts,Cs,jc,np.nan,8
            residual=h*(Te-Ts)-k/distance*(Ts-Ti)-b*jc*value
            if abs(residual)<1e-7:return Ts,Cs,jc,residual,0
            Ts+=residual/(h+k/distance+b*jc*slope)
        return Ts,Cs,jc,residual,9
    return Ts,Cs,jc,residual,0


@njit(cache=True)
def Thermal_AddOperator(U,R,Te,He,model,h,hm,xi,eta,out,props,rows,latent,sensible,b0,R0,grid,hl,Lv):
    nr,nz=U.shape[1:]
    if nz!=1:return 0.,10,0,0
    rf,rc,dr,zf,zc,dz=Geometry_GetGrid(nr,nz,R,xi,eta)
    volumes=.5*np.diff(rf**2)*dz[0];capacity=props[0,:,0]*props[1,:,0]
    b=b0*(R0/R)**2
    enthalpy=np.empty(nr);slope=np.empty(nr)
    for i in range(nr):
        enthalpy[i],slope[i]=Water_GetValue(U[0,i,0],grid,hl)
        if not np.isfinite(enthalpy[i]):return 0.,8,i,0
    if sensible:
        for i in range(nr-1):
            conductance=rf[i+1]*dz[0]/((rf[i+1]-rc[i])/props[3,i,0]+(rc[i+1]-rf[i+1])/props[3,i+1,0])
            flux=b*conductance*(U[1,i,0]-U[1,i+1,0])
            up=enthalpy[i] if flux>=0 else enthalpy[i+1]
            out[0,i,0]-=flux*(up-enthalpy[i])/(volumes[i]*capacity[i])
            out[0,i+1,0]+=flux*(up-enthalpy[i+1])/(volumes[i+1]*capacity[i+1])
            rows[0,i,0]+=abs(flux)*max(slope[i],slope[i+1])/(volumes[i]*capacity[i])
            rows[0,i+1,0]+=abs(flux)*max(slope[i],slope[i+1])/(volumes[i+1]*capacity[i+1])
    i=nr-1;distance=R-rc[-1];k=props[2,i,0];D=props[3,i,0]
    Ts,Cs,jc,residual,code=Thermal_SolveBoundary(U[0,i,0],U[1,i,0],Te,He,k,D,distance,h,hm,b,latent,grid,Lv)
    if code:return 0.,code,i,0
    area=R*dz[0];denominator=volumes[i]*capacity[i]
    if latent:
        original=Boundary_GetConductance(k,distance,h)*(Te-U[0,i,0])
        out[0,i,0]+=area*(k*(Ts-U[0,i,0])/distance-original)/denominator
        lv,dlv=Water_GetValue(Ts,grid,Lv)
        # Scaled coupled norm. The existing diffusion bound is retained.
        rows[0,i,0]+=area*b*(abs(jc*dlv)+Boundary_GetConductance(D,distance,hm)*abs(lv)*2.55/50)/denominator
    if sensible and jc<0:
        hs,ds=Water_GetValue(Ts,grid,hl)
        if not np.isfinite(hs):return 0.,8,i,0
        out[0,i,0]-=area*b*jc*(hs-enthalpy[i])/denominator
        rows[0,i,0]+=area*b*abs(jc)*max(ds,slope[i])/denominator
    return float(np.max(rows)),0,-1,-1


def Thermal_GetTable(spec):
    root=Path(__file__).resolve().parents[3]
    return Water_LoadTable(str(root/spec['water']['table_path']),spec['water']['table_sha256'])


def Thermal_GetSurface(state,R,Te,He,model,mesh,spec):
    grid,hl,Lv=Thermal_GetTable(spec);p=spec['physics']
    b0=Material_Evaluate(model,p['T0_K'],p['C0'])[0]/(1+p['C0'])
    values=Material_Evaluate(model,state[0,-1,0],state[1,-1,0])
    result=Thermal_SolveBoundary(state[0,-1,0],state[1,-1,0],Te,He,values[2],values[3],
        R*(1-(mesh[0][-2]+mesh[0][-1])/2),p['h'],p['hm'],b0*(p['R0_m']/R)**2,
        spec['mode'] in ['M10','M11'],grid,Lv)
    if result[-1]:raise RuntimeError(f'THERMAL_BOUNDARY_SOLVE_FAILED: Ts={result[0]}, Cs={result[1]}, residual={result[3]}')
    return result[0],result[1]


def Thermal_GetKernel(spec):
    grid,hl,Lv=Thermal_GetTable(spec);p=spec['physics'];model={'q1':1,'q23':3,'q4':4}[spec['case']]
    return Thermal_BuildKernel(spec['mode'],model,p['T0_K'],p['C0'],p['R0_m'],spec['water']['table_sha256'],
        tuple(grid),tuple(hl),tuple(Lv))


@lru_cache(maxsize=12)
def Thermal_BuildKernel(mode,model,T0,C0,R0,water_hash,grid_tuple,hl_tuple,Lv_tuple):
    if mode=='M00':return Rk4_Advance
    grid=np.array(grid_tuple);hl=np.array(hl_tuple);Lv=np.array(Lv_tuple)
    b0=Material_Evaluate(model,T0,C0)[0]/(1+C0);latent=mode in ['M10','M11'];sensible=mode in ['M01','M11']
    @njit
    def Operator(U,R,Te,He,model,h,hm,ends,out,props,rows,constant,xi_faces=None,eta_faces=None):
        result=Operator_Evaluate(U,R,Te,He,model,h,hm,ends,out,props,rows,constant,xi_faces,eta_faces)
        if result[1]:return result
        return Thermal_AddOperator(U,R,Te,He,model,h,hm,xi_faces,eta_faces,out,props,rows,latent,sensible,b0,R0,grid,hl,Lv)
    namespace=dict(Rk4_Advance.py_func.__globals__);namespace['Operator_Evaluate']=Operator
    # Rebind the exact original code object, not a copied/edited integrator.
    original=Rk4_Advance.py_func
    rebound=types.FunctionType(original.__code__,namespace,'Thermal_Rk4',original.__defaults__)
    compiled=njit(rebound)
    def AdvanceGuarded(*args):
        values=list(args)
        # The inherited RK4 envelope includes a 0.05 K roundoff allowance.
        # Offset its arguments so the actual accepted domain is exactly the
        # water table domain, including the final combined RK4 state.
        values[14]=grid[0]+.05;values[15]=grid[-1]-.05
        return compiled(*values)
    AdvanceGuarded.py_func=rebound
    return AdvanceGuarded
