"""Read-only replay of accepted RK4 histories for every internal-time comparison.

No production state is changed. Between different accepted time partitions the
other trajectory is linearly interpolated; this is a discrete audit, not a
continuous-time error bound. Replay endpoints are checked against stored fields.
"""
import hashlib
import json
import time
from pathlib import Path
import numpy as np
from numba import njit
from .operators import Operator_Evaluate
from .inputs import Input_AtTime
from .geometry import Geometry_GetSymmetryWeights
from .materials import Material_Evaluate
from .boundaries import Boundary_Reconstruct
from .cases import Case_ReadStatus, Case_LoadMesh, Case_LoadInputs
from .storage import Storage_WriteJson, Storage_HashFiles


@njit(cache=True)
def Audit_ReplayInterval(initial, start, ends, xi, model, environment, radius, tail):
    """Identical classical RK4 stages on an already accepted finite partition."""
    states = np.empty((len(ends)+1,)+initial.shape)
    states[0] = initial
    stages = np.empty((4,)+initial.shape)
    trial = initial.copy()
    props = np.empty((4,initial.shape[1],1))
    rows = np.empty_like(initial)
    constant = np.zeros(4); eta = np.array([0.,1.])
    t = start
    for n in range(len(ends)):
        dt = ends[n]-t
        for k in range(4):
            fraction = 0. if k == 0 else 1. if k == 3 else .5
            trial[:] = states[n] if k == 0 else states[n]+fraction*dt*stages[k-1]
            Te,He,R = Input_AtTime(t+fraction*dt,environment,radius,tail,model==4,t>=14400-1e-9)
            _,code,_,_ = Operator_Evaluate(trial,R,Te,He,model,25.,8e-7,False,
                stages[k],props,rows,constant,xi,eta)
            if code: raise ValueError('INTERNAL_AUDIT_REPLAY_FAILED: invalid RK stage')
        states[n+1] = states[n]+dt/6*(stages[0]+2*stages[1]+2*stages[2]+stages[3])
        t = ends[n]
    return states


@njit(cache=True)
def Audit_ReconstructRadial(state,faces,R,Te,He,model):
    """Exact 1D specialization of Sampling_Reconstruct (no repeated axial copies)."""
    physical=faces*R; centers=(physical[:-1]+physical[1:])/2
    a,b=Geometry_GetSymmetryWeights(physical,True)
    values=np.empty((2,state.shape[1]+2)); values[:,1:-1]=state[:,:,0]
    values[:,0]=a*state[:,0,0]+b*state[:,1,0]
    props=Material_Evaluate(model,state[0,-1,0],state[1,-1,0])
    for p in range(2):
        values[p,-1]=Boundary_Reconstruct(state[p,-1,0],Te if p==0 else He,
            props[p+2],R-centers[-1],25. if p==0 else 8e-7)
    return values


@njit(cache=True)
def Audit_MeasureStates(a,b,t,xa,xb,model,environment,radius,tail):
    Te,He,R = Input_AtTime(t,environment,radius,tail,model==4)
    va = Audit_ReconstructRadial(a,xa,R,Te,He,model)
    vb = Audit_ReconstructRadial(b,xb,R,Te,He,model)
    if t == 0:
        va[0,:]=a[0,0,0]; va[1,:]=a[1,0,0]
        vb[0,:]=b[0,0,0]; vb[1,:]=b[1,0,0]
    ra = np.concatenate((np.array([0.]),(xa[:-1]+xa[1:])*R/2,np.array([R])))
    rb = np.concatenate((np.array([0.]),(xb[:-1]+xb[1:])*R/2,np.array([R])))
    union = np.unique(np.concatenate((ra,rb)))
    official = np.concatenate((np.arange(21)*.001,np.array([R])))
    official = official[official <= R+1e-14]
    weights = np.diff(xb**2)
    result = np.zeros((6,6))
    for p in range(2):
        for group in range(2):
            positions = union if group == 0 else official
            left = np.interp(positions,ra,va[p]); right = np.interp(positions,rb,vb[p])
            delta = right-left; i = np.argmax(np.abs(delta))
            result[p*2+group] = np.array([abs(delta[i]),t,positions[i],left[i],right[i],delta[i]])
        delta = vb[p,1:-1]-np.interp(rb[1:-1],ra,va[p])
        result[4+p] = np.array([np.sqrt(np.sum(weights*delta**2)/np.sum(weights)),t,0.,0.,0.,0.])
    return result


@njit(cache=True)
def Audit_CompareInterval(a,b,start,ea,eb,xa,xb,model,environment,radius,tail):
    aa = Audit_ReplayInterval(a,start,ea,xa,model,environment,radius,tail)
    bb = Audit_ReplayInterval(b,start,eb,xb,model,environment,radius,tail)
    ta = np.concatenate((np.array([start]),ea)); tb = np.concatenate((np.array([start]),eb))
    targets = np.unique(np.concatenate((ta,tb)))
    peaks = np.full((6,6),-1.); ia=0; ib=0
    for t in targets:
        while ia+1 < len(ta)-1 and ta[ia+1] < t: ia += 1
        while ib+1 < len(tb)-1 and tb[ib+1] < t: ib += 1
        ua = aa[ia]+(aa[ia+1]-aa[ia])*((t-ta[ia])/(ta[ia+1]-ta[ia]))
        ub = bb[ib]+(bb[ib+1]-bb[ib])*((t-tb[ib])/(tb[ib+1]-tb[ib]))
        values = Audit_MeasureStates(ua,ub,t,xa,xb,model,environment,radius,tail)
        for k in range(6):
            if values[k,0] > peaks[k,0]: peaks[k] = values[k]
    return peaks,aa[-1],bb[-1],len(targets)-1


def Audit_IterIntervals(root,case_id):
    status = Case_ReadStatus(root,case_id)
    if status.get('execution_mode') == 'stage_schedule':
        for stage in status['stages']:
            yield from Audit_IterIntervals(root,stage['case_id'])
        return
    mesh = Case_LoadMesh(root,case_id); previous = None
    for path in sorted((Path(root)/'work/cache'/case_id).glob('chunk_*.npz')):
        with np.load(path) as data:
            if str(data['fingerprint']) != status['fingerprint']:
                raise RuntimeError('CACHE_MISMATCH: internal audit block')
            times,fields,ends = data['time_s'],data['fields'],data['step_ends']
        for t,field in zip(times,fields):
            if previous is not None:
                start,initial = previous
                steps = ends[(ends>start+1e-9)&(ends<=t+1e-9)]
                if not len(steps) or abs(steps[-1]-t)>1e-8:
                    raise RuntimeError('INTERNAL_AUDIT_INCOMPLETE: missing accepted partition')
                yield float(start),float(t),initial,field,steps,mesh[0]
            previous = float(t),field


def Audit_GetMetric(row,volume=False):
    result = dict(value=float(row[0]),time_s=float(row[1]))
    if not volume:
        result.update(r_m=float(row[2]),z_m=0.,coarse_value=float(row[3]),fine_value=float(row[4]),signed_difference=float(row[5]))
    return result


def Audit_GetSourceIdentity(root):
    """Separate numerical replay identity from acceptance/reporting policy."""
    import ast
    root = Path(root)
    names = {'Audit_ReplayInterval','Audit_ReconstructRadial','Audit_MeasureStates',
             'Audit_CompareInterval','Audit_IterIntervals','Audit_GetMetric'}
    tree = ast.parse((root/'src/drying/audit.py').read_text(encoding='utf-8'))
    bundle = '\n'.join(ast.dump(n,include_attributes=False) for n in tree.body
        if isinstance(n,(ast.Import,ast.ImportFrom)) or isinstance(n,ast.FunctionDef) and n.name in names)
    comparison = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='Audit_CompareCaches')
    start = next(i for i,n in enumerate(comparison.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='streams' for t in n.targets))
    bundle += ast.dump(ast.Module(body=comparison.body[start:],type_ignores=[]),include_attributes=False)
    digest = hashlib.sha256(bundle.encode()).hexdigest()
    reference = root/'configs/audit_solver_reference.json'
    if reference.exists():
        saved = json.loads(reference.read_text(encoding='utf-8'))
        if saved['numerical_ast_hash']==digest:
            return saved['legacy_source_hash'],saved['compatible_producer_hashes']
    return digest,[]


def Audit_CompareCaches(root,coarse_id,fine_id,cap=None):
    root=Path(root); sa=Case_ReadStatus(root,coarse_id); sb=Case_ReadStatus(root,fine_id)
    if sa['dim'] != 1 or sb['dim'] != 1:
        raise ValueError('INTERNAL_AUDIT_INCOMPLETE: replay audit supports 1D only')
    end = min(sa['cap'],sb['cap'],float('inf') if cap is None else cap)
    source_hash,compatible_hashes = Audit_GetSourceIdentity(root)
    signature = dict(coarse=sa['fingerprint'],fine=sb['fingerprint'],end=end,audit_source_hash=source_hash)
    digest=hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest()
    path=root/f'work/validation/internal_audits/{digest}.json'
    if path.exists(): return json.loads(path.read_text(encoding='utf-8'))
    for producer_hash in compatible_hashes:
        old_signature = dict(signature,audit_source_hash=producer_hash)
        old_digest = hashlib.sha256(json.dumps(old_signature,sort_keys=True).encode()).hexdigest()
        previous = root/f'work/validation/internal_audits/{old_digest}.json'
        if previous.exists():
            saved = json.loads(previous.read_text(encoding='utf-8'))
            if saved.get('complete') and all(saved.get(k)==v for k,v in old_signature.items()):
                return saved
    streams=[iter(Audit_IterIntervals(root,c)) for c in [coarse_id,fine_id]]
    a,b=[next(s,None) for s in streams]
    peaks=np.full((6,6),-1.); count=1; cursor=0.; drift=0.; began=time.perf_counter(); last=began
    early_peaks=peaks.copy(); inputs=Case_LoadInputs(root); model=dict(q1=1,q23=3,q4=4)[sa['case']]
    switch_errors=[]
    switches=set(s['t_start'] for status in [sa,sb] for s in status.get('stages',[])[1:])
    while a is not None and b is not None and cursor < end-1e-8:
        if abs(a[0]-b[0])>1e-8 or abs(a[1]-b[1])>1e-8 or abs(a[0]-cursor)>1e-8 or a[1]>end+1e-8:
            raise RuntimeError('INTERNAL_AUDIT_INCOMPLETE: unmatched saved intervals')
        values,final_a,final_b,number=Audit_CompareInterval(a[2],b[2],a[0],a[4],b[4],a[5],b[5],model,*inputs)
        drift=max(drift,float(np.max(abs(final_a-a[3]))),float(np.max(abs(final_b-b[3]))))
        if drift>1e-8: raise RuntimeError(f'INTERNAL_AUDIT_REPLAY_FAILED: saved endpoint mismatch {drift}')
        peaks=np.where((values[:,0]>peaks[:,0])[:,None],values,peaks)
        if a[1] <= 600+1e-8: early_peaks=np.where((values[:,0]>early_peaks[:,0])[:,None],values,early_peaks)
        if a[0] in switches:
            instant=Audit_MeasureStates(a[2],b[2],a[0],a[5],b[5],model,*inputs)
            switch_errors.append(dict(time_s=a[0],temperature=Audit_GetMetric(instant[1]),moisture=Audit_GetMetric(instant[3]),
                first_interval_temperature=Audit_GetMetric(values[1]),first_interval_moisture=Audit_GetMetric(values[3])))
        cursor=a[1]; count+=number
        if time.perf_counter()-last>20:
            print(f'INTERNAL_AUDIT {sa["case"]} {sa["nr"]}/{sb["nr"]} t={cursor:g}/{end:g}s',flush=True); last=time.perf_counter()
        a,b=[next(s,None) for s in streams]
    if abs(cursor-end)>1e-8: raise RuntimeError('INTERNAL_AUDIT_INCOMPLETE: time coverage')
    result=dict(**signature,complete=True,time_range_s=[0.,end],sample_count=count,replay_endpoint_max_abs=drift,
        temperature=Audit_GetMetric(peaks[1]),moisture=Audit_GetMetric(peaks[3]),
        full_field_temperature=Audit_GetMetric(peaks[0]),full_field_moisture=Audit_GetMetric(peaks[2]),
        volume_L2_temperature=Audit_GetMetric(peaks[4],True),volume_L2_moisture=Audit_GetMetric(peaks[5],True),
        early_600s_temperature=Audit_GetMetric(early_peaks[1]),early_600s_moisture=Audit_GetMetric(early_peaks[3]),
        switch_errors=switch_errors,wall_s=time.perf_counter()-began,
        method='All accepted step endpoints from both trajectories; exact RK4 partition replay; linear temporal interpolation of the other trajectory; union of physical radial nodes for Linf. Both sides of remesh boundaries checked. Not a continuous-time bound.')
    Storage_WriteJson(path,result)
    return result


def Audit_AttachComparison(root,value,cap=None):
    audit=Audit_CompareCaches(root,value['coarse_id'],value['fine_id'],cap)
    value['all_internal_times_max_error']=audit
    value['saved_times_max_error']=dict(temperature=value['official_temperature'],moisture=value['official_moisture'])
    formal=value.get('official_output_times_max_error')
    if formal is not None:
        value['official_temperature']=formal['temperature']; value['official_moisture']=formal['moisture']
    value['internal_audit_veto']=False
    return value
