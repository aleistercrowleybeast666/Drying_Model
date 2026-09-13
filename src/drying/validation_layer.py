"""Independent D evidence from explicit production artifacts; no production fallback."""
import hashlib
import json
from pathlib import Path
from .artifact_contract import Artifact_Require,Artifact_Verify
from .dataset_layer import Dataset_GetSpec,Dataset_Read
from .storage import Storage_WriteJson


def Validation_GetReferenceSpec(root,task,production):
    spec=Dataset_GetSpec(root,task)
    source=production['spec']
    # Imported legacy data keep their true identity. Half-step replay must
    # always target that exact production rather than a newly computed alias.
    spec['baseline_id']=source['baseline_id']
    if task['experiment_kind']=='time_half':spec['replay']=source['experiment_id']
    prefix=spec['experiment_id'].rsplit('_',1)[0]
    for name in ['experiment_id','fingerprint','case_id']:spec.pop(name,None)
    digest=hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()
    spec.update(fingerprint=digest,experiment_id=prefix+'_'+digest[:12])
    if task.get('cross'):spec['case_id']=spec['experiment_id']
    return spec


def Validation_Execute(root,task):
    from .judge_tasks import Task_GetCaseSpec,Task_ArchiveReference
    from .studies.analysis import Analysis_ExtractSeries,Analysis_Compare
    from .studies.trajectory import Trajectory_GetSpec,Trajectory_Solve
    from .studies.cache import Cache_SealExperiment
    root=Path(root);entries=Artifact_Require(task['dataset_root'],task.get('requires',[]),'VALIDATION_PREREQUISITE_MISSING')
    prior=Artifact_Verify(task['dataset_root'],task['artifact']) if task.get('artifact') else {'complete':False}
    if prior['complete'] and not task.get('force_reference'):return dict(artifact_entry=prior['entry'],cache_reused=True,pde_solves=0)
    kind=task['validation_kind'];case=task.get('case');result={}
    if kind.startswith('m00_'):
        from .stages import Stage_AssessTransfers
        production=entries['official.'+case]['status'];left_spec=Task_GetCaseSpec(root,production)
        remesh=Stage_AssessTransfers(production['transfers'],dict(temperature_abs_K=.01,moisture_abs=.01))
        if kind=='m00_remesh':result=dict(status='PASS' if remesh['remesh_transfer_passed'] else 'FAIL',remesh=remesh)
        else:
            if kind=='m00_spatial':
                spec=Trajectory_GetSpec(root,case,kind='full_reference',factor=2)
                if task.get('force_reference'):Task_ArchiveReference(root,spec)
                reference=Cache_SealExperiment(root,spec,Trajectory_Solve(root,spec))
            else:
                from .table_solver import Table_SolveSchedule
                reference=Table_SolveSchedule(root,case,dt=.125,replay_id=production['case_id'],label='time_half')
                spec=Task_GetCaseSpec(root,reference,'time_half',production['case_id']);reference=dict(reference,full_history_verified=True)
            result=Analysis_Compare(root,left_spec,spec,Analysis_ExtractSeries(root,left_spec),Analysis_ExtractSeries(root,spec),
                production,reference,formal_end_s=min(production['actual_end_s'],reference.get('actual_end_s',production['actual_end_s'])))
            if kind=='m00_spatial':
                result['remesh']=remesh
                if not remesh['remesh_transfer_passed']:result['status']='FAIL'
    elif kind.startswith(('thermal_','cross_')):
        production=entries[task['requires'][0]];spec=Validation_GetReferenceSpec(root,task,production)
        if task.get('force_reference'):Task_ArchiveReference(root,spec)
        reference=Cache_SealExperiment(root,spec,Trajectory_Solve(root,spec,resume=True))
        result=Analysis_Compare(root,production['spec'],spec,Analysis_ExtractSeries(root,production['spec']),
            Analysis_ExtractSeries(root,spec),production['status'],reference)
    elif kind=='mass':
        from .studies.mass_balance import MassBalance_MeasureCase
        from .studies.mass_report import MassReport_Assess
        production=entries[task['requires'][0]];status=production['status']
        spec=production['spec'] or Task_GetCaseSpec(root,status)
        key=spec['experiment_id'];baseline=bool(spec.get('case_cache_id'))
        manifest=dict(specs={key:spec},statuses={key:status},series={key:dict(baseline=baseline)})
        result=MassBalance_MeasureCase(root,manifest,key,resume=not task.get('force_reference'))
        policy=Dataset_Read(root/'configs/mass_balance_policy.json')
        result=dict(result,**MassReport_Assess(result,policy))
    elif kind.startswith('twod_'):
        from .judge_twod import TwoDimensional_Execute
        if kind=='twod_assess':
            for c in ['q1','q23','q4']:TwoDimensional_Execute(root,dict(task,kind='twod_assess',case=c))
            from .auxiliary2d import Auxiliary_Evaluate
            result=Auxiliary_Evaluate(root)
            result['status']='PASS' if result['two_dimensional_auxiliary_validation_passed'] else 'FAIL'
        else:
            result=TwoDimensional_Execute(root,dict(task,kind=kind))
            # Directional measurements quantify differences, not a certificate
            # of full-time 2D mesh independence.
            result['status']='MEASURED' if kind!='twod_time_half' else 'PASS' if result['evidence']['passed'] else 'FAIL'
    elif kind=='legacy':
        from .validation import Validation_Run
        result=dict(status='DIAGNOSTIC_ONLY',legacy_role='legacy / diagnostic only',
            evidence=Validation_Run(root,scope='1d',case_filter=case),affects_official_pass=False)
    elif kind=='consistency':
        from .artifact_contract import Artifact_ReadbackOfficial
        checks={key:Artifact_ReadbackOfficial(task['dataset_root'],entry) for key,entry in entries.items()}
        result=dict(status='PASS',checks=checks,pde_solves=0)
    else:raise ValueError('UNKNOWN_VALIDATION: '+kind)
    result.update(cache_reused=False,source_artifacts=list(entries),production_fallback=False)
    path=root/'work/validation/v5'/(task['key']+'.json');Storage_WriteJson(path,result)
    return result
