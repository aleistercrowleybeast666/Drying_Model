"""Independent 2D evidence tasks calling the unchanged validation functions."""
import json
from pathlib import Path
from .storage import Storage_WriteJson


def TwoDimensional_GetPlan(case):
    prefix='B.2d.'+case
    parts=[('base',['A.'+case]),('time_half',[prefix+'.base']),('seed',[prefix+'.base']),
           ('radial',[prefix+'.seed']),('axial',[prefix+'.seed'])]
    if case!='q1':parts += [(f'endpoint.{axis}',[prefix+'.seed']) for axis in ['radial','axial']]
    jobs=[dict(key=prefix+'.'+part,kind='twod_'+part,case=case,group='validation',dependencies=deps,
               private='two_'+case+'_'+part.replace('.','_'),pde=True) for part,deps in parts]
    jobs.append(dict(key=prefix,kind='twod_assess',case=case,group='validation',dependencies=[j['key'] for j in jobs],pde=False))
    return jobs


def TwoDimensional_Read(root,case,part):
    return json.loads((Path(root)/f'work/validation/judge_2d/{case}/{part}.json').read_text(encoding='utf-8'))


def TwoDimensional_Execute(root,task):
    from .cases import Case_LoadConfig,Case_Solve,Case_ReadStatus,Case_SolvePairEvents
    from .validation import Validation_CheckTime,Validation_CheckEndpoint,Validation_CompareCaches,Validation_SaveComparison,Validation_SaveEntry
    from .comparison import Comparison_Run
    root=Path(root);case=task['case'];part=task['kind'].removeprefix('twod_')
    config=Case_LoadConfig(root);mc=config['mesh'];cfg=config['validation']
    output=root/f'work/validation/judge_2d/{case}/{part}.json'
    def Evidence_GetTimes():
        paths=[*(root/'work/cache').glob('*/status.json'),*(root/'work/cache').glob('*/paired_endpoints.npz'),
               *(root/'work/validation').glob('*_2d_endpoint_*.json')]
        return {p:p.stat().st_mtime_ns for p in paths}
    cached_before=Evidence_GetTimes()
    if part=='base':
        result=Case_Solve(root,case,2,nr=mc['base_nr'],nz=mc['base_nz'])
    else:
        base=Case_ReadStatus(root,TwoDimensional_Read(root,case,'base')['case_id'])
        if part=='time_half':result=Validation_CheckTime(root,base)
        elif part=='seed':
            production=json.loads((root/'work/recompute/production.json').read_text(encoding='utf-8'))[case]
            Validation_SaveEntry(root,case+'_1d',dict(selected_id=production['case_id'],selected_fingerprint=production['fingerprint'],numerical_status='NOT_RERUN_IN_TABLE_ONLY_MODE'))
            Validation_SaveEntry(root,case+'_2d',dict(selected_id=base['case_id'],selected_fingerprint=base['fingerprint']))
            Case_SolvePairEvents(root)
            comparisons=Comparison_Run(root,case)
            relevant=[v for v in comparisons.values() if v.get('one_id','').startswith(case+'_')]
            representative=sorted(set(float(v[k]['time_s']) for v in relevant for k in ['max_abs_temperature','max_abs_moisture']))
            policy=json.loads((root/'configs/auxiliary_2d_validation.json').read_text(encoding='utf-8'))
            cap=min(base['cap'],max([cfg['two_dimensional_refinement_duration_s'],policy['critical_window_end_s'][case],*representative]))
            result=dict(representative_times_s=representative,cap=cap)
        elif part in ['radial','axial']:
            seed=TwoDimensional_Read(root,case,'seed');cap=seed['cap']
            nr,nz=(mc['refined_nr'],base['nz']) if part=='radial' else (base['nr'],mc['refined_nz'])
            fine=Case_Solve(root,case,2,nr=nr,nz=nz,tag=f'{part}_verification_t{cap:g}',cap=cap)
            result,rows=Validation_CompareCaches(root,base['case_id'],fine['case_id'])
            result.update(assessment='QUANTIFIED',representative_times_s=seed['representative_times_s'],
                note='Separate directional refinement; no combined-direction full-time certificate.')
            Validation_SaveComparison(root,f'{case}_2d_{part}',result,rows)
        elif part.startswith('endpoint.'):
            direction=part.split('.')[1]
            nr,nz=(mc['refined_nr'],base['nz']) if direction=='radial' else (base['nr'],mc['refined_nz'])
            result=Validation_CheckEndpoint(root,base,nr,nz,direction)
        elif part=='assess':
            seed=TwoDimensional_Read(root,case,'seed');temporal=TwoDimensional_Read(root,case,'time_half')
            result=dict(selected_id=base['case_id'],selected_fingerprint=base['fingerprint'],selected_nr=base['nr'],
                time_passed=temporal['passed'],time_full_time=case=='q1',temporal=temporal,
                spatial_quantified=True,spatial_full_time=case=='q1',spatial_passed=False,
                radial=TwoDimensional_Read(root,case,'radial'),axial=TwoDimensional_Read(root,case,'axial'),
                endpoint_sensitivity=[] if case=='q1' else [TwoDimensional_Read(root,case,'endpoint.'+axis) for axis in ['radial','axial']],
                representative_times_s=seed['representative_times_s'],early_refinement_end_s=seed['cap'],
                numerical_status='2D_SPATIAL_VALIDATION_PARTIAL',eligible_1d_export=False,
                spatial_acceptance_note='Separate early/maximum-error refinements and local late-event sensitivity; full-trajectory double-grid convergence unverified.')
            Validation_SaveEntry(root,case+'_2d',result)
        else:raise ValueError('UNKNOWN_2D_COMPONENT: '+part)
    Storage_WriteJson(output,result)
    unchanged=Evidence_GetTimes()==cached_before
    return dict(component=part,case=case,evidence=result,cache_reused=unchanged,
                note='Unchanged numerical routines; acceptance only in final auxiliary evaluation')
