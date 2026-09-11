"""Cached-field animations with fixed scales and bounded frame memory."""
import time
from pathlib import Path
import numpy as np
from PIL import Image, GifImagePlugin
from .plots import Plot_SetStyle, Plot_GetSelected, Plot_DrawSurface, Plot_MirrorSection
import matplotlib.pyplot as plt
from .cases import Case_LoadMesh, Case_LoadConfig, Case_LoadInputs, Case_ReadStatus
from .comparison import Comparison_IterFields
from .sampling import Sampling_GetNodes
from .outputs import Output_GetEnd, Output_PrepareFolders, Output_ReadJson
from .storage import Storage_WriteJson


def Animation_WriteFrame(stream, rgb, duration_ms, first):
    frame = Image.fromarray(rgb).quantize(colors=256)
    if first:
        header, _ = GifImagePlugin.getheader(frame, info={'loop': 0})
        for block in header:
            stream.write(block)
    for block in GifImagePlugin.getdata(frame, duration=duration_ms, disposal=2, include_color_table=True):
        stream.write(block)


def Animation_GetProgress(frame_count):
    early = int(frame_count*2/3)
    return np.r_[np.linspace(0, .06, early, endpoint=False), np.linspace(.06, 1, frame_count-early)]


def Animation_LoadFrames(root, case, q, dimension, progress):
    case_id = Plot_GetSelected(root, case, dimension)
    status = Case_ReadStatus(root, case_id)
    if not status['complete']:
        raise RuntimeError(f'ANIMATION_FAILED: {case_id} trajectory is still running')
    end = Output_GetEnd(q, status)
    times = []
    for path in sorted((Path(root)/'work/cache'/case_id).glob('chunk_*.npz')):
        with np.load(path) as block:
            times.extend(block['time_s'].tolist())
    if status.get('event'):
        times.append(end)
    times = np.unique(times)
    times = times[times <= end+1e-8]
    if len(times) < 2 or abs(times[0]) > 1e-8 or abs(times[-1]-end) > 1e-8:
        raise RuntimeError(f'ANIMATION_FAILED: incomplete stored times for {case_id}')
    selected = np.array([times[np.argmin(abs(times-fraction*end))] for fraction in progress])
    wanted = set(selected.tolist())
    frames = {}
    for t, field in Comparison_IterFields(root, case_id):
        if t in wanted:
            frames[t] = field.copy()
        if t >= selected[-1]:
            break
    if status.get('event') and end not in frames:
        with np.load(Path(root)/'work/cache'/case_id/'event.npz') as block:
            frames[end] = block['state'].copy()
    if wanted-set(frames):
        raise RuntimeError(f'ANIMATION_FAILED: missing actual fields for {case_id}')
    return dict(case_id=case_id, status=status, end=end, times=selected, fields=frames,
                question=q, model=4 if q == 4 else 3, dimension=dimension, mesh=Case_LoadMesh(root,case_id))


def Animation_MapRadial(r, profile, coordinates):
    x, y = np.meshgrid(coordinates, coordinates)
    distance = np.hypot(x, y)
    values = np.interp(distance, r, profile)
    return np.ma.array(values, mask=distance > r[-1]+1e-14)


def Animation_WriteGif(root, path, frame_count, fps, draw, metadata):
    path = Path(path)
    temporary = path.with_suffix('.tmp.gif')
    started = time.perf_counter()
    try:
        with temporary.open('wb') as output:
            for index in range(frame_count):
                fig = draw(index)
                try:
                    fig.canvas.draw()
                    rgb = np.asarray(fig.canvas.buffer_rgba())[:, :, :3].copy()
                    Animation_WriteFrame(output, rgb, 1000 if index == frame_count-1 else round(1000/fps), index == 0)
                finally:
                    plt.close(fig)
                if index % 60 == 0:
                    print(f'ANIMATION_FRAME {path.name} {index+1}/{frame_count}', flush=True)
            output.write(b';')
        with Image.open(temporary) as gif:
            if gif.n_frames != frame_count:
                raise RuntimeError('ANIMATION_FAILED: encoded frame count differs')
            for index in range(frame_count):
                gif.seek(index); gif.convert('RGB').load()
            size = list(gif.size)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return dict(metadata, path=str(path.relative_to(root)), frames=frame_count, size_px=size,
                wall_s=time.perf_counter()-started, decode_check='PASSED_ALL_FRAMES', requested_fps=fps,
                fixed_color_limits=[['temperature_C', 28, 53], ['moisture_kg_kg', 0, 2.55]])


def Animation_DrawSections(index, datasets, inputs, progress, radial=False):
    fig, axes = plt.subplots(2, 2, figsize=(11, 7), dpi=100, layout='constrained')
    meshes = []
    coordinates = np.linspace(-.02, .02, 241)
    for col, dataset in enumerate(datasets):
        t = float(dataset['times'][index])
        r, z, nodes = Sampling_GetNodes(dataset['fields'][t], t, dataset['model'], inputs, dataset['mesh'])
        if not radial:
            rr, zz, mirrored = Plot_MirrorSection(r, z, nodes)
        for p in [0, 1]:
            axis = axes[p, col]
            lower, upper = (28, 53) if p == 0 else (0, 2.55)
            cmap = 'inferno' if p == 0 else 'viridis'
            if radial:
                field = Animation_MapRadial(r, nodes[p, :, 0]-(273.15 if p == 0 else 0), coordinates)
                mesh = axis.imshow(field, origin='lower', extent=(-2, 2, -2, 2),
                                   vmin=lower, vmax=upper, cmap=cmap, interpolation='nearest')
                axis.add_patch(plt.Circle((0, 0), r[-1]*100, fill=False, color='#475569', lw=1))
                axis.set(xlabel='x / cm', ylabel='y / cm', xlim=(-2.1, 2.1), ylim=(-2.1, 2.1), aspect='equal')
            else:
                field = mirrored[p]-(273.15 if p == 0 else 0)
                mesh = axis.pcolormesh(zz*100, rr*100, field, shading='gouraud', cmap=cmap, vmin=lower, vmax=upper)
                axis.set(xlabel='z / cm', ylabel='r / cm', xlim=(-12.5, 12.5), ylim=(-2.1, 2.1))
            axis.set_facecolor('#edf0f4')
            axis.set_title(f'第{dataset["question"]}问  t={t/3600:.3f} h / {dataset["end"]/3600:.3f} h\n'
                           f'R={r[-1]*100:.4f} cm', fontsize=10)
            meshes.append(mesh)
    for p in [0, 1]:
        fig.colorbar(meshes[p], ax=axes[p, :], shrink=.85, label='温度 / ℃' if p == 0 else '干基含水率 C / (kg/kg)')
    source = '一维径向解映射的圆形截面' if radial else '真实二维解的完整过轴截面'
    fig.suptitle(f'{source}，同步相对进度 {progress[index]*100:.1f}%\n'
                 '前 6% 过程放慢展示；各面板标注实际缓存时刻；色标固定', fontsize=12)
    return fig


def Animation_Run(root, case_filter='all'):
    root = Path(root)
    Output_PrepareFolders(root); Plot_SetStyle()
    inputs = Case_LoadInputs(root); cfg = Case_LoadConfig(root)['display']
    progress = Animation_GetProgress(cfg['frames'])
    manifest_path = root/'work/diagnostics/animations_manifest.json'
    manifest = Output_ReadJson(manifest_path, [])
    two_d = []
    for q, case in [(3, 'q23'), (4, 'q4')]:
        if case_filter not in ('all', case):
            continue
        dataset = Animation_LoadFrames(root, case, q, 2, progress)
        two_d.append(dataset)
        def Animation_DrawSurfaceFrame(index):
            t = float(dataset['times'][index])
            fig = plt.figure(figsize=(cfg['width_px']/100, cfg['height_px']/100), dpi=100)
            label = '真实二维解；物理时间非匀速映射'
            if not dataset['status']['event']:
                label += '；72 h 内未烘干' if dataset['end'] >= 259200 else '；未达烘干条件'
            Plot_DrawSurface(fig, dataset['fields'][t], t, dataset['model'], inputs, f'第{q}问', label, [(28, 53), (0, 2.55)], mesh=dataset['mesh'])
            return fig
        record = Animation_WriteGif(root, root/f'results/q{q}/q{q}_3d.gif', len(progress), cfg['fps'],
            Animation_DrawSurfaceFrame, dict(source='genuine 2D PDE', case_id=dataset['case_id'],
                                            frame_times_s=dataset['times'].tolist()))
        manifest = [item for item in manifest if item['path'] != record['path']]+[record]
        Storage_WriteJson(manifest_path, manifest)
    if case_filter != 'all':
        return
    for radial in [False, True]:
        datasets = ([Animation_LoadFrames(root, case, q, 1, progress) for q, case in [(3, 'q23'), (4, 'q4')]]
                    if radial else two_d)
        name = 'radial' if radial else 'axial'
        def Animation_DrawSectionFrame(index):
            return Animation_DrawSections(index, datasets, inputs, progress, radial)
        record = Animation_WriteGif(root, root/f'results/q3_q4_{name}_section.gif', len(progress), cfg['fps'],
            Animation_DrawSectionFrame, dict(source='1D radial profiles' if radial else 'genuine 2D PDE',
                relative_progress=progress.tolist(),
                cases=[dict(case_id=d['case_id'], frame_times_s=d['times'].tolist(), end_s=d['end']) for d in datasets]))
        manifest = [item for item in manifest if item['path'] != record['path']]+[record]
        Storage_WriteJson(manifest_path, manifest)
