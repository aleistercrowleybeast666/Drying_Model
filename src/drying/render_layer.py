"""C: individually selected figures; all computation entry points are guarded."""
from contextlib import contextmanager,ExitStack
import importlib
from pathlib import Path
import sys
import numpy as np
from .artifact_contract import Artifact_Require,Artifact_Verify
from .pipeline_plan import Catalog_Read


@contextmanager
def Render_BlockSolvers():
    from unittest.mock import patch
    blocked={
        'cases':['Case_Solve','Case_SolvePairEvents'], 'stages':['Stage_Solve'],
        'table_solver':['Table_SolveSchedule'], 'rk4':['Rk4_Advance'],
        'studies.trajectory':['Trajectory_Solve','Trajectory_GetAdvance','Trajectory_GetState'],
        'studies.analysis':['Analysis_GetExactState','Analysis_GetBaselineState'],
        'studies.mass_balance':['MassBalance_MeasureCase'], 'studies.mass_kernel':['MassBalance_BuildKernel']}
    functions=[]
    for module,names in blocked.items():
        obj=importlib.import_module('drying.'+module)
        functions += [getattr(obj,n) for n in names]
    ids={id(f) for f in functions}
    def Solver_Reject(*args,**kwargs):raise RuntimeError('PLOT_SOLVER_CALL_FORBIDDEN: C only reads saved data')
    with ExitStack() as stack:
        for name,module in list(sys.modules.items()):
            if not name.startswith('drying.') or module is None:continue
            for field,value in list(vars(module).items()):
                if id(value) in ids:stack.enter_context(patch.object(module,field,Solver_Reject))
        yield


def Render_Execute(root,task):
    root=Path(root);item=Catalog_Read(root)['plot.'+task['plot_key']]
    entries=Artifact_Require(task['dataset_root'],item['requires'],'PLOT_INPUT_MISSING')
    # Plot requests explicitly redraw. A/D certificates cannot suppress them.
    with Render_BlockSolvers():
        if item['path'].startswith('results/studies/'):
            path=Render_DrawStudy(root,entries,item)
        else:path=Render_DrawOriginal(root,entries,item)
    if not path.is_file():raise RuntimeError('PLOT_OUTPUT_MISSING: '+item['key'])
    return dict(files=[path.relative_to(root).as_posix()],pde_solves=0,cache_reused=False,
        producer='Render_Execute',source_artifacts=list(entries),solver_guard='ACTIVE',selected_plot=item['key'])


def Render_DrawOriginal(root,entries,item):
    from .cases import Case_LoadConfig,Case_LoadInputs
    from .plot_payload import Payload_PrepareCurves,Payload_GetNodes,Payload_PrepareFrames
    from .plots import Plot_SetStyle,Plot_DrawCurves,Plot_DrawSurfaceNodes,Plot_DrawComparison,Plot_DrawMaxSection
    from .animations import Animation_GetProgress,Animation_ReadDataset,Animation_WriteGif,Animation_DrawSections
    from .cutaway import Cutaway_DrawFrame,Cutaway_GetView
    import matplotlib.pyplot as plt
    name=item['renderer'];path=root/item['path'];path.parent.mkdir(parents=True,exist_ok=True)
    cfg=Case_LoadConfig(root)['display'];inputs=Case_LoadInputs(root);limits=[[28,53],[0,2.55]];Plot_SetStyle()
    if item['animation']:
        progress=Animation_GetProgress(cfg['frames']);dimension=1 if 'radial_section' in name else 2
        qs=[3,4] if name.startswith('q3_q4') else [int(name[1])];datasets=[]
        for q in qs:
            case='q23' if q==3 else 'q4';source=entries[('official.' if dimension==1 else 'innovation.2d.')+case]['case_id']
            info=Payload_PrepareFrames(root,q,source,3 if q==3 else 4,inputs,progress,dimension)
            datasets.append(Animation_ReadDataset(root,info))
        cutaway=dict(angle_deg=cfg.get('cutaway_angle_deg',45.),azimuth_deg=cfg.get('cutaway_azimuth_deg',35.),
            boundary_width=cfg.get('cutaway_boundary_width',1.8),cut_width=cfg.get('cutaway_cut_width',2.2),color_limits=limits)
        def Frame_Draw(index):
            if 'cutaway' in name:return Cutaway_DrawFrame(index,datasets,progress,cutaway)
            if name.startswith('q3_q4'):return Animation_DrawSections(index,datasets,progress,radial=dimension==1,limits=limits)
            dataset=datasets[0];r,z,nodes=dataset['frames'][index]
            fig=plt.figure(figsize=(cfg['width_px']/100,cfg['height_px']/100),dpi=100)
            Plot_DrawSurfaceNodes(fig,r,z,nodes,float(dataset['times'][index]),f'第{qs[0]}问','真实二维解；前 6% 慢放',limits);return fig
        Animation_WriteGif(root,path,len(progress),cfg['fps'],Frame_Draw,dict(source='existing sealed fields',pde_solves=0),
            playback_rate=Cutaway_GetView(cutaway)['playback_rate'] if 'cutaway' in name else 1.)
        return path
    q=int(name[1]);case={1:'q1',2:'q23',3:'q23',4:'q4'}[q];model={1:1,2:3,3:3,4:4}[q]
    if name.endswith('_curves'):
        data=Payload_PrepareCurves(root,q,entries['official.'+case]['case_id'],model,inputs,publish_summary=False)
        Plot_DrawCurves(root,q,data,item['path']);return path
    if name.endswith('_3d'):
        t=float(cfg['snapshot_s']);r,z,nodes=Payload_GetNodes(root,entries['innovation.2d.'+case]['case_id'],t,model,inputs)
        fig=plt.figure(figsize=(12,5))
        try:Plot_DrawSurfaceNodes(fig,r,z,nodes,t,f'第{q}问','独立二维 PDE 解',limits);fig.savefig(path)
        finally:plt.close(fig)
        return path
    from .comparison import Comparison_Run
    from .dataset_layer import Dataset_Read
    from .artifact_contract import Artifact_HashFile
    from .storage import Storage_WriteJson
    receipt=root/f'work/comparison/render_q{q}.json'
    identity=dict(sources={k:v['seal'] for k,v in entries.items()},comparison_source=Artifact_HashFile(Path(__file__).with_name('comparison.py')))
    prior=Dataset_Read(receipt);summary=Dataset_Read(root/'work/comparison/summary.json')
    if prior.get('identity')==identity and 'q'+str(q) in summary and all((root/p).is_file() and Artifact_HashFile(root/p)==h for p,h in prior.get('files',{}).items()):
        info=dict(summary['q'+str(q)])
    else:
        info=dict(Comparison_Run(root,case,stored_only=True,question_filter=q)['q'+str(q)])
        files={info['csv']:Artifact_HashFile(root/info['csv'])}
        Storage_WriteJson(receipt,dict(identity=identity,files=files))
    t=float(info['max_abs_moisture']['time_s']);r1,_,one=Payload_GetNodes(root,info['one_id'],t,model,inputs)
    r,z,two=Payload_GetNodes(root,info['two_id'],t,model,inputs)
    reference=np.broadcast_to(np.stack([np.interp(r,r1,one[p,:,0]) for p in [0,1]])[:,:,None],two.shape)
    section=(t,r,z,two,reference)
    if q>=3:
        er,ez,en=Payload_GetNodes(root,info['two_id'],info['time_range_s'][-1],model,inputs)
        i,j=np.unravel_index(en[1].argmax(),en[1].shape);info['endpoint_max_moisture_location']=dict(r_m=float(er[i]),z_m=float(ez[j]),C=float(en[1,i,j]))
    if name.endswith('_compare'):Plot_DrawComparison(root,q,info,section,np.loadtxt(root/info['csv'],delimiter=',',skiprows=1,ndmin=2),item['path'])
    else:Plot_DrawMaxSection(root,q,info,section,item['path'])
    return path


def Render_DrawStudy(root,entries,item):
    import matplotlib.pyplot as plt
    from .studies.plots import StudyPlot_SetStyle,StudyPlot_Draw
    from .derived_layer import Derived_Build,Derived_ReadState
    name=item['renderer'];path=root/item['path'];path.parent.mkdir(parents=True,exist_ok=True);StudyPlot_SetStyle()
    if name=='verification_evidence':
        fig,axes=plt.subplots(2,2,figsize=(11.5,8),layout='constrained')
        for ax,(case,label) in zip(axes.flat,[('q1','问题1'),('q23','问题2/3'),('q4','问题4')]):
            status=entries['official.'+case]['status'];schedule=status['schedule']
            ax.step([s['t_start']/3600 for s in schedule]+[schedule[-1]['t_end']/3600],
                [s['nr'] for s in schedule]+[schedule[-1]['nr']],where='post',label=label)
            ax.set(xlabel='时间 / h',ylabel='径向单元数',title=label+' · 已核验数据缓存');ax.legend()
        axes[1,1].axis('off');axes[1,1].text(.05,.85,'本图仅展示正式数据来源与阶段网格。\n\n数值验证：未在 C 中执行。\n请在 D 中查看独立空间、时间及守恒证据。',va='top',wrap=True)
        fig.suptitle('正式数据与验证证据范围\n缓存完整性不等于空间/时间收敛 PASS')
        try:fig.savefig(path)
        finally:plt.close(fig)
        return path
    manifest,arrays,by_artifact=Derived_Build(root,entries,name)
    if item['animation']:
        from .studies.animations import StudyAnimation_Write
        StudyAnimation_Write(root,manifest,name);return path
    if name=='geometry_property_cross':fig=Render_DrawCross(root,manifest,arrays,by_artifact)
    elif name=='drying_kinetics':
        from .studies.kinetics import Kinetics_Extract
        from .studies.technical_plots import Technical_DrawKinetics
        kinetics={key:Kinetics_Extract(root,manifest,key,state_reader=Derived_ReadState) for key in manifest['baseline_keys'].values()}
        fig=Technical_DrawKinetics(root,manifest,dict(kinetics=kinetics,kinetics_summary=kinetics[manifest['baseline_keys']['q4']]['timing']))
    else:
        actual=StudyPlot_Draw(root,manifest,name)
        if actual!=path:actual.replace(path)
        return path
    try:fig.savefig(path)
    finally:plt.close(fig)
    return path


def Render_DrawCross(root,manifest,arrays,by_artifact):
    from .derived_layer import Derived_Save,Derived_ReadState
    from .studies.technical_analysis import Technical_GetQualifiedFraction
    from .studies.technical_plots import Technical_DrawCross
    from .studies.trajectory import Trajectory_GetInputs,Trajectory_GetNodes
    groups=[('P3_fixed','innovation.full.q23'),('P3_shrink','innovation.cross.p3_shrink'),
            ('P4_fixed','innovation.cross.p4_fixed'),('P4_shrink','innovation.full.q4')]
    times=arrays[by_artifact[groups[0][1]]]['time_s']
    for _,artifact in groups[1:]:times=np.intersect1d(times,arrays[by_artifact[artifact]]['time_s'])
    payload=dict(time_s=times);rows=[]
    for group,artifact in groups:
        key=by_artifact[artifact];data=arrays[key];spec=manifest['specs'][key];status=manifest['statuses'][key]
        if abs(data['time_s'][-1]-259200)>1e-8:raise RuntimeError('PLOT_INPUT_MISSING: full 72 h cross data')
        indices=np.searchsorted(data['time_s'],times);payload[group+'_Cmax']=data['Cmax'][indices]
        state,mesh=Derived_ReadState(root,spec,259200.);inputs=Trajectory_GetInputs(root,spec)
        r,_,nodes=Trajectory_GetNodes(state,259200.,spec.get('material_appendix',3 if spec['case']=='q23' else 4),inputs,mesh,spec)
        row=dict(group=group,drying_time_h=status.get('drying_time_h'),
            endpoint_Cmax=status['event']['report_max_C'] if status.get('event') else float(data['Cmax'][-1]),
            Cmax_72h=float(data['Cmax'][-1]),Cmean_72h=float(data['Cmean'][-1]),
            qualified_volume_fraction_72h=Technical_GetQualifiedFraction(r,nodes[1,:,0]))
        rows.append(row)
    interaction={q:rows[3][q]-rows[2][q]-rows[1][q]+rows[0][q] for q in ['Cmax_72h','Cmean_72h','qualified_volume_fraction_72h']}
    entry=Derived_Save(root,'geometry_cross',payload,groups=rows,interactions=interaction)
    return Technical_DrawCross(root,dict(geometry_property_cross=entry,cross_validation=dict(status='未运行 D')))
