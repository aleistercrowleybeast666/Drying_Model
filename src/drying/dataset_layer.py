"""A/B data production and read-only legacy registration; no validation or plots."""
import json
from pathlib import Path
from .storage import Storage_WriteJson
from .artifact_contract import Artifact_Seal,Artifact_GetCachePaths,Artifact_Verify,Artifact_GetIdentity,Artifact_HashFile


def Dataset_Read(path,default=None):
    return json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).exists() else ({} if default is None else default)


def Innovation_PrepareBaseline(runtime):
    """Construct numerical inputs exclusively from config and explicit B sources."""
    from .cases import Case_LoadConfig,Case_GetSourceHash
    from .frozen_mesh import Frozen_ReadManifest,Frozen_HashValue
    runtime=Path(runtime);frozen=Frozen_ReadManifest(runtime);config=Case_LoadConfig(runtime)
    selected={c+'_1d':dict(case=c,schedule=s,cap=s[-1]['t_end']) for c,s in frozen['schedules'].items()}
    sources=Dataset_Read(runtime/'work/datasets/innovation_sources.json')
    selected.update({k:v for k,v in sources.items() if k.endswith(('_1d','_2d'))})
    protected={p.relative_to(runtime).as_posix():dict(sha256=Artifact_HashFile(p),size=p.stat().st_size)
               for p in (runtime/'work/validation/mesh_profiles').glob('*_monitor.npz')}
    value=dict(schema_version=2,baseline_id=Frozen_HashValue(dict(frozen_mesh=frozen,config=config,
        numerical_core_hash=Case_GetSourceHash(runtime),purpose='judge_full_horizon_definition')),
        config=config,selected=selected,numerical_core_hash=Case_GetSourceHash(runtime),
        input=Dataset_Read(runtime/'data/input_manifest.json'),protected_files=protected,
        full_horizon=True,validation={},status={},images=[],workbooks=[],policy='V5 data-only inputs; validation never selects production')
    Storage_WriteJson(runtime/'work/baseline_snapshot/baseline_manifest.json',value)
    return value


def Dataset_GetSpec(runtime,job):
    from .studies.trajectory import Trajectory_GetSpec
    from .studies.selection import Selection_GetFactor
    from .studies.cross_spec import Cross_GetSpec
    case=job['case'];mode=job.get('mode','M00');kind=job.get('experiment_kind','production')
    factor=Selection_GetFactor(runtime,case,mode)*(2 if kind=='full_reference' else 1)
    if job.get('cross'):
        production=Cross_GetSpec(runtime)
        return Cross_GetSpec(runtime,kind,2 if kind=='full_reference' else 1,production['experiment_id'] if kind=='time_half' else None)
    replay=Trajectory_GetSpec(runtime,case,mode,factor=factor)['experiment_id'] if kind=='time_half' else None
    return Trajectory_GetSpec(runtime,case,mode,kind,factor,job.get('tail_minutes',60),replay)


def Dataset_GetExperimentKey(spec):
    case=spec['case'];kind=spec['kind'];mode=spec['mode']
    if kind in ['full_reference','time_half']:return None
    if spec.get('study_id')=='geometry_cross_p3_shrink':return 'innovation.cross.p3_shrink'
    if kind=='fixed_radius':return 'innovation.cross.p4_fixed'
    if kind=='tail':return f'innovation.tail.{case}.{spec["tail_minutes"]}'
    if kind=='matched':return 'innovation.matched.'+case
    if kind=='production' and mode!='M00':return f'innovation.thermal.{mode}.{case}'
    return None


def Dataset_Register(root,runtime,key,status,producer,spec=None,dependencies=()):
    root=Path(root);runtime=Path(runtime)
    paths=Artifact_GetCachePaths(runtime,status)
    case=status.get('case',spec.get('case') if spec else None)
    if key.startswith('official.'):
        for q in dict(q1=[1],q23=[2,3],q4=[4])[case]:
            paths += [root/f'results/tables/result{q}.xlsx',runtime/f'work/cache/exports/result{q}_full_precision.npz']
    # Input_Prepare rewrites descriptive source paths in input_manifest.json;
    # those paths are not scientific identity. Seal numerical arrays instead.
    for path in [runtime/'data/inputs.npz']:
        if path.exists():paths.append(path)
    return Artifact_Seal(root,key,producer,[p.relative_to(root).as_posix() for p in paths],dependencies,
        dict(case=case,case_id=status.get('case_id'),experiment_id=status.get('experiment_id',status.get('case_id')),
             fingerprint=status['fingerprint'],actual_end_s=status.get('actual_end_s',status.get('cap')),
             event=status.get('event'),runtime=runtime.relative_to(root).as_posix(),status=status,spec=spec,
             time_range_s=[status.get('start_time',0),status.get('actual_end_s',status.get('cap'))]))


def Dataset_Execute(root,task):
    """Worker entry: only data producers. Publication is performed by the parent."""
    from .cases import Case_Solve,Case_LoadConfig
    from .stages import Stage_Solve
    from .frozen_mesh import Frozen_ReadManifest
    from .artifact_contract import Artifact_ReadbackOfficial,Artifact_Require
    root=Path(root);owner=Path(task['dataset_root']);key=task['artifact']
    existing=Artifact_Verify(owner,key)
    if existing['complete'] and not task.get('force_data'):
        if key.startswith('official.'):Artifact_ReadbackOfficial(owner,existing['entry'])
        return dict(artifact_entry=existing['entry'],cache_reused=True,pde_solves=0)
    kind=task['data_kind'];case=task.get('case')
    if kind=='official':
        from .judge_tasks import Task_Execute
        from .dataset_migration import LegacyArtifact_InvalidateSelected
        if task.get('force_data'):LegacyArtifact_InvalidateSelected(root,task)
        return Task_Execute(root,dict(task,layer=None,kind='original'))
    if task.get('force_data'):
        from .dataset_migration import LegacyArtifact_InvalidateSelected
        LegacyArtifact_InvalidateSelected(root,task)
    if kind=='full':
        if case=='q1' and Artifact_Verify(owner,'official.q1')['complete'] and not task.get('force_data'):
            entry=Artifact_Require(owner,['official.q1'])['official.q1']
            return dict(production=entry['status'],alias_entry=entry,cache_reused=True)
        status=Stage_Solve(root,case,Frozen_ReadManifest(root)['schedules'][case],label='conservative' if case=='q23' else 'default')
        return dict(production=status,cache_reused=False)
    if kind=='2d':
        cfg=Case_LoadConfig(root)['mesh'];status=Case_Solve(root,case,2,nr=cfg['base_nr'],nz=cfg['base_nz'])
        return dict(production=status,cache_reused=False)
    if kind=='experiment':
        from .studies.trajectory import Trajectory_Solve
        from .studies.cache import Cache_SealExperiment
        spec=Dataset_GetSpec(root,task)
        previous=Dataset_Read(root/'work/studies/experiments'/spec['experiment_id']/'status.json')
        status=Cache_SealExperiment(root,spec,Trajectory_Solve(root,spec,resume=True))
        if not status.get('complete'):raise RuntimeError('INNOVATION_DATA_INCOMPLETE: '+key)
        return dict(production=status,spec=spec,cache_reused=bool(previous.get('complete')))
    raise ValueError('UNKNOWN_DATA_PRODUCER: '+kind)


def Dataset_Merge(root,runtime,job,workspace,receipt):
    import shutil
    from .judge_resources import Resource_CopyTree
    from .judge_pipeline import Judge_MergeWorker,Judge_PublishOriginal
    root=Path(root);runtime=Path(runtime);workspace=Path(workspace);result=receipt['result'];key=job['artifact']
    if result.get('artifact_entry'):
        entry=result['artifact_entry']
        from .artifact_contract import Artifact_Hydrate
        Artifact_Hydrate(root,runtime,{key:entry})
        status=entry['status']
    else:
        if job['data_kind']=='official':
            Judge_MergeWorker(runtime,dict(job,kind='original'),workspace,receipt)
            Judge_PublishOriginal(runtime,data_only=True)
            for relative in ['status.json','overview.md',*[f'q{q}/q{q}_summary.json' for q in range(1,5)],
                             *[f'tables/result{q}.xlsx' for q in dict(q1=[1],q23=[2,3],q4=[4])[job['case']]]]:
                source=runtime/'results'/relative
                if source.exists():
                    target=root/'results'/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        elif workspace!=runtime:
            for path in ['work/cache','work/studies/experiments']:
                Resource_CopyTree(workspace/path,runtime/path,immutable=True)
        if result.get('alias_entry'):
            from .artifact_contract import Artifact_Hydrate
            Artifact_Hydrate(root,runtime,{key:result['alias_entry']})
        status=result['production']
        Dataset_Register(root,runtime,key,status,job['key'],result.get('spec'),job.get('requires',[]))
    if key.startswith('innovation.'):
        sources=Dataset_Read(runtime/'work/datasets/innovation_sources.json')
        if job['data_kind'] in ['full','2d']:sources[job['case']+('_1d' if job['data_kind']=='full' else '_2d')]=status
        Storage_WriteJson(runtime/'work/datasets/innovation_sources.json',sources)
        Innovation_PrepareBaseline(runtime)
    elif key.startswith('official.') and result.get('artifact_entry'):
        production=Dataset_Read(runtime/'work/recompute/production.json');production[job['case']]=status
        Storage_WriteJson(runtime/'work/recompute/production.json',production)
