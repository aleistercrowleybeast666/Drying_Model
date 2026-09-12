"""Optional 60 x 188 refinement, with a measured cost gate and honest partial status."""
from pathlib import Path
import logging
import numpy as np
from ..cases import Case_Solve, Case_LoadConfig, Case_LoadInputs, Case_LoadMesh
from ..validation import Validation_GetEndpointState, Validation_CompareCaches
from ..sampling import Sampling_GetNodes
from ..geometry import Geometry_GetCells
from ..storage import Storage_WriteJson, Storage_WriteArray
from .baseline import Baseline_ReadJson, Baseline_Check, Baseline_HashFile
from .metrics import Metrics_GetEndEffects


def Refinement_Compare(root, case, frozen, fine):
    coarse=frozen['selected'][case+'_2d'];one=frozen['selected'][case+'_1d'];inputs=Case_LoadInputs(root)
    comparison,rows=Validation_CompareCaches(root,coarse['case_id'],fine['case_id'])
    target=Path(root)/'work/studies/technical/refinement2d'/case
    Storage_WriteArray(target/'comparison.npz',values=np.array(rows))
    times=sorted(set([0.,1800.,10800.,86400.,172800.,259200.]+[s['event']['report_s'] for s in [coarse,fine,one] if s.get('event')]))
    records=[];model=3 if case=='q23' else 4
    for t in times:
        one_state=Validation_GetEndpointState(root,one['case_id'],t)
        ro,zo,no=Sampling_GetNodes(one_state,t,model,inputs,Case_LoadMesh(root,one['case_id'],t))
        for label,status in [('40x125',coarse),('60x188',fine)]:
            state=Validation_GetEndpointState(root,status['case_id'],t);mesh=Case_LoadMesh(root,status['case_id'],t)
            r,z,nodes=Sampling_GetNodes(state,t,model,inputs,mesh)
            rc,zc,volumes=Geometry_GetCells(*state.shape[1:],r[-1],mesh=mesh)
            one_at_cells=np.array([np.interp(rc,ro,no[f,:,0]) for f in [0,1]])
            errors=state-one_at_cells[:,:,None]
            metrics=Metrics_GetEndEffects(errors[0],errors[1],volumes,zc)
            ties=np.argwhere(np.abs(nodes[1]-nodes[1].max())<=1e-9)
            metrics.update(time_s=t,grid=label,source_case_id=status['case_id'],Cmax=float(nodes[1].max()),
                controlling_r_range_m=[float(r[ties[:,0]].min()),float(r[ties[:,0]].max())],
                controlling_z_range_m=[float(z[ties[:,1]].min()),float(z[ties[:,1]].max())],tied_node_count=len(ties),
                official_1d_id=one['case_id'],comparison_scope='same formal 1D reconstructed at 2D cell centers; includes radial discretization discrepancy')
            for f,key in [(0,'T'),(1,'C')]:
                metrics['max_local_1d_2d_delta_'+key]=float(np.max(np.abs(nodes[f]-np.interp(r,ro,no[f,:,0])[:,None])))
            records.append(metrics)
    result=dict(comparison=comparison,representative_results=records,
        own_endpoints={name:next((r for r in records if r['grid']==name and status.get('event') and abs(r['time_s']-status['event']['report_s'])<1e-8),None)
            for name,status in [('40x125',coarse),('60x188',fine)]},
        status='2D_FULL_TRAJECTORY_REFINED',independent_grid_certification=False,
        scope='one complete refinement only; not 2D_SPATIAL_CONVERGED',
        source_case_id=fine['case_id'],coarse_id=coarse['case_id'],
        data_path=(target/'comparison.npz').relative_to(root).as_posix(),data_sha256=Baseline_HashFile(target/'comparison.npz'))
    Storage_WriteJson(target/'comparison.json',result)
    return result


def Refinement_Run(root, args):
    from .technical_run import TechnicalRunResult
    root=Path(root);frozen=Baseline_ReadJson(root/'work/baseline_snapshot/baseline_manifest.json')
    config=Case_LoadConfig(root);folder=root/'work/studies/technical/refinement2d';path=folder/'index.json'
    if args.payload_only:
        if not path.exists():raise RuntimeError('REFINEMENT_REPORT_MISSING: run compute_studies.py --group refine2d --resume')
        print('REFINEMENT_REPORT_REUSED '+Baseline_ReadJson(path)['status'],flush=True)
        return TechnicalRunResult.COMPLETE
    selected_cases=[args.case] if args.case in ['q23','q4'] else ['q23','q4']
    if args.dry_run:
        print('Q3/Q4 60x188: original initial state; 60 s cost probe; 1 h projected wall budget per full case; no larger grid')
        return TechnicalRunResult.COMPLETE
    report=Baseline_ReadJson(path) if path.exists() else dict(study_id='optional_full_2d_60x188',cases={})
    logging.basicConfig(level=logging.INFO,format='%(message)s')
    for case in selected_cases:
        original=frozen['selected'][case+'_2d']
        if config['physics']!=original['physics']:raise RuntimeError('FROZEN_2D_PHYSICS_MISMATCH')
        if (root/'work/studies/STOP').exists():return TechnicalRunResult.STOPPED
        record=dict(status='PARTIAL_2D',attempted=True,grid=[60,188],start_time_s=0.,initial_state='original uniform T0=301.15 K, C0=2.55',
            coarse_source_case_id=original['case_id'],input_hash=original['input_hash'],physics=original['physics'],
            monitor_source='same frozen continuous radial/axial monitors; Mesh_BuildAdaptive',
            projected_wall_budget_s=3600.,complete_full_trajectory=False,independent_grid_certification=False)
        try:
            probe=Case_Solve(root,case,2,nr=60,nz=188,dt=.25,tag='technical60x188_cost_probe',cap=60.,mesh_mode='adaptive')
            for axis in ['radial','axial']:
                if probe[axis+'_monitor_hash']!=original[axis+'_monitor_hash']:raise RuntimeError('FROZEN_2D_MONITOR_MISMATCH')
            # Warm-up is reported separately by Case_Solve, never multiplied into the projection.
            projection=probe['wall_s']/60.*259200.
            source_folder=root/'work/cache'/probe['case_id']
            source_paths=[source_folder/'status.json',source_folder/'mesh.npz',*sorted(source_folder.glob('chunk_*.npz'))]
            record['source_files']=[dict(path=p.relative_to(root).as_posix(),sha256=Baseline_HashFile(p),purpose='independent 2D cost probe') for p in source_paths]
            record['source_file']=(source_folder/'status.json').relative_to(root).as_posix()
            record.update(probe_source_case_id=probe['case_id'],probe_simulated_s=60.,probe_wall_s=probe['wall_s'],
                compile_or_load_s=probe['compile_or_load_s'],projected_full_72h_wall_s=projection,
                cost_estimate_scope='linear scaling of measured first 60 s excluding compilation; not a guarantee, later stability/geometry may change',
                probe_actual_dt_min_s=probe['actual_dt_min'],probe_actual_dt_mean_s=probe['actual_dt_mean'])
            if getattr(args, 'refine_probe_only', False):
                record['reason']='MANDATORY_WORK_PRIORITY: only cost probe retained; full refinement deferred for the newly requested solver mass audit; no full-trajectory or grid-independence claim'
                partial_folder=root/'work/cache'/probe['case_id'].replace('cost_probe','full')
                if (partial_folder/'status.json').exists():
                    partial=Baseline_ReadJson(partial_folder/'status.json')
                    record['resumable_partial_full_case']=dict(source_case_id=partial['case_id'],
                        simulated_time_s=partial.get('simulated_time_s',0.),complete=partial.get('complete',False),
                        checkpoint='work/checkpoints/'+partial['case_id']+'/checkpoint.npz')
            elif projection>record['projected_wall_budget_s'] and not args.refine_force_full:
                record['reason']='COST_LIMIT: projected full trajectory exceeds optional per-case wall budget; retain PARTIAL_2D; no claim that a 60 s probe is a complete refinement'
            else:
                full=Case_Solve(root,case,2,nr=60,nz=188,dt=.25,tag='technical60x188_full',cap=259200.,mesh_mode='adaptive')
                if not full['complete'] or full['simulated_time_s']!=259200.:raise RuntimeError('FULL_2D_HISTORY_INCOMPLETE')
                source_folder=root/'work/cache'/full['case_id']
                source_paths=[source_folder/'status.json',source_folder/'mesh.npz',*sorted(source_folder.glob('chunk_*.npz'))]
                if full.get('event'):source_paths.append(source_folder/'event.npz')
                record['source_files'] += [dict(path=p.relative_to(root).as_posix(),sha256=Baseline_HashFile(p),purpose='independent full 2D trajectory') for p in source_paths]
                record.update(Refinement_Compare(root,case,frozen,full),complete_full_trajectory=True,full_wall_s=full['wall_s'],reason='one full 40x125 -> 60x188 comparison; grid independence remains uncertified')
        except Exception as exc:
            record.update(status='PARTIAL_2D',reason='OPTIONAL_2D_NUMERICAL_OR_RESOURCE_ISSUE: '+str(exc))
        report['cases'][case]=record
        report.update(status='2D_FULL_TRAJECTORY_REFINED' if len(report['cases'])==2 and all(v['complete_full_trajectory'] for v in report['cases'].values()) else 'PARTIAL_2D',
            independent_grid_certification=False,larger_grid_attempted=False)
        Storage_WriteJson(path,report);print('REFINEMENT_RESULT '+case+' '+record['status']+' '+record['reason'],flush=True)
        Baseline_Check(root)
    return TechnicalRunResult.COMPLETE
