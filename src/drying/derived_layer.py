"""Cheap C payloads from saved fields and saved event states, never reintegration."""
from pathlib import Path
import numpy as np
from .storage import Storage_WriteArray
from .dataset_layer import Dataset_Read
from .artifact_contract import Artifact_HashFile


def Derived_ReadState(root,spec,target,baseline=False):
    from .comparison import Comparison_ReadSnapshot
    from .cases import Case_LoadMesh
    from .studies.trajectory import Trajectory_Iter
    if spec.get('case_cache_id'):
        key=spec['case_cache_id']
        return Comparison_ReadSnapshot(root,key,target),Case_LoadMesh(root,key,target)
    event=Path(root)/'work/studies/experiments'/spec['experiment_id']/'event.npz'
    if event.exists():
        with np.load(event) as saved:
            if abs(float(saved['time_s'])-target)<1e-8:return saved['state'].copy(),(saved['xi_faces'].copy(),saved['eta_faces'].copy())
    for t,state,mesh in Trajectory_Iter(root,spec['experiment_id']):
        if abs(t-target)<1e-8:return state,mesh
        if t>target:break
    raise RuntimeError('PLOT_INPUT_MISSING: stored state '+spec['experiment_id']+' at '+str(target))


def Derived_Save(root,name,arrays,**metadata):
    path=Path(root)/'work/studies/plot_payload'/(name+'.npz');Storage_WriteArray(path,**arrays)
    return dict(path=path.relative_to(root).as_posix(),sha256=Artifact_HashFile(path),**metadata)


def Derived_Build(root,entries,name):
    from .judge_tasks import Task_GetCaseSpec
    from .studies.analysis import Analysis_ExtractSeries,Analysis_LoadSeries
    from .studies.metrics import Metrics_GetStages
    root=Path(root);manifest=dict(series={},specs={},statuses={},baseline_keys={},checks=[],thermal_audits=[],
        end_effects=[],counterfactuals=[],interactions=[],summary_tables=dict(DryingStages=[],ThermalModes=[]),
        validation_status='NOT_RUN',data_only=True)
    arrays={};by_artifact={};rule=Dataset_Read(root/'configs/studies_analysis.json')['stage_identification']
    for artifact,entry in entries.items():
        if not artifact.startswith('innovation.') or artifact.startswith('innovation.2d.'):continue
        spec=entry['spec'] or Task_GetCaseSpec(root,entry['status']);key=spec['experiment_id']
        event=entry['status'].get('event');extra=[event['report_s']] if event else []
        series=Analysis_ExtractSeries(root,spec,baseline=bool(spec.get('case_cache_id')),extra_times=extra,state_reader=Derived_ReadState)
        manifest['series'][key]=series;manifest['specs'][key]=spec;manifest['statuses'][key]=entry['status']
        arrays[key]=data=Analysis_LoadSeries(root,series);by_artifact[artifact]=key
        if artifact.startswith('innovation.full.'):manifest['baseline_keys'][entry['case']]=key
        if spec['kind']=='production':
            row=dict(case=spec['case'],mode=spec['mode'])
            for quantity in ['Cmean','Cmax']:
                row.update({quantity+'_'+k:v for k,v in Metrics_GetStages(data['time_s'],data['loss_'+quantity+'_s'],rule,event['report_s'] if event else None).items()})
            manifest['summary_tables']['DryingStages'].append(row)
            manifest['summary_tables']['ThermalModes'].append(dict(case=spec['case'],mode=spec['mode'],
                drying_time_h=entry['status'].get('drying_time_h'),minimum_temperature_C=float(data['Tmin_K'].min()-273.15)))
    if name=='environment_robustness':
        for artifact,key in by_artifact.items():
            if '.tail.' not in artifact:continue
            spec=manifest['specs'][key];control=arrays[key];base=arrays[manifest['baseline_keys'][spec['case']]]
            times=np.intersect1d(control['time_s'],base['time_s']);ic=np.searchsorted(control['time_s'],times);ib=np.searchsorted(base['time_s'],times)
            manifest['counterfactuals'].append(Derived_Save(root,key+'_tail',dict(time_s=times,control_Cmax=control['Cmax'][ic],delta_Cmax=control['Cmax'][ic]-base['Cmax'][ib]),
                kind='tail',case=spec['case'],tail_minutes=spec['tail_minutes'],significance='NOT_ASSESSED_WITHOUT_D'))
    if name=='thermal_interactions':
        for case in ['q23','q4']:
            keys=[manifest['baseline_keys'][case]]+[by_artifact[f'innovation.thermal.{mode}.{case}'] for mode in ['M10','M01','M11']]
            datasets=[arrays[k] for k in keys];times=datasets[0]['time_s']
            for data in datasets[1:]:times=np.intersect1d(times,data['time_s'])
            values={q:sum(sign*d[q][np.searchsorted(d['time_s'],times)] for sign,d in zip([1,-1,-1,1],datasets)) for q in ['Tmin_K','Cmax']}
            manifest['interactions'].append(Derived_Save(root,case+'_interactions',dict(time_s=times,**values),case=case))
    if name=='end_effect_extent':manifest['end_effects']=Derived_GetEndEffects(root,entries,manifest,by_artifact)
    if name in ['thermal_temperature','thermal_moisture']:
        from .studies.plan import Plan_Build
        Plan_Build(manifest,arrays)
    return manifest,arrays,by_artifact


def Derived_GetEndEffects(root,entries,manifest,by_artifact):
    from .studies.trajectory import Trajectory_Iter,Trajectory_GetInputs,Trajectory_GetNodes
    from .cases import Case_IterFields,Case_LoadMesh
    from .inputs import Input_AtTime
    from .geometry import Geometry_GetCells
    from .sampling import Sampling_GetNodes
    from .studies.metrics import Metrics_GetEndEffects
    result=[]
    for case in ['q23','q4']:
        key=by_artifact['innovation.matched.'+case];spec=manifest['specs'][key];inputs=Trajectory_GetInputs(root,spec);model=3 if case=='q23' else 4
        matched=iter(Trajectory_Iter(root,key));one=next(matched,None);rows=[];two=entries['innovation.2d.'+case]['case_id']
        for t,state in Case_IterFields(root,two):
            while one and one[0]<t-1e-8:one=next(matched,None)
            if not one or abs(one[0]-t)>1e-8:continue
            mesh=Case_LoadMesh(root,two,t)
            if not np.array_equal(mesh[0],one[2][0]):raise RuntimeError('MATCHED_DIMENSION_REFERENCE_MISSING')
            R=Input_AtTime(t,*inputs,spec['shrink'])[2];_,z,volume=Geometry_GetCells(state.shape[1],state.shape[2],R,mesh=mesh)
            errors=state-one[1][:,:,:1];metrics=Metrics_GetEndEffects(errors[0],errors[1],volume,z)
            _,_,nodes=Sampling_GetNodes(state,t,model,inputs,mesh);_,_,onodes=Trajectory_GetNodes(one[1],t,model,inputs,one[2],spec)
            for field,label,threshold in [(0,'T',.2),(1,'C',.003)]:
                if np.any(abs(nodes[field,:,0]-onodes[field,:,0])>threshold):metrics['depth_'+label+'_m']=.125
            rows.append(dict(time_s=t,**metrics))
        if not rows:raise RuntimeError('PLOT_INPUT_MISSING: no common matched/2D stored times')
        result.append(Derived_Save(root,case+'_end_effects',{k:np.array([r[k] for r in rows]) for k in rows[0]},
            case=case,question='Q3' if case=='q23' else 'Q4',scope='已有共同存储时刻；未补算配对终点；二维验证单独执行'))
    return result
