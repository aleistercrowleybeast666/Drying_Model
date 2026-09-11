"""Render only the declared plot payload. There is deliberately no solver import."""
import json
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from .plot_contract import Payload_ReadManifest, Payload_ResolvePath, Payload_GetRenderHash
from .plots import Plot_SetStyle, Plot_DrawCurves, Plot_DrawComparison, Plot_DrawMaxSection, Plot_DrawSurfaceNodes
from .animations import Animation_ReadDataset, Animation_DrawSections, Animation_WriteGif
from .cutaway import Cutaway_DrawFrame
from .overview import Overview_Write
from .storage import Storage_WriteJson
from .diagnostics import Diagnostics_RecordException


def Presentation_Run(root,png=True,gif=True,case_filter='all'):
    root=Path(root); manifest=Payload_ReadManifest(root); Plot_SetStyle()
    limits=[manifest['color_limits'][key] for key in ['temperature_C','moisture_kg_kg']]
    # Validate every input before changing any final plot.
    for output in manifest['outputs']: Payload_ResolvePath(root,output,True).parent.mkdir(parents=True,exist_ok=True)
    records=[]; png_files=[]
    if png:
        for key,info in manifest['questions'].items():
            q=info['question']; out=info['outputs']
            with np.load(Payload_ResolvePath(root,info['data_path']),allow_pickle=False) as source:
                data={k:source[k].copy() for k in source.files}
            section=(float(data['section_time_s']),data['section_r'],data['section_z'],data['section_actual'],data['section_reference'])
            png_files.append(Plot_DrawCurves(root,q,data,out['curves']))
            png_files.append(Plot_DrawComparison(root,q,info['comparison'],section,data['comparison'],out['compare']))
            png_files.append(Plot_DrawMaxSection(root,q,info['comparison'],section,out['section']))
            if 'surface_png' in out:
                fig=plt.figure(figsize=(12,5))
                try:
                    Plot_DrawSurfaceNodes(fig,data['surface_r'],data['surface_z'],data['surface_nodes'],
                        float(data['surface_time_s']),f'第{q}问','独立二维 PDE 解',limits)
                    fig.savefig(root/out['surface_png'])
                finally: plt.close(fig)
                png_files.append(out['surface_png'])
            print(f'PLOTS_GENERATED {key}',flush=True)
        Storage_WriteJson(root/'work/diagnostics/plots_manifest.json',dict(source='sealed plot payload only',files=png_files,
            manifest_hash=manifest['manifest_hash'],render_hash=Payload_GetRenderHash(root)))
    if gif:
        cfg=manifest['animation']; progress=np.array(cfg['relative_progress']); datasets={}
        for q in [3,4]:
            info=manifest['questions'][f'q{q}']
            if case_filter not in ('all',info['case']): continue
            dataset=Animation_ReadDataset(root,info['animations']['2d']); datasets[(q,'2d')]=dataset
            def Draw(index):
                r,z,nodes=dataset['frames'][index]
                fig=plt.figure(figsize=tuple(v/100 for v in cfg['surface_size_px']),dpi=100)
                Plot_DrawSurfaceNodes(fig,r,z,nodes,float(dataset['times'][index]),f'第{q}问',
                    '真实二维解；物理时间非匀速映射',limits)
                return fig
            records.append(Animation_WriteGif(root,root/info['outputs']['surface_gif'],len(progress),cfg['fps'],Draw,
                dict(source='genuine 2D PDE, sealed payload',case_id=dataset['case_id'],frame_times_s=dataset['times'].tolist())))
        if case_filter == 'all':
            for name,record in manifest['cross_question_gifs'].items():
                selected=[]
                for path in record['datasets']:
                    info=next(v for q in manifest['questions'].values() for v in q['animations'].values() if v['data_path']==path)
                    key=(info['question'],f'{info["dimension"]}d')
                    if key not in datasets: datasets[key]=Animation_ReadDataset(root,info)
                    selected.append(datasets[key])
                def DrawCross(index):
                    if name == 'cutaway_cylinder': return Cutaway_DrawFrame(index,selected,progress,dict(cfg['cutaway'],color_limits=limits))
                    return Animation_DrawSections(index,selected,progress,radial=name=='radial_section',limits=limits)
                try:
                    records.append(Animation_WriteGif(root,root/record['output'],len(progress),cfg['fps'],DrawCross,
                        dict(source='sealed 1D radial payload' if name=='radial_section' else 'sealed genuine 2D payload',
                            relative_progress=progress.tolist(),layout=cfg['layout'],
                            cases=[dict(case_id=d['case_id'],frame_times_s=d['times'].tolist(),end_s=d['end']) for d in selected],
                            cutaway=cfg['cutaway'] if name=='cutaway_cylinder' else None)))
                except Exception as error:
                    if name=='cutaway_cylinder':
                        Diagnostics_RecordException(root,'CUTAWAY_RENDER_FAILED',error,output=record['output'])
                    raise
        animation_manifest=root/'work/diagnostics/animations_manifest.json'
        if case_filter != 'all' and animation_manifest.exists():
            previous=json.loads(animation_manifest.read_text(encoding='utf-8'))
            replaced={v['path'] for v in records}
            records=[v for v in previous if v['path'] not in replaced]+records
        Storage_WriteJson(animation_manifest,records)
    data=json.loads(Payload_ResolvePath(root,manifest['overview_payload']).read_text(encoding='utf-8'))
    Overview_Write(root,data)
    Storage_WriteJson(root/'work/diagnostics/plot_status.json',dict(status='COMPLETE',pde_solves=0,
        manifest_hash=manifest['manifest_hash'],render_hash=Payload_GetRenderHash(root),png_files=png_files,
        gif_files=[r['path'] for r in records],source='work/plot_payload only'))
    return dict(png_files=png_files,gifs=records)
