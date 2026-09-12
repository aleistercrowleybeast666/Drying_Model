"""Eight synchronized radial disks at identical physical times, not 2D PDE fields."""
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib.patches import Circle
from PIL import Image
import imageio.v2 as imageio
from .plot_contract import StudyPlot_Load,StudyPlot_Find
from .plan import Plan_GetFrameTimes


def StudyAnimation_GetTimes(datasets,frames=200):
    return Plan_GetFrameTimes(datasets,frames)


def StudyAnimation_Write(root,manifest,field):
    datasets={};missing={}
    for case in ['q23','q4']:
        for mode in ['M00','M10','M01','M11']:
            try:datasets[(case,mode)]=StudyPlot_Load(root,StudyPlot_Find(manifest,case,mode))
            except FileNotFoundError as exc:missing[(case,mode)]=str(exc)
    if any(sum(key[0]==case for key in datasets)<2 for case in ['q23','q4']):
        raise RuntimeError('STUDY_REFERENCE_INCOMPLETE: at least two actual thermal modes per case are required for a comparison GIF')
    for data in datasets.values():
        if not np.isfinite(data['profile']).all() or data['profile'][:,1].min()<-1e-10 or data['profile'][:,1].max()>2.55+1e-10:
            raise RuntimeError('STUDY_RENDER_FAILED: invalid or out-of-range moisture data; fixed color limits retained')
    plan=manifest.get('animation_plan',{})
    if plan.get('status')!='READY':raise RuntimeError('STUDY_PAYLOAD_MISSING: prepared animation plan; run compute_studies.py --payload-only')
    times=np.array(plan['frame_times_s'])
    if any(not np.isin(times,d['time_s']).all() for d in datasets.values()):raise RuntimeError('STUDY_MANIFEST_VERSION_MISMATCH: frame outside actual samples')
    temperature=field=='thermal_temperature';index=0 if temperature else 1
    limits=plan['temperature_limits_C'] if temperature else plan['moisture_limits']
    cmap=plt.get_cmap('inferno' if temperature else 'viridis');norm=Normalize(*limits)
    path=Path(root)/f'results/studies/animations/{field}.gif';path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix('.tmp.gif')
    grid=np.linspace(-.021,.021,161);xx,yy=np.meshgrid(grid,grid);rr=np.hypot(xx,yy)
    frame_duration=plan['frame_duration_s'];fig,axes=plt.subplots(2,4,figsize=(18,9),dpi=100)
    fig.subplots_adjust(left=.04,right=.92,bottom=.12,top=.83,wspace=.18,hspace=.42)
    artists={};circles={};texts={};panel_titles={};panel_axes={}
    labels=['M00 均不计','M10 仅潜热','M01 仅携热','M11 两者均计']
    for row,case in enumerate(['q23','q4']):
        for col,mode in enumerate(['M00','M10','M01','M11']):
            ax=axes[row,col];ax.grid(False);ax.set_aspect('equal');ax.set_xlim(-2.1,2.1);ax.set_ylim(-2.1,2.1)
            ax.set_title(('Q3' if row==0 else 'Q4')+' · '+labels[col],fontsize=12)
            ax.set_xlabel('x / cm');ax.set_ylabel('y / cm');ax.set_facecolor('#edf0f2')
            if (case,mode) in missing:
                candidates=[v for v in manifest['experiments'].values() if v.get('case')==case and v.get('mode')==mode and v.get('kind')=='production']
                reason=str(candidates[-1].get('error','STUDY_REFERENCE_INCOMPLETE')).split(':')[0] if candidates else 'STUDY_REFERENCE_INCOMPLETE'
                ax.text(.5,.5,'数据不可用\n'+reason.replace('_','\n',1),transform=ax.transAxes,ha='center',va='center',fontsize=9);continue
            artists[(case,mode)]=ax.imshow(np.ma.masked_all(rr.shape),extent=[-2.1,2.1,-2.1,2.1],origin='lower',cmap=cmap,norm=norm,interpolation='bilinear')
            circle=Circle((0,0),2.,fill=False,edgecolor='#263340',linewidth=1.2);ax.add_patch(circle);circles[(case,mode)]=circle
            texts[(case,mode)]=ax.text(.5,-.25,'',transform=ax.transAxes,ha='center',fontsize=10)
            panel_titles[(case,mode)]=('Q3' if row==0 else 'Q4')+' · '+labels[col];panel_axes[(case,mode)]=ax
    cax=fig.add_axes([.945,.18,.013,.58]);fig.colorbar(plt.cm.ScalarMappable(norm=norm,cmap=cmap),cax=cax,label='温度 / °C' if temperature else '含水率 / kg/kg')
    heading=fig.suptitle('',fontsize=18);footer=fig.text(.5,.015,'各热模型的一维径向解可视化（非二维 PDE）；八图共用非匀速时间轴，前 6% 慢放；Q4 按 R(t) 收缩',ha='center',fontsize=11)
    try:
        # Streaming imageio legacy GIF-PIL writer keeps frame memory bounded.
        with imageio.get_writer(temp,format='GIF-PIL',mode='I',duration=frame_duration,loop=0,subrectangles=False) as writer:
            for frame,t in enumerate(times):
                heading.set_text(('温度' if temperature else '含水率')+f'演化 · 真实时间 {t/3600:.3f} h / {times[-1]/3600:g} h')
                for key,data in datasets.items():
                    i=np.searchsorted(data['time_s'],t);R=data['radius_m'][i];profile=data['profile'][i,index]
                    if temperature:profile=profile-273.15
                    unit='°C' if temperature else 'kg/kg';precision=2 if temperature else 3
                    panel_axes[key].set_title(panel_titles[key]+f'\n中心 {profile[0]:.{precision}f} / 表面 {profile[-1]:.{precision}f} {unit}',fontsize=11,pad=8)
                    disk=np.interp(rr.ravel()/R,data['xi'],profile).reshape(rr.shape)
                    artists[key].set_data(np.ma.array(disk,mask=rr>R));circles[key].set_radius(R*100)
                    status=manifest['statuses'][StudyPlot_Find(manifest,*key)['experiment_id']];event=status.get('event')
                    event_text='已达标，继续积分' if event and t>=event['report_s'] else '尚未达标'
                    texts[key].set_text(f'R={R*100:.3f} cm · {event_text}')
                fig.canvas.draw();frame_array=np.asarray(fig.canvas.buffer_rgba())[:,:,:3].copy();writer.append_data(frame_array)
                if frame%40==0:print(f'{field}: {frame+1}/{len(times)} frames',flush=True)
    finally:plt.close(fig)
    durations=[]
    with Image.open(temp) as gif:
        if gif.n_frames!=len(times):raise RuntimeError('STUDY_RENDER_FAILED: incomplete GIF')
        for i in range(gif.n_frames):gif.seek(i);gif.convert('RGB').load();durations.append(gif.info.get('duration',0))
        size=list(gif.size)
    temp.replace(path)
    return dict(path=path.relative_to(root).as_posix(),frames=len(times),size_px=size,frame_times_s=times.tolist(),
        duration_ms=durations,fixed_color_limits=limits,shared_physical_time=True,field=field,
        early_fraction=.06,early_frames=120,radius='actual R(t); equal fixed physical axes',
        mapping='1D radial disk, not 2D PDE',missing=[dict(case=k[0],mode=k[1],reason=v) for k,v in missing.items()],decode_check='PASSED_ALL_FRAMES')
