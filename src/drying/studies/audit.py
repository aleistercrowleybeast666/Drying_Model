"""Independent instantaneous water/effective-heat balances and remesh diagnostics."""
from pathlib import Path
import numpy as np
from ..geometry import Geometry_GetGrid
from ..materials import Material_Evaluate
from ..operators import Operator_Evaluate
from ..inputs import Input_AtTime
from ..boundaries import Boundary_GetConductance
from ..storage import Storage_WriteJson
from .trajectory import Trajectory_Iter,Trajectory_GetInputs,Trajectory_GetNodes
from .thermal import Thermal_AddOperator,Thermal_GetTable,Thermal_SolveBoundary
from .water import Water_GetValue
from .metrics import Metrics_GetFront
from .baseline import Baseline_ReadJson


def Audit_CheckBaselineRemesh(root,spec,selected):
    root=Path(root);inputs=Trajectory_GetInputs(root,spec);model={'q1':1,'q23':3,'q4':4}[spec['case']];records=[]
    for previous,current in zip(selected['stages'][:-1],selected['stages'][1:]):
        states=[];meshes=[]
        for item,last in [(previous,True),(current,False)]:
            folder=root/'work/cache'/item['case_id'];files=sorted(folder.glob('chunk_*.npz'))
            with np.load(files[-1] if last else files[0]) as block:states.append(block['fields'][-1 if last else 0].copy())
            with np.load(folder/'mesh.npz') as data:meshes.append((data['xi_faces'].copy(),data['eta_faces'].copy()))
        t=current['t_start'];fronts=[];water=[]
        for state,mesh in zip(states,meshes):
            r,z,nodes=Trajectory_GetNodes(state,t,model,inputs,mesh,spec)
            fronts.append([Metrics_GetFront(r,nodes[1,:,0],c) for c in [2.,1.,.5,.15]])
            water.append(float(np.dot(np.diff(mesh[0]**2),state[1,:,0])))
        records.append(dict(time_s=t,fronts_before=fronts[0],fronts_after=fronts[1],
            front_radius_change_m=[b['radius_m']-a['radius_m'] for a,b in zip(fronts[0],fronts[1])],
            relative_volume_integral_C_error=abs(water[1]-water[0])/abs(water[0]),
            note='Front jumps are projection diagnostics at a common time; not physical recession rates.'))
    result=dict(case=spec['case'],mode='M00',status='PASS' if all(v['relative_volume_integral_C_error']<=1e-12 for v in records) else 'FAIL',records=records)
    Storage_WriteJson(root/f"work/studies/validation/{spec['case']}_baseline_remesh_fronts.json",result)
    return result


def Audit_CheckThermal(root,spec):
    root=Path(root);grid,hl,Lv=Thermal_GetTable(spec);p=spec['physics'];model={'q1':1,'q23':3,'q4':4}[spec['case']]
    inputs=Trajectory_GetInputs(root,spec);b0=Material_Evaluate(model,p['T0_K'],p['C0'])[0]/(1+p['C0'])
    latent=spec['mode'] in ['M10','M11'];sensible=spec['mode'] in ['M01','M11']
    audits=[];negative=0;previous_nr=None
    for t,U,mesh in Trajectory_Iter(root,spec['experiment_id']):
        if t!=0 and t%600!=0 and U.shape[1]==previous_nr:continue
        previous_nr=U.shape[1];Te,He,R=Input_AtTime(t,*inputs,spec['shrink']);nr=U.shape[1]
        props=np.empty((4,nr,1));out=np.empty_like(U);rows=np.empty_like(U)
        base=Operator_Evaluate(U,R,Te,He,model,p['h'],p['hm'],False,out,props,rows,np.zeros(4),*mesh)
        check=Thermal_AddOperator(U,R,Te,He,model,p['h'],p['hm'],*mesh,out,props,rows,latent,sensible,b0,p['R0_m'],grid,hl,Lv)
        if base[1] or check[1]:raise RuntimeError('THERMAL_BALANCE_CHECK_FAILED: property or boundary')
        rf,rc,dr,zf,zc,dz=Geometry_GetGrid(nr,1,R,*mesh);vol=.5*np.diff(rf**2)*dz[0];b=b0*(p['R0_m']/R)**2
        Ts,Cs,jc,residual,code=Thermal_SolveBoundary(U[0,-1,0],U[1,-1,0],Te,He,props[2,-1,0],props[3,-1,0],R-rc[-1],p['h'],p['hm'],b,latent,grid,Lv)
        if jc<0:negative+=1
        enthalpy=np.array([Water_GetValue(T,grid,hl)[0] for T in U[0,:,0]])
        source=0.
        if sensible:
            for i in range(nr-1):
                water=b*rf[i+1]*dz[0]/((rf[i+1]-rc[i])/props[3,i,0]+(rc[i+1]-rf[i+1])/props[3,i+1,0])*(U[1,i,0]-U[1,i+1,0])
                source+=water*(enthalpy[i]-enthalpy[i+1])
            if jc<0:source-=R*dz[0]*b*jc*(Water_GetValue(Ts,grid,hl)[0]-enthalpy[-1])
        heat_expected=R*dz[0]*props[2,-1,0]*(Ts-U[0,-1,0])/(R-rc[-1])+source
        heat_actual=np.dot(vol*props[0,:,0]*props[1,:,0],out[0,:,0])
        mass_actual=np.dot(b*vol,out[1,:,0]);mass_expected=-R*dz[0]*b*jc
        audits.append(dict(time_s=t,temperature_surface_K=Ts,moisture_surface=Cs,signed_Jw_kg_m2_s=b*jc,
            heat_balance_abs_W_per_rad=float(abs(heat_actual-heat_expected)),water_balance_abs_kg_s_per_rad=float(abs(mass_actual-mass_expected)),
            boundary_residual_W_m2=float(residual),heat_scale_W_per_rad=float(max(abs(heat_expected),abs(heat_actual),1e-12))))
    transfers=[];folder=root/'work/studies/experiments'/spec['experiment_id']
    for path in sorted(folder.glob('remesh_*.npz')):
        with np.load(path) as data:
            t=float(data['time_s']);before=data['before'];after=data['after'];old=data['old_xi'];new=data['new_xi']
        storage=[];front=[];water=[];R=Input_AtTime(t,*inputs,spec['shrink'])[2]
        for U,xi in [(before,old),(after,new)]:
            weight=np.pi*R**2*np.diff(xi**2)*p['L_m'];water.append(float(np.dot(weight,U[1,:,0])))
            K=np.array([np.prod(Material_Evaluate(model,T,C)[:2]) for T,C in zip(U[0,:,0],U[1,:,0])])
            storage.append(float(np.dot(weight*K,U[0,:,0]-273.15)))
            r,z,nodes=Trajectory_GetNodes(U,t,model,inputs,(xi,np.array([0.,1.])),spec)
            front.append([Metrics_GetFront(r,nodes[1,:,0],c) for c in [2.,1.,.5,.15]])
        transfers.append(dict(time_s=t,volume_integral_C_before=water[0],volume_integral_C_after=water[1],
            effective_storage_J_before=storage[0],effective_storage_J_after=storage[1],effective_storage_change_J=storage[1]-storage[0],
            fronts_before=front[0],fronts_after=front[1],meaning='K(T,C)*(T-273.15) volume indicator, not total mixture enthalpy; properties recomputed after transfer'))
    passed=all(a['heat_balance_abs_W_per_rad']<=1e-9+1e-8*a['heat_scale_W_per_rad'] and a['water_balance_abs_kg_s_per_rad']<1e-14 and abs(a['boundary_residual_W_m2'])<1e-6 for a in audits)
    result=dict(experiment_id=spec['experiment_id'],status='PASS' if passed else 'THERMAL_BALANCE_CHECK_FAILED',
        samples=audits,remesh=transfers,reverse_flux_sample_count=negative,scope='instantaneous FV effective-temperature and water identities at 600 s and stage outputs; RK4 stage guards run at every substep',
        b0_kg_m3=b0,dry_mass_kg=b0*np.pi*p['R0_m']**2*p['L_m'])
    Storage_WriteJson(root/'work/studies/validation'/f"{spec['experiment_id']}_thermal_audit.json",result)
    return {k:v for k,v in result.items() if k not in ['samples','remesh']}
