"""V5 publication boundaries and portable worker preparation."""
import json
from pathlib import Path
from .storage import Storage_WriteJson
from .artifact_contract import Artifact_Require,Artifact_Hydrate,Artifact_Seal,Artifact_ReadManifest
from .dataset_layer import Dataset_Read,Innovation_PrepareBaseline,Dataset_Merge


def Pipeline_PrepareTask(root,runtime,job):
    from .judge_pipeline import Judge_PreparePrivate
    from .judge_resources import Resource_CopyTree
    import time
    root=Path(root);runtime=Path(runtime)
    code='PLOT_INPUT_MISSING' if job['layer']=='C' else 'VALIDATION_PREREQUISITE_MISSING' if job['layer']=='D' else 'DATA_PREREQUISITE_MISSING'
    entries=Artifact_Require(root,job.get('requires',[]),code)
    private=job.get('private')
    if private and (job.get('force_data') or job.get('force_reference')):private+='_'+str(time.time_ns())
    workspace=Judge_PreparePrivate(runtime,private) if private else runtime
    Artifact_Hydrate(root,workspace,entries)
    # These compatibility selectors are derived only from explicit data artifacts.
    # They carry no validation certificate and never choose a production mesh.
    production={};sources={};selectors={}
    for key,entry in entries.items():
        if key.startswith('official.'):
            case=entry['case'];production[case]=entry['status']
            selectors[case+'_1d']=dict(selected_id=entry['case_id'],selected_fingerprint=entry['fingerprint'],numerical_status='NOT_RUN')
        elif key.startswith('innovation.full.'):sources[entry['case']+'_1d']=entry['status']
        elif key.startswith('innovation.2d.'):
            case=entry['case'];sources[case+'_2d']=entry['status']
            selectors[case+'_2d']=dict(selected_id=entry['case_id'],selected_fingerprint=entry['fingerprint'],numerical_status='NOT_RUN')
            if job['layer']=='D':Storage_WriteJson(workspace/f'work/validation/judge_2d/{case}/base.json',entry['status'])
    if workspace!=runtime:
        Storage_WriteJson(workspace/'work/datasets/innovation_sources.json',sources)
        Innovation_PrepareBaseline(workspace)
        Storage_WriteJson(workspace/'work/recompute/production.json',production)
        if job['layer'] in ['C','D']:Storage_WriteJson(workspace/'work/validation/summary.json',selectors)
    if job['layer']=='D':
        case=job.get('case')
        # Each evidence task uses a private copy: paired endpoint audit may add
        # files to a cache directory, but cannot mutate a production artifact.
        if job['kind'].startswith('twod_') and job['kind'] not in ['twod_seed','twod_time_half']:
            seed=runtime/f'work/validation/judge_2d/{case}/seed.json'
            if case and seed.exists():Resource_CopyTree(seed.parent,workspace/seed.parent.relative_to(runtime),immutable=True)
        if job['kind']=='twod_assess':
            Resource_CopyTree(runtime/'work/validation/judge_2d',workspace/'work/validation/judge_2d',immutable=True)
            Resource_CopyTree(runtime/'work/validation/auxiliary_2d',workspace/'work/validation/auxiliary_2d',immutable=True)
    return workspace


def Pipeline_Merge(root,runtime,job,workspace,receipt):
    from .judge_resources import Resource_CopyFile,Resource_CopyTree
    root=Path(root);runtime=Path(runtime);workspace=Path(workspace);result=receipt['result']
    if job['layer'] in ['A','B']:return Dataset_Merge(root,runtime,job,workspace,receipt)
    if result.get('artifact_entry'):return
    if job['layer']=='C':
        files=result['files']
        for name in files:Resource_CopyFile(workspace/name,root/name)
        Artifact_Seal(root,job['artifact'],job['key'],files,job['requires'],dict(result=result,runtime='.',pde_solves=0))
        return
    # Only D-owned references/evidence are merged. Never publish a private
    # production summary or private export over A/B results.
    if workspace!=runtime:
        for name in ['work/validation/judge_2d','work/validation/auxiliary_2d']:
            Resource_CopyTree(workspace/name,runtime/name,immutable=True)
    path=root/'work/validation/v5'/(job['key']+'.json')
    Storage_WriteJson(path,result)
    if job.get('artifact'):
        Artifact_Seal(root,job['artifact'],job['key'],[path.relative_to(root).as_posix()],job['requires'],
            dict(result=result,runtime='.',validation_status=result.get('status','COMPLETE')))
    manifest=Artifact_ReadManifest(root,'validation.summary')
    summary={k:v.get('result',{}) for k,v in manifest.get('entries',{}).items()}
    Storage_WriteJson(root/'results/validation/summary.json',dict(scope='D only; never selects or replaces A/B data',items=summary))
    path=root/'results/studies/validation_summary.json';existing=Dataset_Read(path)
    existing['v5_independent_validation']=summary;Storage_WriteJson(path,existing)
    lines=['# 验证摘要','','D 验证单独记录；未执行的验证不声称 PASS。历史 fixed-grid 为 legacy / diagnostic only。','']
    lines += [f'- {k}: {v.get("status","COMPLETE")}' for k,v in summary.items()]
    (root/'results/validation/overview.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
