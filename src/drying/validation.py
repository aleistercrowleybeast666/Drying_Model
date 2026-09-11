"""Mesh-aware time checks and explicit spatial acceptance; no tolerance fitting."""
import csv
import json
import os
import time
from pathlib import Path
import numpy as np
from scipy.interpolate import RegularGridInterpolator
from .cases import Case_IterFields, Case_LoadConfig, Case_LoadInputs, Case_LoadMesh, Case_ReadStatus, Case_Solve, Case_GetSchedule
from .sampling import Sampling_GetNodes
from .geometry import Geometry_GetCells
from .storage import Storage_WriteJson, Storage_WriteArray
from .diagnostics import Diagnostics_Record


def Validation_IterReference(root, status):
    """Read separately verified old uniform data, never a production cache."""
    for path in sorted((Path(root)/'work/cache'/status['case_id']).glob('chunk_*.npz')):
        with np.load(path) as data:
            if str(data['fingerprint']) != status['fingerprint']:
                raise RuntimeError('CACHE_MISMATCH: uniform reference block')
            times, fields = data['time_s'], data['fields']
        yield from zip(times.tolist(), fields)


def Validation_GetMaximum(delta, coarse, fine, r, z, t):
    i = np.unravel_index(np.abs(delta).argmax(), delta.shape)
    return dict(value=float(abs(delta[i])), signed_difference=float(delta[i]), time_s=float(t),
        r_m=float(r[i[0]]), z_m=float(z[i[1]]), coarse_value=float(coarse[i]), fine_value=float(fine[i]))


def Validation_CompareCaches(root, coarse_id, fine_id, legacy_reference=None):
    sa = legacy_reference or Case_ReadStatus(root, coarse_id)
    sb = Case_ReadStatus(root, fine_id)
    model = dict(q1=1,q23=3,q4=4)[sa['case']]; inputs = Case_LoadInputs(root)
    ma = None if legacy_reference else Case_LoadMesh(root, coarse_id)
    mb = Case_LoadMesh(root, fine_id)
    maxima = [dict(value=-1.),dict(value=-1.)]; official = [dict(value=-1.),dict(value=-1.)]
    l2 = [dict(value=-1.),dict(value=-1.)]; rows = []
    coarse = iter(Validation_IterReference(root,sa) if legacy_reference else Case_IterFields(root,coarse_id))
    fine = iter(Case_IterFields(root,fine_id)); a,b = next(coarse,None),next(fine,None)
    while a is not None and b is not None:
        if abs(a[0]-b[0]) > 1e-8:
            if a[0] < b[0]: a = next(coarse,None)
            else: b = next(fine,None)
            continue
        t = a[0]
        if sa.get('execution_mode') == 'stage_schedule': ma = Case_LoadMesh(root,coarse_id,t)
        if sb.get('execution_mode') == 'stage_schedule': mb = Case_LoadMesh(root,fine_id,t)
        ra,za,va = Sampling_GetNodes(a[1],t,model,inputs,ma)
        rb,zb,vb = Sampling_GetNodes(b[1],t,model,inputs,mb)
        rr,zz = np.meshgrid(rb,zb,indexing='ij'); coordinates = np.column_stack((rr.ravel(),zz.ravel()))
        fixed = np.arange(21)*.001; radii = np.unique(np.r_[fixed[fixed <= rb[-1]+1e-14],rb[-1]])
        # 1D official radii and true surface; 2D also spans all reconstructed axial nodes.
        ro,zo = np.meshgrid(radii,zb,indexing='ij'); co = np.column_stack((ro.ravel(),zo.ravel()))
        weights = Geometry_GetCells(b[1].shape[1],b[1].shape[2],rb[-1],mesh=mb)[2]
        metrics = []
        for p in range(2):
            interp = RegularGridInterpolator((ra,za),va[p],bounds_error=True)
            interpolated = interp(coordinates).reshape(rr.shape); delta = vb[p]-interpolated
            peak = Validation_GetMaximum(delta,interpolated,vb[p],rb,zb,t)
            if peak['value'] > maxima[p]['value']: maxima[p] = peak
            ca = interp(co).reshape(ro.shape)
            fb = RegularGridInterpolator((rb,zb),vb[p])(co).reshape(ro.shape)
            point = Validation_GetMaximum(fb-ca,ca,fb,radii,zb,t)
            if point['value'] > official[p]['value']: official[p] = point
            rms = float(np.sqrt(np.sum(weights*delta[1:-1,1:-1]**2)/weights.sum()))
            if rms > l2[p]['value']: l2[p] = dict(value=rms,time_s=float(t))
            metrics.extend([peak['value'],point['value'],rms])
        rows.append((t,*metrics)); a,b = next(coarse,None),next(fine,None)
    if not rows: raise RuntimeError('SPATIAL_REFERENCE_INCOMPLETE: no common sampled times')
    applicable = sa['cap'] == sb['cap']; difference = relative = None
    if applicable and sa['event'] and sb['event']:
        difference = abs(sa['event']['raw_event_s']-sb['event']['raw_event_s'])
        relative = difference/sb['event']['raw_event_s']
    expected_times = Case_GetSchedule(sa['case'],min(sa['cap'],sb['cap']))
    extra_a = [s['t_start'] for s in sa.get('stages',[])]
    extra_b = [s['t_start'] for s in sb.get('stages',[])]
    expected_times = np.intersect1d(np.unique(np.r_[expected_times,extra_a]),np.unique(np.r_[expected_times,extra_b]))
    complete = bool(sa['complete'] and sb['complete'] and len(rows) == len(expected_times) and
                    np.allclose(np.asarray(rows)[:,0],expected_times,rtol=0,atol=1e-8))
    return dict(coarse_id=coarse_id,fine_id=fine_id,coarse_fingerprint=sa['fingerprint'],fine_fingerprint=sb['fingerprint'],
        maxima_temperature=maxima[0],maxima_moisture=maxima[1],official_temperature=official[0],official_moisture=official[1],
        volume_L2_temperature=l2[0],volume_L2_moisture=l2[1],event_difference_s=difference,event_relative_difference=relative,
        event_status_agrees=(bool(sa['event']) == bool(sb['event'])) if applicable else True,
        event_comparison_applicable=applicable,reference_complete=complete,
        time_range_s=[rows[0][0],rows[-1][0]],sample_count=len(rows),
        method='Same saved times; piecewise bilinear physical-coordinate reconstruction; official r=0:0.001:0.020 m plus true R(t); outside points excluded; volume-normalized L2 at fine cell centers',
        scope_note='Sampled-time maxima, not a continuous-time bound. Spatial refinement may activate different unchanged RK4 safety partitions.'),rows


def Validation_SaveComparison(root, name, value, rows):
    folder = Path(root)/'work/validation'; folder.mkdir(parents=True,exist_ok=True)
    Storage_WriteJson(folder/f'{name}.json',value)
    with (folder/f'{name}.csv').open('w',newline='',encoding='utf-8-sig') as stream:
        writer = csv.writer(stream)
        writer.writerow(['time_s','T_Linf_K','T_official_K','T_volume_L2_K','C_Linf','C_official','C_volume_L2'])
        writer.writerows(rows)


def Validation_SaveEntry(root, key, entry):
    """Merge independent case validations without losing another completed case."""
    folder = Path(root)/'work/validation'; folder.mkdir(parents=True,exist_ok=True)
    path = folder/'summary.json'; lock = folder/'summary.lock'
    deadline = time.monotonic()+30
    while True:
        try:
            handle = os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
            break
        except FileExistsError:
            if time.monotonic() > deadline:
                raise RuntimeError('VALIDATION_SUMMARY_LOCKED: another writer has not released its lock')
            time.sleep(.05)
    try:
        summary = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        summary[key] = entry; Storage_WriteJson(path,summary)
        return summary
    finally:
        os.close(handle); lock.unlink()


def Validation_AssessSpatial(value, thresholds, needs_event):
    reasons = []
    if not value['reference_complete']: reasons.append('SPATIAL_REFERENCE_INCOMPLETE')
    if value['official_temperature']['value'] > thresholds['temperature_abs_K']: reasons.append('OFFICIAL_T_EXCEEDS_TOLERANCE')
    if value['official_moisture']['value'] > thresholds['moisture_abs']: reasons.append('OFFICIAL_C_EXCEEDS_TOLERANCE')
    if needs_event and value['event_relative_difference'] is None:
        reasons.append('SPATIAL_REFERENCE_INCOMPLETE: drying event unavailable')
    elif needs_event and value['event_relative_difference'] > thresholds['drying_time_relative']:
        reasons.append('DRYING_TIME_EXCEEDS_TOLERANCE')
    value.update(passed=not reasons,failure_reasons=reasons,thresholds=thresholds,assessment='PASS' if not reasons else 'FAIL')
    return value


def Validation_CheckTime(root, base):
    """Retain actual-partition bisection, tolerances and optional second bisection."""
    cfg = Case_LoadConfig(root)['validation']
    cap = None if base['dim'] == 1 else cfg['two_dimensional_refinement_duration_s']
    def Passed(value):
        return (value['reference_complete'] and value['maxima_temperature']['value'] <= cfg['temperature_tolerance_K']
            and value['maxima_moisture']['value'] <= cfg['moisture_tolerance'] and value['event_status_agrees']
            and (value['event_difference_s'] is None or value['event_difference_s'] <= cfg['event_tolerance_s']))
    staged = base.get('execution_mode') == 'stage_schedule'
    def SolveReference(parent, label):
        if staged:
            from .stages import Stage_Solve
            return Stage_Solve(root,base['case'],base['schedule'],dt=parent['dt']/2,replay_id=parent['case_id'],label=label)
        return Case_Solve(root,base['case'],base['dim'],nr=base['nr'],nz=base['nz'],dt=parent['dt']/2,
            tag=label,replay_id=parent['case_id'],cap=cap,mesh_mode=base['mesh_mode'])
    fine = SolveReference(base,'half_steps')
    result,rows = Validation_CompareCaches(root,base['case_id'],fine['case_id'])
    result.update(passed=Passed(result),actual_base_partition_bisected=True,requested_dt_s=fine['dt'])
    prefix = f"{base['case']}_{base['dim']}d_"+('stage_' if staged else '')
    Validation_SaveComparison(root,prefix+'time_half',result,rows)
    if not result['passed']:
        quarter = SolveReference(fine,'quarter_steps')
        second,rows = Validation_CompareCaches(root,fine['case_id'],quarter['case_id'])
        second.update(passed=Passed(second),actual_base_partition_bisected=True,requested_dt_s=quarter['dt'])
        Validation_SaveComparison(root,prefix+'time_quarter',second,rows)
        result['quarter_check'] = second
        Diagnostics_Record(root,'TIME_CONVERGENCE_FAILED','WARNING',case_id=base['case_id'],
            half_vs_quarter_passed=second['passed'],reason='Production requested dt retained; its own bisection failed.')
    return result


def Validation_ProjectAverages(state, source_mesh, target_mesh):
    """Conservative overlap projection ONLY for a local endpoint diagnostic."""
    matrices = []
    for axis,(old,new) in enumerate(zip(source_mesh,target_mesh)):
        a,b = (np.asarray(old)**2,np.asarray(new)**2) if axis == 0 else (np.asarray(old),np.asarray(new))
        overlap = np.maximum(0.,np.minimum(b[1:,None],a[None,1:])-np.maximum(b[:-1,None],a[None,:-1]))
        matrices.append(overlap/np.diff(b)[:,None])
    return np.stack([matrices[0]@field@matrices[1].T for field in state])


def Validation_CheckEndpoint(root, base, nr, nz, direction):
    from .mesh import Mesh_BuildAdaptive
    from .rk4 import Rk4_Advance
    from .events import Event_Locate
    from .comparison import Comparison_ReadSnapshot
    root = Path(root); cfg = Case_LoadConfig(root); num = cfg['numerics']; spatial = cfg['validation']['spatial']
    if not base.get('event'):
        return dict(status='SPATIAL_REFERENCE_INCOMPLETE',reason='No base drying event',direction=direction)
    source_mesh = Case_LoadMesh(root,base['case_id'])
    mesh,meta = Mesh_BuildAdaptive(root,base['case'],nr,nz,base['mesh_mode'])
    path = root/f"work/validation/{base['case']}_2d_endpoint_{direction}.json"
    end = min(base['cap'],base['event']['report_s']+spatial.get('endpoint_tail_s',600.))
    start = max(0.,np.floor((base['event']['raw_event_s']-spatial.get('endpoint_window_s',3600.))/60)*60)
    saved = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if (saved.get('base_fingerprint') == base['fingerprint'] and saved.get('mesh_profile_hash') == meta['mesh_profile_hash']
            and saved.get('time_range_s') == [start,end] and saved.get('complete')):
        return saved
    original = Comparison_ReadSnapshot(root,base['case_id'],start)
    state = Validation_ProjectAverages(original,source_mesh,mesh)
    old_integrals = np.array([np.sum(f*Geometry_GetCells(base['nr'],base['nz'],1.,mesh=source_mesh)[2]) for f in original])
    new_integrals = np.array([np.sum(f*Geometry_GetCells(nr,nz,1.,mesh=mesh)[2]) for f in state])
    inputs = Case_LoadInputs(root); model = dict(q1=1,q23=3,q4=4)[base['case']]
    def Advance(state,a,b):
        result = Rk4_Advance(state,a,b,num['dt_s'],model,*inputs,model==4,True,
            num['safety'],num['min_dt_s'],num['max_rejections'],max(10000,int((b-a)/.001)+100),
            min(301.15,inputs[0][:,1].min(),inputs[2][0]),max(301.15,inputs[0][:,1].max(),inputs[2][0]),
            np.empty(0),xi_faces=mesh[0],eta_faces=mesh[1])
        if result[4]: raise RuntimeError('SPATIAL_REFERENCE_INCOMPLETE: local endpoint integration failed')
        return result
    began = time.perf_counter(); t = start; event = None; steps = limited = 0
    while t < end-1e-8:
        result = Advance(state,t,min(end,t+60.))
        state,t = result[0],float(result[1]); steps += len(result[2]); limited += int(result[5])
        if result[6] >= 0 and event is None:
            event,event_state = Event_Locate(result[6],result[7],result[8],Advance,model,inputs,mesh=mesh)
            Storage_WriteArray(path.with_suffix('.npz'),state=event_state,time_s=event['report_s'],
                xi_faces=mesh[0],eta_faces=mesh[1],base_fingerprint=base['fingerprint'])
    delta = abs(event['raw_event_s']-base['event']['raw_event_s']) if event else None
    value = dict(complete=True,status='2D_SPATIAL_VALIDATION_PARTIAL' if event else 'SPATIAL_REFERENCE_INCOMPLETE',
        base_id=base['case_id'],base_fingerprint=base['fingerprint'],mesh_profile_hash=meta['mesh_profile_hash'],
        direction=direction,nr=nr,nz=nz,time_range_s=[start,end],event=event,event_difference_s=delta,
        event_relative_difference=delta/event['raw_event_s'] if event else None,wall_s=time.perf_counter()-began,
        steps=steps,limited=limited,projection_integral_difference=(new_integrals-old_integrals).tolist(),
        note='Conservative projection of base state then genuine fine-grid late-window integration; inherited earlier coarse-grid error is NOT measured. This cannot establish full-time spatial convergence.')
    Storage_WriteJson(path,value)
    return value


def Validation_Run(root, scope='all', case_filter='all'):
    root = Path(root); config = Case_LoadConfig(root); cfg = config['validation']; mc = config['mesh']
    dimensions = [1,2] if scope == 'all' else [int(scope[0])]
    path = root/'work/validation/summary.json'
    summary = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    for dim in dimensions:
        for case in ['q1','q23','q4']:
            if case_filter not in ('all',case): continue
            if dim == 1:
                levels = [Case_Solve(root,case,1,nr=n) for n in [mc['base_nr'],mc['refined_nr'],mc['verification_nr']]]
                pairs = []
                for coarse,fine in zip(levels[:-1],levels[1:]):
                    value,rows = Validation_CompareCaches(root,coarse['case_id'],fine['case_id'])
                    Validation_AssessSpatial(value,cfg['spatial'],case != 'q1')
                    Validation_SaveComparison(root,f"{case}_1d_spatial_{coarse['nr']}_{fine['nr']}",value,rows)
                    pairs.append(value)
                passed = pairs[-1]['passed']; base = levels[1] if passed else levels[2]
                entry = dict(selected_id=base['case_id'],selected_fingerprint=base['fingerprint'],selected_nr=base['nr'],
                    time_passed=False,time_full_time=True,spatial_passed=passed,spatial_quantified=True,
                    spatial_full_time=True,spatial_pairs=pairs,radial=pairs[-1],axial=None,
                    numerical_status='SPATIAL_PASS_TIME_PENDING' if passed else 'SPATIAL_CONVERGENCE_FAILED',
                    spatial_acceptance_note='Official physical samples plus relative drying time; full-field extrema reported separately.',
                    eligible_1d_export=True,candidate_only=not passed)
                summary = Validation_SaveEntry(root,f'{case}_1d',entry)
                if not passed:
                    Diagnostics_Record(root,'SPATIAL_CONVERGENCE_FAILED','WARNING',case_id=base['case_id'],
                        failure_reasons=pairs[-1]['failure_reasons'])
                temporal = Validation_CheckTime(root,base)
                from .mesh import Mesh_GetPilot
                legacy,_ = Mesh_GetPilot(root,case,'radial')
                uniform,rows = Validation_CompareCaches(root,legacy['case_id'],base['case_id'],legacy_reference=legacy)
                uniform['note'] = 'Selected adaptive grid versus verified old uniform nr=40; this delta alone does not establish accuracy.'
                Validation_SaveComparison(root,f'{case}_1d_vs_old_uniform',uniform,rows)
                entry.update(time_passed=temporal['passed'],temporal=temporal,old_uniform_comparison=uniform,
                    numerical_status='PASS' if passed and temporal['passed'] else 'SPATIAL_CONVERGENCE_FAILED' if not passed else 'TIME_CONVERGENCE_FAILED')
            else:
                base = Case_Solve(root,case,2,nr=mc['base_nr'],nz=mc['base_nz'])
                temporal = Validation_CheckTime(root,base)
                from .cases import Case_SolvePairEvents
                from .comparison import Comparison_Run
                Case_SolvePairEvents(root)
                comparisons = Comparison_Run(root,case)
                relevant = [v for v in comparisons.values() if v.get('one_id','').startswith(case+'_')]
                representative = sorted(set(float(v[key]['time_s']) for v in relevant
                    for key in ['max_abs_temperature','max_abs_moisture']))
                cap = min(base['cap'],max([cfg['two_dimensional_refinement_duration_s'],*representative]))
                refinements = []
                for direction,nr,nz in [('radial',mc['refined_nr'],base['nz']),('axial',base['nr'],mc['refined_nz'])]:
                    old_id = summary.get(f'{case}_2d',{}).get(direction,{}).get('fine_id')
                    fine = Case_ReadStatus(root,old_id) if old_id else None
                    if not (fine and fine['complete'] and fine['cap'] >= cap and fine['nr']==nr and fine['nz']==nz):
                        fine = Case_Solve(root,case,2,nr=nr,nz=nz,tag=f'{direction}_verification_t{cap:g}',cap=cap)
                    value,rows = Validation_CompareCaches(root,base['case_id'],fine['case_id'])
                    value.update(assessment='QUANTIFIED',representative_times_s=representative,
                        note='Separate directional refinement; no combined-direction full-time certificate.')
                    Validation_SaveComparison(root,f'{case}_2d_{direction}',value,rows); refinements.append(value)
                endpoints = [] if case == 'q1' else [Validation_CheckEndpoint(root,base,nr,nz,direction)
                    for direction,nr,nz in [('radial',mc['refined_nr'],base['nz']),('axial',base['nr'],mc['refined_nz'])]]
                entry = dict(selected_id=base['case_id'],selected_fingerprint=base['fingerprint'],selected_nr=base['nr'],
                    time_passed=temporal['passed'],time_full_time=case=='q1',temporal=temporal,
                    spatial_quantified=True,spatial_full_time=case=='q1',spatial_passed=False,
                    radial=refinements[0],axial=refinements[1],endpoint_sensitivity=endpoints,
                    representative_times_s=representative,early_refinement_end_s=cap,
                    numerical_status='2D_SPATIAL_VALIDATION_PARTIAL',eligible_1d_export=False,
                    spatial_acceptance_note='Separate early/maximum-error refinements and local late-event sensitivity; full-trajectory double-grid convergence unverified.')
                Diagnostics_Record(root,'2D_SPATIAL_VALIDATION_PARTIAL','WARNING',case_id=base['case_id'],
                    covered_refinement_time_s=[0,cap],endpoint_windows=[v.get('time_range_s') for v in endpoints])
            summary = Validation_SaveEntry(root,f'{case}_{dim}d',entry)
    return summary
