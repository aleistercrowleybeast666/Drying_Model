"""Four explicit plans joined by artifact contracts and an A/B -> C/D barrier."""
import json
from pathlib import Path
from .runtime import Runtime_GetCode
from .artifact_contract import Artifact_GetStatus


def Catalog_Read(root):
    code=Runtime_GetCode(Path(root));items=[]
    if not (code/'configs/task_catalog.json').is_file():code=Path(__file__).resolve().parents[2]
    for filename,field,prefix in [('task_catalog.json','tasks',''),('plot_catalog.json','plots','plot.'),('validation_catalog.json','validations','validation.')]:
        path=code/'configs'/filename
        if not path.exists():continue
        for raw in json.loads(path.read_text(encoding='utf-8'))[field]:
            row=dict(raw);row['selection_key']=prefix+row['key'];items.append(row)
    return {r['selection_key']:r for r in items}


def Catalog_GetPresets(root):
    catalog=Catalog_Read(root)
    return dict(official=[k for k,v in catalog.items() if v['mode']=='A'],
        paper=[k for k,v in catalog.items() if v['mode'] in ['A','B']],all=list(catalog),
        validation=[k for k,v in catalog.items() if v['mode']=='D'])


def Plan_CreateJob(key,kind,layer,requires=(),**values):
    return dict(key=key,kind=kind,layer=layer,group=dict(A='original',B='extension',C='plot',D='validation')[layer],
        requires=list(requires),dependencies=[],phase=1 if layer in ['A','B'] else 2,**values)


def OfficialPlan_Build(items):
    return [Plan_CreateJob('A.'+r['case'],'original','A',data_kind='official',artifact=r['artifact'],case=r['case'],
        pde=True,private='official_'+r['case'],label=r['display_name_zh']) for r in items]


def InnovationPlan_Build(items,catalog):
    expanded={}
    def Add_Item(row):
        if row['data_kind']=='alias':
            for key in row['targets']:Add_Item(catalog[key])
            return
        if row['selection_key'] in expanded:return
        expanded[row['selection_key']]=row
        for key in row['dependencies']:Add_Item(catalog[key])
    for item in items:Add_Item(item)
    jobs=[]
    for key,r in expanded.items():
        kind={'full':'full_production','2d':'twod_base','experiment':'experiment'}[r['data_kind']]
        row=Plan_CreateJob('B.'+key.removeprefix('innovation.'),kind,'B',r['dependencies'],
            data_kind=r['data_kind'],artifact=key,case=r['case'],pde=True,
            private=None if kind=='experiment' else 'data_'+key.replace('.','_'),label=r['display_name_zh'])
        for field in ['experiment_kind','cross','tail_minutes']:
            if field in r:row[field]=r[field]
        row['mode']=r.get('mode_id','M00');jobs.append(row)
    return jobs


def RenderPlan_Build(items):
    return [Plan_CreateJob('C.'+r['key'],'render','C',r['requires'],artifact='plot.'+r['key'],
        plot_key=r['key'],pde=False,private='render_'+r['key'].split('_')[0]+'_comparison' if r['key'].endswith(('_compare','_max_error_section')) else 'render_'+r['key'],label=r['display_name_zh']) for r in items]


def ValidationPlan_Build(items):
    jobs=[];seeds={}
    for r in items:
        key='D.'+r['key'];kind=r['kind'];case=r.get('case')
        worker_kind='mass_measure' if kind=='mass' else 'experiment' if kind.startswith(('thermal_','cross_')) else kind
        job=Plan_CreateJob(key,worker_kind,'D',r['requires'],validation_kind=kind,artifact='validation.'+r['key'],
            case=case,mode=r.get('mode_id','M00'),pde=kind not in ['m00_remesh','consistency','twod_assess'],
            private=None if worker_kind in ['experiment','mass_measure'] else 'validation_'+r['key'].replace('.','_'),label=r['display_name_zh'])
        if kind.startswith(('thermal_','cross_')):
            job['experiment_kind']=kind.split('_',1)[1];job['cross']=kind.startswith('cross_')
        if kind.startswith('twod_') and kind not in ['twod_assess','twod_time_half']:
            seed='D.2d.'+case+'.seed';job['dependencies'].append(seed)
            seeds[case]=Plan_CreateJob(seed,'twod_seed','D',r['requires'],validation_kind='twod_seed',case=case,
                pde=True,private='validation_'+case+'_seed',label=case+'二维代表时刻准备')
        if kind=='twod_assess':
            # An assess-only request consumes existing validation artifacts;
            # it does not silently select additional validations.
            job['requires'] += r.get('validation_requires',[])
        jobs.append(job)
    return list(seeds.values())+jobs


def PipelinePlan_Build(root,selected,workers='auto',force_data=False,force_validation=False):
    from .judge_schedule import Schedule_GetResources
    from .judge_progress import Progress_GetIdentity
    root=Path(root);catalog=Catalog_Read(root)
    unknown=set(selected)-catalog.keys()
    if unknown:raise ValueError('UNKNOWN_TASK: '+', '.join(sorted(unknown)))
    items=[catalog[k] for k in dict.fromkeys(selected)]
    jobs=OfficialPlan_Build([r for r in items if r['mode']=='A'])
    jobs+=InnovationPlan_Build([r for r in items if r['mode']=='B'],catalog)
    jobs+=RenderPlan_Build([r for r in items if r['mode']=='C'])
    jobs+=ValidationPlan_Build([r for r in items if r['mode']=='D'])
    resources=Schedule_GetResources(workers);producers={j['artifact']:j['key'] for j in jobs if j.get('artifact')}
    phase_one=[j['key'] for j in jobs if j['phase']==1]
    missing=[]
    try:identity=Progress_GetIdentity(root)
    except FileNotFoundError:identity=None
    profile_path=Runtime_GetCode(root)/'configs/judge_resource_reference.json'
    profile=json.loads(profile_path.read_text(encoding='utf-8')) if profile_path.exists() else {}
    for job in jobs:
        job['force_data']=force_data and job['layer'] in ['A','B'];job['force_reference']=force_validation and job['layer']=='D'
        for key in job['requires']:
            if key in producers:job['dependencies'].append(producers[key])
            elif not Artifact_GetStatus(root,key)['complete']:missing.append(dict(task=job['key'],artifact=key))
        if job['phase']==2:job['dependencies']+=phase_one
        job['dependencies']=list(dict.fromkeys(job['dependencies']))
        state=Artifact_GetStatus(root,job['artifact']) if job.get('artifact') else {'complete':False}
        if job['key']=='B.full.q1' and Artifact_GetStatus(root,'official.q1')['complete']:
            state={'complete':True}
        job['expected_cache_hit']=state['complete'] and not (job['force_data'] or job['force_reference'])
        job['cache_state']='RECHECK_SEALED_ARTIFACT' if job['expected_cache_hit'] else 'COMPUTE_REQUIRED'
        job['cpu_demand']=job['slots']=1
        peak=profile.get('peak_rss_mb',{}).get(job['kind']) if profile.get('identity')==identity else None
        job['memory_estimate_mb']=max(512.,peak*1.3) if peak else 2048. if job['kind'].startswith('twod_') and job['pde'] else 1024. if job['pde'] else 512.
        if job['expected_cache_hit']:job['memory_estimate_mb']=512.
        previous=root/'work/recompute/runtime/work/recompute/receipts'/(job['key']+'.json')
        if previous.exists():
            old=json.loads(previous.read_text(encoding='utf-8'))
            if old.get('progress_identity')==identity and old.get('peak_rss_mb'):job['memory_estimate_mb']=max(512.,old['peak_rss_mb']*1.3)
        job['persistent']=job['kind'] in ['experiment','mass_measure']
        job['locks']=[] if job['private'] else ['validation_summary'] if job['kind']=='twod_assess' else []
    return dict(schema_version=5,v5=True,selected=list(selected),steps=jobs,mode='DRY_RUN',pde_solves=0,
        automatic_dependencies=[catalog[k]['display_name_zh'] for k in producers if k in catalog and k not in selected],
        missing_prerequisites=missing,worker_count=resources['cpu_tokens'],resources=resources,
        requires_pde=any(j['pde'] and not j['expected_cache_hit'] for j in jobs),
        logical_tasks=len(items),unique_pde_experiments=sum(j['pde'] for j in jobs),
        experiment_aliases={'B.full.q1':'A.q1 when a matching complete artifact exists'},
        developer_full_audit=all(k in selected for k,v in catalog.items() if v['mode']=='D'),
        parallel_groups={g:[j['key'] for j in jobs if j['group']==g] for g in ['original','extension','plot','validation']},
        phase_labels={'1':'生成基础数据 A/B','2':'绘图 / 验证 C/D'},output='results/')


def Pipeline_CheckPrerequisites(plan):
    if plan['missing_prerequisites']:
        code='PLOT_INPUT_MISSING' if any(v['task'].startswith('C.') for v in plan['missing_prerequisites']) else 'VALIDATION_PREREQUISITE_MISSING'
        raise RuntimeError(code+': '+json.dumps(plan['missing_prerequisites'],ensure_ascii=False)+'；请先运行对应基础数据任务，不会自动选择 A/B。')
