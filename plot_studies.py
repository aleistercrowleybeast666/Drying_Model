"""Render supplementary figures/GIFs using sealed data only. Never solves PDEs."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
from drying.studies.plot_contract import StudyPlot_ReadManifest,StudyPlot_GetHash
from drying.studies.plots import StudyPlot_SetStyle,StudyPlot_Draw
from drying.studies.animations import StudyAnimation_Write
from drying.storage import Storage_WriteJson


def Studies_PlotMain():
    names=['end_effect_extent','drying_fronts','drying_kinetics','diffusion_clock_drivers','geometry_control','environment_robustness','thermal_modes','thermal_interactions','verification_evidence']
    parser=argparse.ArgumentParser(description=__doc__);selection=parser.add_mutually_exclusive_group();selection.add_argument('--fig',choices=names+['geometry_property_cross'])
    selection.add_argument('--technical-only',action='store_true',help='update only figures 03 and 05; preserve every GIF')
    selection.add_argument('--gif',choices=['thermal_temperature','thermal_moisture']);parser.add_argument('--gif-only',action='store_true')
    args=parser.parse_args()
    if (args.fig or args.technical_only) and args.gif_only:parser.error('static selection cannot be combined with --gif-only')
    root=Path(__file__).resolve().parent;manifest=StudyPlot_ReadManifest(root);StudyPlot_SetStyle()
    if (args.technical_only or args.fig=='geometry_property_cross') and not manifest.get('technical_extension'):parser.error('technical payload missing; run compute_studies.py --group geometry_cross --payload-only')
    record=dict(manifest_seal=manifest['seal'],numerical_data='sealed NPZ only; no solver imports or cache discovery',
        render_hash={name:StudyPlot_GetHash(root/'src/drying/studies'/name) for name in ['plots.py','animations.py','plot_contract.py']},files=[],failures=[])
    if not args.gif_only and not args.gif:
        for name in ['drying_kinetics','geometry_property_cross'] if args.technical_only else [args.fig] if args.fig else names:
            try:
                path=StudyPlot_Draw(root,manifest,name);record['files'].append(dict(path=path.relative_to(root).as_posix(),sha256=StudyPlot_GetHash(path)))
                print('FIGURE_COMPLETE '+name,flush=True)
            except Exception as exc:record['failures'].append(dict(name=name,error=str(exc)));print(str(exc),flush=True)
    if not args.fig and not args.technical_only:
        for name in [args.gif] if args.gif else ['thermal_temperature','thermal_moisture']:
            try:record['files'].append(StudyAnimation_Write(root,manifest,name))
            except Exception as exc:record['failures'].append(dict(name=name,error=str(exc)));print(str(exc),flush=True)
    if manifest.get('technical_extension'):
        record['render_hash'].update({name:StudyPlot_GetHash(root/'src/drying/studies'/name) for name in ['technical_plots.py','technical_contract.py']})
    for item in record['files']:
        item['sha256']=StudyPlot_GetHash(root/item['path']);item['render_hash']=record['render_hash'];item['manifest_seal']=manifest['seal']
    history=root/'work/studies/diagnostics/render_manifest.json'
    if (args.fig or args.gif or args.gif_only or args.technical_only) and history.exists():
        previous=json.loads(history.read_text(encoding='utf-8'))
        if previous.get('manifest_seal')==manifest['seal']:
            current={v['path']:v for v in record['files']}
            for old in previous.get('files',[]):
                if old['path'] not in current and (root/old['path']).is_file() and old.get('sha256')==StudyPlot_GetHash(root/old['path']):
                    current[old['path']]=old
            record['files']=list(current.values())
    record['status']='STUDY_RENDER_FAILED' if record['failures'] else 'RENDERED' if len(record['files'])==11 else 'PARTIAL_RENDER'
    # Rendering owns only this diagnostics record, never compute-owned status/overview.
    Storage_WriteJson(root/'work/studies/diagnostics/render_manifest.json',record)
    if record['failures']:raise SystemExit(1)


if __name__=='__main__':Studies_PlotMain()
