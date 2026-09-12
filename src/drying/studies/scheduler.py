"""A serial experiment queue; failures remain local, and STOP is checkpoint-safe."""
import traceback
from pathlib import Path
from ..storage import Storage_WriteJson
from .baseline import Baseline_Freeze, Baseline_Check, Baseline_ReadJson
from .trajectory import Trajectory_GetSpec, Trajectory_Solve


def Studies_GetPlan(args):
    from .selection import Selection_GetFactor
    root=Path(__file__).resolve().parents[3]
    cases=[args.case] if args.case else ['q1','q23','q4'];jobs=[]
    groups=['verify','postprocess','geometry','environment','thermal'] if args.group=='all' else [args.group]
    for group in groups:
        if group=='verify':jobs.extend(dict(case=c,kind='full_reference',factor=2) for c in cases)
        if group=='postprocess':jobs.extend(dict(case=c,kind='matched') for c in cases)
        if group=='geometry' and 'q4' in cases:jobs.append(dict(case='q4',kind='fixed_radius'))
        if group=='environment':jobs.extend(dict(case=c,kind='tail',tail_minutes=m) for c in cases if c!='q1' for m in [30,90])
        if group=='thermal':
            modes=[] if args.mode=='M00' else [args.mode] if args.mode else ['M10','M01','M11']
            jobs.extend(dict(case=c,mode=m,kind=k,factor=f*Selection_GetFactor(root,c,m)) for m in modes for c in cases
                for k,f in [('production',1),('full_reference',2),('time_half',1)])
    return jobs


def Studies_Run(root,args):
    root=Path(root)
    if args.dry_run:return Studies_ShowPlan(root,args)
    Baseline_Freeze(root);Baseline_Check(root)
    jobs=Studies_GetPlan(args)
    if (root/'work/studies/technical/plot_payload/technical_manifest.json').exists():
        return Studies_RefreshFrozenExtension(root,args,jobs)
    folder=root/'work/studies';folder.mkdir(exist_ok=True)
    index_path=root/'results/studies/study_index.json'
    index=Baseline_ReadJson(index_path) if index_path.exists() else dict(schema_version=1,experiments={})
    if not args.payload_only:
        for job in jobs:
            if (folder/'STOP').exists():print('STOPPED: remove work/studies/STOP to resume',flush=True);return
            job=dict(job)
            try:
                if job['kind']=='time_half':
                    original=Trajectory_GetSpec(root,job['case'],job.get('mode','M00'),factor=job.get('factor',1))
                    job['replay']=original['experiment_id']
                    parent=root/'work/studies/experiments'/original['experiment_id']/'status.json'
                    if not parent.exists() or not Baseline_ReadJson(parent).get('complete'):
                        raise RuntimeError('STUDY_REFERENCE_INCOMPLETE: half-step replay requires its complete production trajectory')
                spec=Trajectory_GetSpec(root,**job);experiment_id=spec['experiment_id']
            except Exception as exc:
                experiment_id=f"{job['case']}_{job.get('mode','M00')}_{job['kind']}_SPEC_FAILED"
                result=dict(job,status='FAILED',complete=False,error=str(exc),traceback=traceback.format_exc())
                index['experiments'][experiment_id]=result;Storage_WriteJson(index_path,index)
                Storage_WriteJson(folder/'diagnostics'/f'{experiment_id}_exception.json',result)
                print('FAILED '+experiment_id+': '+str(exc),flush=True);continue
            index['current_experiment']=experiment_id
            index['experiments'][experiment_id]=dict(job,status='RUNNING',complete=False)
            Storage_WriteJson(index_path,index)
            print('START '+experiment_id,flush=True)
            try:
                from .cache import Cache_SealExperiment,Cache_ReuseEquivalent
                path=root/'work/studies/experiments'/experiment_id/'status.json'
                result=None
                if path.exists():
                    saved=Baseline_ReadJson(path)
                    if saved.get('complete'):result=Cache_SealExperiment(root,spec,saved)
                    elif not args.resume:raise RuntimeError('STUDY_RESUME_REQUIRED: matching unfinished trajectory exists; rerun with --resume')
                if result is None:result=Cache_ReuseEquivalent(root,spec,index['experiments'])
                if result is None:result=Trajectory_Solve(root,spec,resume=args.resume)
                if result.get('complete'):result=Cache_SealExperiment(root,spec,result)
                index['experiments'][experiment_id]=dict(job,**result)
            except Exception as exc:
                result=dict(status='FAILED',complete=False,error=str(exc),traceback=traceback.format_exc())
                index['experiments'][experiment_id]=dict(job,**result)
                Storage_WriteJson(folder/'diagnostics'/f'{experiment_id}_exception.json',result)
                print('FAILED '+experiment_id+': '+str(exc)[:400],flush=True)
            Storage_WriteJson(index_path,index)
        index['current_experiment']=None
        Storage_WriteJson(index_path,index)
    # Analysis/exports are a separate phase, installed alongside the numerical queue.
    from .analysis import Studies_Summarize
    Studies_Summarize(root,index)
    Baseline_Check(root)


def Studies_ShowPlan(root,args):
    """Read-only expected cache report, including missing prerequisites."""
    import json
    from .baseline import Baseline_HashFile
    root=Path(root);jobs=Studies_GetPlan(args);missing=[];rows=[]
    baseline=root/'work/baseline_snapshot/baseline_manifest.json'
    if not baseline.exists():
        missing.append(str(baseline));baseline_ready=False
    else:
        try:Baseline_Check(root);baseline_ready=True
        except (RuntimeError,FileNotFoundError) as exc:missing.append(str(exc));baseline_ready=False
    water_ready=False;water_path=root/'work/studies/diagnostics/water_properties.json'
    if water_path.exists():
        try:
            import iapws
            water=Baseline_ReadJson(water_path)
            water_ready=water['library_version']==iapws.__version__ and Baseline_HashFile(root/water['table_path'])==water['table_sha256']
        except (ImportError,FileNotFoundError):pass
    for job in jobs:
        row=dict(job,expected_cache_hit=False);request=dict(job)
        if not baseline_ready:row['state']='BASELINE_REQUIRED'
        elif request.get('mode','M00')!='M00' and not water_ready:
            row['state']='WATER_PROPERTY_CACHE_OR_DEPENDENCY_REQUIRED';missing.append(str(water_path))
        else:
            if request['kind']=='time_half':request['replay']=Trajectory_GetSpec(root,request['case'],request.get('mode','M00'),factor=request.get('factor',1))['experiment_id']
            spec=Trajectory_GetSpec(root,**request);folder=root/'work/studies/experiments'/spec['experiment_id'];path=folder/'status.json'
            saved=Baseline_ReadJson(path) if path.exists() else {}
            row.update(experiment_id=spec['experiment_id'],expected_cache_hit=bool(saved.get('complete') and saved.get('fingerprint')==spec['fingerprint']),
                state='EXPECTED_COMPLETE_CACHE' if saved.get('complete') and saved.get('fingerprint')==spec['fingerprint'] else 'CHECKPOINT_AVAILABLE' if (folder/'checkpoint.npz').exists() else 'COMPUTE_REQUIRED')
            if request['kind']=='time_half':row['depends_on_production_id']=request['replay']
        rows.append(row)
    print(json.dumps(dict(sequential_heavy_workers=1,read_only=True,jobs=rows,missing_inputs=sorted(set(missing)),
        cache_note='Expected identity match only; actual execution verifies all sealed numerical files. No solve or cache creation in this preview.'),ensure_ascii=False,indent=2))


def Studies_RefreshFrozenExtension(root,args,jobs):
    """Keep legacy entry points from silently dropping the newly published sheets."""
    from types import SimpleNamespace
    from .plot_contract import StudyPlot_ReadManifest
    from .cache import Cache_SealExperiment
    from .technical_run import Technical_Run,TechnicalRunResult
    manifest=StudyPlot_ReadManifest(root,validate_technical=False)
    for job in jobs:
        request=dict(job)
        if request['kind']=='time_half':
            parent=Trajectory_GetSpec(root,request['case'],request.get('mode','M00'),factor=request.get('factor',1))
            request['replay']=parent['experiment_id']
        spec=Trajectory_GetSpec(root,**request);key=spec['experiment_id']
        if key not in manifest['statuses'] or spec['fingerprint']!=manifest['specs'][key]['fingerprint']:
            raise RuntimeError('FROZEN_STUDY_SOURCE_CHANGED: '+key+'; existing technical publication refers to a different base study configuration')
        Cache_SealExperiment(root,spec,manifest['statuses'][key])
    print('FROZEN_STUDIES_REUSED: refresh technical additions while retaining all existing tables/figures',flush=True)
    forwarded=SimpleNamespace(**vars(args));forwarded.group='geometry_cross'
    result=Technical_Run(root,forwarded)
    if result==TechnicalRunResult.FAILED:raise RuntimeError('TECHNICAL_VALIDATION_FAILED')
    return result
