"""Classified rendering from existing trajectories/payloads; no solver calls."""
import json
from pathlib import Path

import numpy as np

from .storage import Storage_WriteJson
from .judge_observer import Progress_PlotStep


def Judge_GetPlotMissing(root, selection='static'):
    from .judge_pipeline import Judge_ReadJson
    root = Path(root)
    sources = Judge_ReadJson(root/'work/recompute/production.json')
    validation = Judge_ReadJson(root/'work/validation/summary.json')
    missing = []
    for case in ['q1','q23','q4']:
        status = sources.get(case, {})
        if not status.get('complete') or not (root/'work/cache'/status.get('case_id','missing')/'status.json').is_file():
            missing.append(dict(source=case+' production', required_group='A', required_task=case))
    for case in ['q23','q4']:
        source = validation.get(case+'_2d', {}).get('selected_id')
        if not source or not (root/'work/cache'/source/'status.json').is_file():
            missing.append(dict(source=case+' independent 2D field', required_group='B', required_task='aux-2d'))
    return missing


def Judge_DrawOriginal(root, selection):
    from .judge_pipeline import Judge_ReadJson
    from .cases import Case_LoadConfig, Case_LoadInputs
    from .plot_payload import Payload_PrepareCurves, Payload_PrepareFrames, Payload_GetNodes
    from .plots import Plot_SetStyle, Plot_DrawCurves, Plot_DrawSurfaceNodes
    from .animations import Animation_GetProgress, Animation_ReadDataset, Animation_WriteGif, Animation_DrawSections
    from .cutaway import Cutaway_DrawFrame, Cutaway_GetView
    import matplotlib.pyplot as plt
    root = Path(root)
    missing = Judge_GetPlotMissing(root, selection)
    if missing:
        raise RuntimeError('PLOT_INPUT_MISSING: '+json.dumps(missing,ensure_ascii=False)+'；绘图不会自动启动 PDE。')
    production = Judge_ReadJson(root/'work/recompute/production.json')
    validation = Judge_ReadJson(root/'work/validation/summary.json')
    config = Case_LoadConfig(root); cfg = config['display']; inputs = Case_LoadInputs(root)
    Plot_SetStyle(); files = []; limits = [[28,53],[0,2.55]]
    for q in range(1,5):
        (root/f'results/q{q}').mkdir(parents=True,exist_ok=True)
    if selection == 'static':
        for q,case,model in [(1,'q1',1),(2,'q23',3),(3,'q23',3),(4,'q4',4)]:
            data = Payload_PrepareCurves(root,q,production[case]['case_id'],model,inputs,publish_summary=False)
            files.append(Plot_DrawCurves(root,q,data,f'results/q{q}/q{q}_curves.png'))
            Progress_PlotStep(len(files),6,'完成 Q'+str(q)+' 曲线')
            if q >= 3:
                t = float(cfg['snapshot_s']); source = validation[case+'_2d']['selected_id']
                r,z,nodes = Payload_GetNodes(root,source,t,model,inputs)
                fig = plt.figure(figsize=(12,5))
                try:
                    Plot_DrawSurfaceNodes(fig,r,z,nodes,t,f'第{q}问','独立二维 PDE 解',limits)
                    destination = f'results/q{q}/q{q}_3d.png'; fig.savefig(root/destination)
                    files.append(destination)
                    Progress_PlotStep(len(files),6,'完成 Q'+str(q)+' 三维图')
                finally:
                    plt.close(fig)
    elif selection == 'gif':
        progress = Animation_GetProgress(cfg['frames']); datasets = {}
        folder = root/'results/animations'; folder.mkdir(parents=True,exist_ok=True)
        for q,case,model in [(3,'q23',3),(4,'q4',4)]:
            for dimension,source in [(1,production[case]['case_id']),(2,validation[case+'_2d']['selected_id'])]:
                info = Payload_PrepareFrames(root,q,source,model,inputs,progress,dimension)
                datasets[q,dimension] = Animation_ReadDataset(root,info)
            dataset = datasets[q,2]
            def Draw_Surface(index):
                r,z,nodes = dataset['frames'][index]
                fig = plt.figure(figsize=(cfg['width_px']/100,cfg['height_px']/100),dpi=100)
                Plot_DrawSurfaceNodes(fig,r,z,nodes,float(dataset['times'][index]),f'第{q}问','真实二维解；前 6% 慢放',limits)
                return fig
            record = Animation_WriteGif(root,folder/f'q{q}_3d.gif',len(progress),cfg['fps'],Draw_Surface,
                dict(source='genuine cached 2D field',case_id=dataset['case_id'],frame_times_s=dataset['times'].tolist()))
            files.append(record['path'])
        cutaway = dict(angle_deg=cfg.get('cutaway_angle_deg',45.),azimuth_deg=cfg.get('cutaway_azimuth_deg',35.),
            boundary_width=cfg.get('cutaway_boundary_width',1.8),cut_width=cfg.get('cutaway_cut_width',2.2),color_limits=limits)
        for name,dimension in [('axial_section',2),('radial_section',1),('cutaway_cylinder',2)]:
            selected = [datasets[q,dimension] for q in [3,4]]
            def Draw_Cross(index):
                return Cutaway_DrawFrame(index,selected,progress,cutaway) if name=='cutaway_cylinder' else \
                    Animation_DrawSections(index,selected,progress,radial=name=='radial_section',limits=limits)
            record = Animation_WriteGif(root,folder/f'q3_q4_{name}.gif',len(progress),cfg['fps'],Draw_Cross,
                dict(source='unchanged cached fields',relative_progress=progress.tolist(),layout=[['Q3 T','Q4 T'],['Q3 C','Q4 C']]),
                playback_rate=Cutaway_GetView(cutaway)['playback_rate'] if name=='cutaway_cylinder' else 1.)
            files.append(record['path'])
    else:
        raise ValueError('Unknown original plot selection')
    result = dict(files=files,pde_solves=0,group='plot',selection=selection,cache_reused=False)
    Storage_WriteJson(root/f'work/diagnostics/judge_{selection}_plots.json',result)
    return result


def Judge_DrawValidation(root):
    from .judge_pipeline import Judge_ReadJson
    from .cases import Case_LoadInputs
    from .plot_payload import Payload_GetNodes
    from .plots import Plot_SetStyle, Plot_DrawComparison, Plot_DrawMaxSection
    root = Path(root); Plot_SetStyle(); inputs = Case_LoadInputs(root)
    manifest = Judge_ReadJson(root/'work/comparison/summary.json')
    files = []
    for q,case,model in [(1,'q1',1),(2,'q23',3),(3,'q23',3),(4,'q4',4)]:
        info = dict(manifest.get('q'+str(q), {}))
        if not info:
            raise RuntimeError('PLOT_INPUT_MISSING: B comparison q'+str(q))
        if q >= 3:
            end=float(info['time_range_s'][-1])
            er,ez,en=Payload_GetNodes(root,info['two_id'],end,model,inputs)
            i,j=np.unravel_index(en[1].argmax(),en[1].shape)
            info['endpoint_max_moisture_location']=dict(r_m=float(er[i]),z_m=float(ez[j]),C=float(en[1,i,j]))
        t = float(info['max_abs_moisture']['time_s'])
        r1,_,one = Payload_GetNodes(root,info['one_id'],t,model,inputs)
        r,z,two = Payload_GetNodes(root,info['two_id'],t,model,inputs)
        reference = np.broadcast_to(np.stack([np.interp(r,r1,one[p,:,0]) for p in [0,1]])[:,:,None],two.shape)
        section = (t,r,z,two,reference)
        data = np.loadtxt(root/info['csv'],delimiter=',',skiprows=1,ndmin=2)
        files.append(Plot_DrawComparison(root,q,info,section,data,f'results/q{q}/q{q}_1d_2d_compare.png'))
        files.append(Plot_DrawMaxSection(root,q,info,section,f'results/q{q}/q{q}_max_error_section.png'))
        Progress_PlotStep(len(files),8,'完成 Q'+str(q)+' 验证图')
    Storage_WriteJson(root/'work/diagnostics/judge_validation_plots.json',dict(files=files,pde_solves=0,group='validation'))


def Judge_DrawExtensions(root,gifs=True):
    from .studies.plot_contract import StudyPlot_ReadManifest, StudyPlot_GetHash
    from .studies.plots import StudyPlot_SetStyle, StudyPlot_Draw
    from .studies.animations import StudyAnimation_Write
    root = Path(root)
    try:
        manifest = StudyPlot_ReadManifest(root)
    except FileNotFoundError as error:
        raise RuntimeError('PLOT_INPUT_MISSING: D sealed study payload') from error
    StudyPlot_SetStyle(); files = []
    # End-effect extent needs the D matched trajectory; its output belongs to D.
    for name in ['end_effect_extent','drying_fronts','drying_kinetics','diffusion_clock_drivers',
                 'environment_robustness','thermal_modes','thermal_interactions','geometry_property_cross']:
        path = StudyPlot_Draw(root,manifest,name)
        files.append(dict(path=path.relative_to(root).as_posix(),sha256=StudyPlot_GetHash(path)))
        Progress_PlotStep(len(files),10 if gifs else 8,'完成拓展图 '+name)
    for name in ['thermal_temperature','thermal_moisture'] if gifs else []:
        files.append(StudyAnimation_Write(root,manifest,name))
        Progress_PlotStep(len(files),10,'完成拓展动画 '+name)
    Storage_WriteJson(root/'work/studies/diagnostics/render_manifest.json',dict(manifest_seal=manifest['seal'],files=files,
        status='RENDERED',pde_solves=0,group='extension',judge_scope=True,animations_selected=gifs))


def Judge_DrawSpatialEvidence(root):
    from .judge_pipeline import Judge_ReadJson
    from .studies.plots import StudyPlot_Draw,StudyPlot_SetStyle
    root=Path(root)
    validation=Judge_ReadJson(root/'work/validation/summary.json')
    production=Judge_ReadJson(root/'work/recompute/production.json')
    keys={case:source['case_id'] for case,source in production.items()}
    series={key:Judge_ReadJson(root/'work/studies/plot_payload'/(key+'_series.json')) for key in keys.values()}
    checks=[validation[case+'_1d']['full_schedule_reference'] for case in ['q1','q23','q4']]
    manifest=dict(baseline_keys=keys,series=series,checks=checks,thermal_audits=[],
        summary_tables=dict(EventEvidence=[dict(case=c,mode='M00',estimated_dt_s=None,
            reason='局部斜率估计属于 D 拓展；本次 B 仅使用真实参考事件差') for c in ['q23','q4']]))
    StudyPlot_SetStyle();path=StudyPlot_Draw(root,manifest,'verification_evidence')
    summary_path=root/'results/studies/validation_summary.json'
    summary=Judge_ReadJson(summary_path)
    summary['official_one_dimensional']={case:validation[case+'_1d'] for case in ['q1','q23','q4']}
    Storage_WriteJson(summary_path,summary)
    lines=['# 验证摘要','','正式来源：M00 冻结阶段网格。历史 fixed-grid：legacy / diagnostic only。','']
    for case in ['q1','q23','q4']:
        row=validation[case+'_1d'];check=row['full_schedule_reference']
        lines.append(f"- {case}: {row['numerical_status']}；完整 x2 ΔT={check['max_abs_T_K']:.8g} K，ΔC={check['max_abs_C']:.8g}；时间重放 {row['temporal']['status']}；remesh {row['remesh_transfer_passed']}。")
    (root/'results/studies/overview.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return dict(files=[path.relative_to(root).as_posix()],pde_solves=0,cache_reused=False)
