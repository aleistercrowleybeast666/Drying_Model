"""One-frame-at-a-time GIF encoding; only real saved 2D fields are displayed."""
import json
import time
from pathlib import Path
import numpy as np
from PIL import Image, GifImagePlugin
import matplotlib.pyplot as plt
from .cases import Case_IterFields, Case_LoadConfig, Case_LoadInputs, Case_ReadStatus
from .plots import Plot_SetStyle, Plot_GetSelected, Plot_DrawSurface
from .storage import Storage_WriteJson


def Animation_WriteFrame(stream, rgb, duration_ms, first):
    frame=Image.fromarray(rgb).quantize(colors=256)
    if first:
        header,_=GifImagePlugin.getheader(frame,info={'loop':0})
        for block in header: stream.write(block)
    for block in GifImagePlugin.getdata(frame,duration=duration_ms,disposal=2,include_color_table=True):
        stream.write(block)


def Animation_Run(root, case_filter='all'):
    root=Path(root); folder=root/'results/animations'; folder.mkdir(parents=True,exist_ok=True)
    Plot_SetStyle(); inputs=Case_LoadInputs(root); cfg=Case_LoadConfig(root)['display']
    manifest=[]
    manifest_path=folder/'manifest.json'
    if manifest_path.exists():
        manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    for q,case,model in [(3,'q23',3),(4,'q4',4)]:
        if case_filter not in ('all',case):
            continue
        case_id=Plot_GetSelected(root,case,2); status=Case_ReadStatus(root,case_id)
        if not status['complete']:
            raise RuntimeError(f'ANIMATION_FAILED: {case_id} trajectory is still running')
        end=status['event']['report_s'] if status['event'] else status['cap']
        times=[]
        # Discover times without loading the fields into one giant array.
        for path in sorted((root/'results/cache'/case_id).glob('chunk_*.npz')):
            with np.load(path) as block: times.extend(block['time_s'].tolist())
        times=np.array(times); times=times[times<=end+1e-8]
        requested=np.r_[np.linspace(0,min(10800,end),int(cfg['frames']*2/3),endpoint=False),
                         np.linspace(min(10800,end),end,cfg['frames']-int(cfg['frames']*2/3))]
        indices=np.unique([int(np.argmin(abs(times-t))) for t in requested])
        selected=times[indices]; wanted=set(selected.tolist())
        event_field=None
        if status['event']:
            with np.load(root/'results/cache'/case_id/'event.npz') as saved: event_field=saved['state'].copy()
        path=folder/f'q{q}_distribution_3d.gif'; temporary=path.with_suffix('.tmp.gif')
        frame_times=[]; started=time.perf_counter()
        with temporary.open('wb') as output:
            def Write(field,t,last=False):
                figure=plt.figure(figsize=(cfg['width_px']/100,cfg['height_px']/100),dpi=100)
                text=('72 h 内未烘干' if not status['event'] else '候选轨迹，空间验证未完全覆盖')+'；物理时间非匀速映射'
                Plot_DrawSurface(figure,field,t,model,inputs,f'第{q}问',text,[(28,53),(0,2.55)])
                figure.canvas.draw()
                rgb=np.asarray(figure.canvas.buffer_rgba())[:,:,:3].copy()
                Animation_WriteFrame(output,rgb,1000 if last else int(round(1000/cfg['fps'])),not frame_times)
                plt.close(figure); frame_times.append(float(t))
            for t,field in Case_IterFields(root,case_id):
                if t in wanted:
                    Write(field,t,last=event_field is None and t==selected[-1])
                if t>=selected[-1]: break
            if event_field is not None:
                Write(event_field,end,last=True)
            output.write(b';')
        # Reopen and decode first, middle and final frames before atomic publication.
        with Image.open(temporary) as gif:
            count=gif.n_frames
            assert count==len(frame_times)
            for index in [0,count//2,count-1]: gif.seek(index); gif.convert('RGB').load()
            assert gif.size==(cfg['width_px'],cfg['height_px'])
        temporary.replace(path)
        manifest=[item for item in manifest if item['case_id']!=case_id]
        manifest.append(dict(path=str(path.relative_to(root)),case_id=case_id,frame_times_s=frame_times,
            frames=len(frame_times),requested_fps=cfg['fps'],note='GIF delays quantized to 10 ms; actual stored frame times displayed; no interpolation',
            wall_s=time.perf_counter()-started,decode_check='PASSED',source_status=status['status']))
        Storage_WriteJson(folder/'manifest.json',manifest)
