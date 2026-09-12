"""Compute-side adapter from variable-grid trajectories to standalone plot arrays."""
import json
from datetime import datetime
from pathlib import Path
import numpy as np
from .cases import Case_LoadConfig, Case_LoadInputs, Case_LoadMesh, Case_ReadStatus, Case_GetSchedule
from .comparison import Comparison_IterFields, Comparison_ReadSnapshot
from .sampling import Sampling_GetNodes
from .geometry import Geometry_GetCells
from .outputs import Output_GetEnd, Output_GetSelected, Output_UpdateSummary
from .storage import Storage_WriteArray, Storage_WriteJson, Storage_HashFiles
from .plot_contract import Payload_GetRenderHash, Payload_GetSeal
from .overview import Overview_Gather, Overview_Write


def Payload_GetNodes(root,case_id,t,model,inputs,field=None):
    state = Comparison_ReadSnapshot(root,case_id,t) if field is None else field
    return Sampling_GetNodes(state,t,model,inputs,Case_LoadMesh(root,case_id,t))


def Payload_PrepareCurves(root,q,case_id,model,inputs):
    status = Case_ReadStatus(root,case_id); end = Output_GetEnd(q,status)
    times=[]; profiles=[]; means=[]; maxima=[]; radii=[]; snapshots={}
    keys = [100,600,1200,1800] if q == 1 else [1800,3600,7200,10800]
    max_T,min_C = -np.inf,np.inf
    for t,field in Comparison_IterFields(root,case_id):
        if t > end+1e-8: break
        mesh = Case_LoadMesh(root,case_id,t)
        r,_,nodes = Sampling_GetNodes(field,t,model,inputs,mesh)
        max_T,min_C = max(max_T,float(nodes[0].max())),min(min_C,float(nodes[1].min()))
        if t in keys: snapshots[t] = (r,nodes[:,:,0].copy())
        if q <= 2 or abs(t/60-round(t/60)) < 1e-8 or abs(t-end) < 1e-8:
            times.append(t); radii.append(r[-1])
            profiles.append(np.stack([np.interp(np.array([0,.25,.5,.75,1])*r[-1],r,nodes[p,:,0]) for p in [0,1]]))
            means.append(np.average(field[1,:,0],weights=Geometry_GetCells(field.shape[1],1,r[-1],mesh=mesh)[2][:,0]))
            maxima.append(nodes[1].max())
    if not times or abs(times[-1]-end) > 1e-8:
        raise RuntimeError(f'PLOT_PAYLOAD_MISSING: exact q{q} endpoint {end} in {case_id}')
    arrays = dict(time_s=np.array(times),profiles=np.array(profiles),mean_C=np.array(means),max_C=np.array(maxima),
        R_m=np.array(radii),snapshot_time_s=np.array(list(snapshots)))
    for i,(r,nodes) in enumerate(snapshots.values()):
        arrays[f'snapshot_r_{i}']=r; arrays[f'snapshot_nodes_{i}']=nodes
    Output_UpdateSummary(root,q,max_temperature=max_T-273.15,min_moisture=min_C,
        temperature_unit='degC',moisture_unit='kg/kg',extrema_source='All stored 1D samples in question window')
    return arrays


def Payload_PrepareFrames(root,q,case_id,model,inputs,progress,dimension):
    status = Case_ReadStatus(root,case_id); end = Output_GetEnd(q,status)
    times = np.unique(np.r_[Case_GetSchedule(status['case'],status['cap']),
        [s['t_start'] for s in status.get('stages',[])],end])
    times = times[times <= end+1e-8]
    selected = np.array([times[np.argmin(abs(times-fraction*end))] for fraction in progress])
    wanted = set(selected.tolist()); frames = {}
    for t,field in Comparison_IterFields(root,case_id):
        if t in wanted: frames[t] = Payload_GetNodes(root,case_id,t,model,inputs,field)
        if t >= selected[-1]: break
    if wanted-set(frames):
        raise RuntimeError(f'PLOT_PAYLOAD_MISSING: frames {sorted(wanted-set(frames))} in {case_id}')
    arrays = dict(time_s=selected,relative_progress=progress)
    for i,t in enumerate(selected):
        r,z,nodes = frames[t]
        arrays.update({f'r_{i}':r,f'z_{i}':z,f'nodes_{i}':nodes})
    path = Path(root)/f'work/plot_payload/q{q}_{dimension}d_frames.npz'
    Storage_WriteArray(path,**arrays)
    return dict(data_path=path.relative_to(root).as_posix(),case_id=case_id,dimension=dimension,question=q,
        frame_times_s=selected.tolist(),end_s=end,event=status.get('event'),
        execution_mode=status.get('execution_mode','fixed'),source_fingerprint=status['fingerprint'])


def Payload_Prepare(root):
    root=Path(root); folder=root/'work/plot_payload'; folder.mkdir(parents=True,exist_ok=True)
    cfg=Case_LoadConfig(root); inputs=Case_LoadInputs(root)
    comparison=json.loads((root/'work/comparison/summary.json').read_text(encoding='utf-8'))
    count=cfg['display']['frames']; early=int(count*2/3)
    progress=np.r_[np.linspace(0,.06,early,endpoint=False),np.linspace(.06,1,count-early)]
    manifest=dict(schema_version=1,generated_at=datetime.now().astimezone().isoformat(timespec='seconds'),
        input_hash=json.loads((root/'data/input_manifest.json').read_text(encoding='utf-8'))['hash'],
        plot_version_hash=Payload_GetRenderHash(root),questions={},payload_files=[],outputs=[],
        color_limits=dict(temperature_C=[28,53],moisture_kg_kg=[0,2.55]),
        animation=dict(relative_progress=progress.tolist(),frames=count,fps=cfg['display']['fps'],
            surface_size_px=[cfg['display']['width_px'],cfg['display']['height_px']],
            layout=[['Q3 temperature','Q4 temperature'],['Q3 moisture','Q4 moisture']],
            cutaway=dict(angle_deg=cfg['display'].get('cutaway_angle_deg',45.),
                azimuth_deg=cfg['display'].get('cutaway_azimuth_deg',35.),
                boundary_width=cfg['display'].get('cutaway_boundary_width',1.8),
                cut_width=cfg['display'].get('cutaway_cut_width',2.2),
                geometry='Upright cylinder; transverse plane at model midsection; upper portion removed only for visibility')),
        overview_payload='work/plot_payload/overview_data.json',cross_question_gifs={})
    for q,case,model in [(1,'q1',1),(2,'q23',3),(3,'q23',3),(4,'q4',4)]:
        one,two=[Output_GetSelected(root,case,d) for d in [1,2]]
        source=Case_ReadStatus(root,one); info=dict(comparison[f'q{q}'])
        arrays=Payload_PrepareCurves(root,q,one,model,inputs)
        arrays['comparison']=np.loadtxt(root/info['csv'],delimiter=',',skiprows=1,ndmin=2)
        t=float(info['max_abs_moisture']['time_s'])
        r1,_,nodes1=Payload_GetNodes(root,one,t,model,inputs)
        r,z,nodes=Payload_GetNodes(root,two,t,model,inputs)
        reference=np.broadcast_to(np.stack([np.interp(r,r1,nodes1[p,:,0]) for p in [0,1]])[:,:,None],nodes.shape)
        arrays.update(section_time_s=t,section_r=r,section_z=z,section_actual=nodes,section_reference=reference)
        output={key:f'results/q{q}/q{q}_{name}.png' for key,name in
            [('curves','curves'),('compare','1d_2d_compare'),('section','max_error_section')]}
        animation={}
        if q >= 3:
            end=info['time_range_s'][-1]
            er,ez,en=Payload_GetNodes(root,two,end,model,inputs)
            i,j=np.unravel_index(en[1].argmax(),en[1].shape)
            location=dict(r_m=float(er[i]),z_m=float(ez[j]),C=float(en[1,i,j]))
            info['endpoint_max_moisture_location']=location
            Output_UpdateSummary(root,q,endpoint_2d_max_moisture_location=location)
            st=float(cfg['display']['snapshot_s']); sr,sz,sn=Payload_GetNodes(root,two,st,model,inputs)
            arrays.update(surface_time_s=st,surface_r=sr,surface_z=sz,surface_nodes=sn)
            output.update(surface_png=f'results/q{q}/q{q}_3d.png',surface_gif=f'results/animations/q{q}_3d.gif')
            for dim,case_id in [(1,one),(2,two)]:
                animation[f'{dim}d']=Payload_PrepareFrames(root,q,case_id,model,inputs,progress,dim)
        path=folder/f'q{q}_plot_data.npz'; Storage_WriteArray(path,**arrays)
        manifest['questions'][f'q{q}']=dict(question=q,case=case,one_id=one,two_id=two,
            one_cache=f'work/cache/{one}',two_cache=f'work/cache/{two}',mesh_mode=source['mesh_mode'],
            execution_mode=source.get('execution_mode','fixed'),stages=source.get('stages',[]),
            data_path=path.relative_to(root).as_posix(),comparison=info,animations=animation,outputs=output,
            representative_times_s=arrays['snapshot_time_s'].tolist(),
            maximum_error_times_s={key:info[f'max_abs_{key}']['time_s'] for key in ['temperature','moisture']},
            color_limits=manifest['color_limits'],excel=f'results/tables/result{q}.xlsx',source_fingerprint=source['fingerprint'])
        manifest['outputs'].extend(output.values())
        print(f'PLOT_PAYLOAD_PREPARED q{q}',flush=True)
    for name,dim in [('axial_section','2d'),('radial_section','1d'),('cutaway_cylinder','2d')]:
        output=f'results/animations/q3_q4_{name}.gif'
        manifest['cross_question_gifs'][name]=dict(output=output,
            datasets=[manifest['questions'][q]['animations'][dim]['data_path'] for q in ['q3','q4']])
        manifest['outputs'].append(output)
    evidence=Overview_Gather(root); Storage_WriteJson(root/manifest['overview_payload'],evidence)
    Overview_Write(root,evidence)
    payloads=[v['data_path'] for v in manifest['questions'].values()]+[manifest['overview_payload']]
    payloads += [v['data_path'] for q in manifest['questions'].values() for v in q['animations'].values()]
    manifest['payload_files']=[dict(path=p,hash=Storage_HashFiles([root/p]),size_bytes=(root/p).stat().st_size) for p in sorted(set(payloads))]
    manifest['manifest_hash']=Payload_GetSeal(manifest)
    Storage_WriteJson(folder/'plot_manifest.json',manifest)
    return manifest
