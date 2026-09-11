"""Cached-field animations with fixed scales and bounded frame memory."""
import time
from pathlib import Path
import numpy as np
from PIL import Image, GifImagePlugin
from .plots import Plot_SetStyle, Plot_DrawSurfaceNodes, Plot_MirrorSection
import matplotlib.pyplot as plt
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


def Animation_ReadDataset(root, info):
    from .plot_contract import Payload_ResolvePath
    with np.load(Payload_ResolvePath(root,info['data_path']),allow_pickle=False) as data:
        frames = [(data[f'r_{i}'].copy(),data[f'z_{i}'].copy(),data[f'nodes_{i}'].copy())
                  for i in range(len(info['frame_times_s']))]
    return dict(info,frames=frames,times=np.array(info['frame_times_s']),end=info['end_s'])

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


def Animation_DrawSections(index, datasets, progress, radial=False, limits=((28,53),(0,2.55))):
    fig, axes = plt.subplots(2, 2, figsize=(11, 7), dpi=100, layout='constrained')
    meshes = []
    coordinates = np.linspace(-.02, .02, 241)
    for col, dataset in enumerate(datasets):
        t = float(dataset['times'][index])
        r, z, nodes = dataset['frames'][index]
        if not radial:
            rr, zz, mirrored = Plot_MirrorSection(r, z, nodes)
        for p in [0, 1]:
            axis = axes[p, col]
            lower, upper = limits[p]
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
    from .presentation import Presentation_Run
    return Presentation_Run(root, png=False, gif=True, case_filter=case_filter)
