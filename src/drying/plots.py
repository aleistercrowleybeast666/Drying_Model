import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from .cases import Case_GetId, Case_IterFields, Case_LoadConfig, Case_LoadInputs, Case_ReadStatus
from .sampling import Sampling_GetNodes, Sampling_GetRadial
from .storage import Storage_WriteJson


def Plot_SetStyle():
    plt.rcParams.update({'font.family':'sans-serif', 'font.sans-serif':['Microsoft YaHei','SimHei','DejaVu Sans'],
        'axes.unicode_minus':False, 'font.size':10, 'figure.dpi':120,
        'savefig.dpi':150, 'axes.spines.top':False, 'axes.spines.right':False})


def Plot_GetSelected(root, case, dim):
    path = Path(root)/'results/validation/summary.json'
    summary = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    return summary.get(f'{case}_{dim}d',{}).get('selected_id',Case_GetId(case,dim))


def Plot_GetSnapshot(root, case_id, at_time):
    for t, field in Case_IterFields(root,case_id):
        if abs(t-at_time)<1e-8:
            return field
        if t>at_time:
            break
    raise RuntimeError(f'PLOT_FAILED: exact cached field {case_id} at t={at_time} is unavailable')


def Plot_DrawSurface(fig, field, t, model, inputs, label, status, limits=None):
    r,z,nodes = Sampling_GetNodes(field,t,model,inputs)
    # Display decimation is spatial sampling of a true 2D solution, not a 3D PDE.
    ri = np.unique(np.r_[np.arange(0,len(r),max(1,len(r)//32)),len(r)-1])
    zi = np.unique(np.r_[np.arange(0,len(z),max(1,len(z)//40)),len(z)-1])
    rr,zz = np.meshgrid(r[ri]*100,z[zi]*100,indexing='ij')
    axes=[]
    for p in range(2):
        axis=fig.add_subplot(1,2,p+1,projection='3d')
        values=nodes[p][np.ix_(ri,zi)]-(273.15 if p==0 else 0)
        lower,upper = limits[p] if limits else ((28,53) if p==0 else (0,2.55))
        surface=axis.plot_surface(rr,zz,values,cmap='inferno' if p==0 else 'viridis',
            vmin=lower,vmax=upper,linewidth=0,antialiased=True,rstride=1,cstride=1)
        axis.set(xlabel='r / cm',ylabel='z / cm',zlabel='温度 / ℃' if p==0 else '干基含水率 C / (kg/kg)',
                 xlim=(0,2),ylim=(0,12.5),zlim=(lower,upper))
        axis.set_title(f'{"温度" if p==0 else "干基含水率"}，t={t:.2f} s',fontsize=10)
        axis.view_init(elev=26,azim=-130)
        fig.colorbar(surface,ax=axis,shrink=.5,pad=.02)
        axes.append(axis)
    fig.suptitle(f'{label} · 二维核验模型 · R={r[-1]*100:.4f} cm\n{status}',fontsize=11,y=.98)
    fig.subplots_adjust(left=.02,right=.97,bottom=.09,top=.79,wspace=.15)
    return axes


def Plot_Run(root):
    root=Path(root); folder=root/'results/figures'; folder.mkdir(parents=True,exist_ok=True)
    Plot_SetStyle()
    inputs=Case_LoadInputs(root); config=Case_LoadConfig(root)
    manifest=[]
    for q,case,model in [(1,'q1',1),(2,'q23',3),(3,'q23',3),(4,'q4',4)]:
        case_id=Plot_GetSelected(root,case,1); status=Case_ReadStatus(root,case_id)
        with np.load(root/f'results/tables/result{q}_full_precision.npz') as cache:
            times=cache['time_s']; T=cache['temperature_C']; C=cache['moisture']; R=cache['R_m']; surface=cache['surface_C']
        if q<=2:
            keys=([100,300,600,900,1200,1500,1800] if q==1 else [1800,3600,5400,7200,9000,10800])
            fig,axes=plt.subplots(2,2,figsize=(12,8),layout='constrained')
            for t in keys:
                index=np.flatnonzero(np.abs(times-t)<1e-8)[0]
                for p,array in enumerate([T,C]): axes[p,0].plot(np.arange(21)*.1,array[index,:21],label=f'{t:g} s')
            for p,array in enumerate([T,C]):
                for column in [0,5,10,15,20]: axes[p,1].plot(times/(3600 if q==2 else 1),array[:,column],label=f'r={column*.1:g} cm')
                for axis in axes[p]:
                    axis.set_ylabel('温度 / ℃' if p==0 else '干基含水率 C / (kg/kg)')
                    axis.grid(alpha=.2); axis.legend(fontsize=8,ncol=2)
                axes[p,0].set_xlabel('r / cm'); axes[p,1].set_xlabel('t / h' if q==2 else 't / s')
            fig.suptitle(f'第{q}问 · 一维候选结果（时间验证通过，空间差异见验证数据）')
            path=folder/f'q{q}_radial_and_time.png'; fig.savefig(path); plt.close(fig); manifest.append(str(path.relative_to(root)))
        else:
            max_values=[]; means=[]; sample_times=[]
            for t,field in Case_IterFields(root,case_id):
                if t>times[-1]+1e-8: break
                if t%60>1e-8: continue
                r,z,nodes=Sampling_GetNodes(field,t,model,inputs)
                weights=2*np.arange(field.shape[1])+1
                sample_times.append(t); max_values.append(nodes[1].max()); means.append(np.average(field[1,:,0],weights=weights))
            if status['event']:
                with np.load(root/'results/cache'/case_id/'event.npz') as cached:
                    field=cached['state']; t=float(cached['time_s'])
                if not sample_times or t>sample_times[-1]+1e-8:
                    nodes=Sampling_GetNodes(field,t,model,inputs)[2]
                    sample_times.append(t); max_values.append(nodes[1].max()); means.append(np.average(field[1,:,0],weights=2*np.arange(field.shape[1])+1))
            fig,axes=plt.subplots(1,2,figsize=(12,4.5),layout='constrained')
            for column in [0,5,10,15,20]: axes[0].plot(times/3600,C[:,column],label=f'r={column*.1:g} cm')
            axes[1].plot(np.array(sample_times)/3600,max_values,label='全域最大')
            axes[1].plot(np.array(sample_times)/3600,means,label='体积加权平均')
            axes[1].plot(times/3600,surface,label='真实表面重构')
            for axis in axes:
                axis.axhline(.15,color='firebrick',ls='--',label='阈值 0.15')
                if status['event']: axis.axvline(status['event']['report_h'],color='black',ls=':',label=f"候选终点 {status['event']['report_h']:.4f} h")
                axis.set(xlabel='t / h',ylabel='干基含水率 C / (kg/kg)',ylim=(0,2.65)); axis.legend(fontsize=8); axis.grid(alpha=.2)
            fig.suptitle(f'第{q}问 · 一维候选轨迹 · '+('72 h 内未烘干' if not status['event'] else '空间精度待确认'))
            path=folder/f'q{q}_moisture_history.png'; fig.savefig(path); plt.close(fig); manifest.append(str(path.relative_to(root)))
            if q==4:
                fig,axes=plt.subplots(1,2,figsize=(11,4.5),layout='constrained')
                axes[0].plot(inputs[1][:,0]/3600,inputs[1][:,1]*100,color='#006b6e')
                axes[0].set(xlabel='t / h',ylabel='R / cm',title='附件2：分段线性半径，长度固定25 cm')
                for t in [1800,21600,64800,129600,172800]:
                    field=Plot_GetSnapshot(root,case_id,t)
                    r,_,nodes=Sampling_GetNodes(field,t,model,inputs)
                    axes[1].plot(r*100,nodes[1,:,0],label=f'{t/3600:g} h')
                axes[1].set(xlabel='r / cm',ylabel='干基含水率 C / (kg/kg)',xlim=(0,2)); axes[1].legend()
                for axis in axes: axis.grid(alpha=.2)
                path=folder/'q4_radius_and_snapshots.png'; fig.savefig(path); plt.close(fig); manifest.append(str(path.relative_to(root)))
    for q,case,model in [(3,'q23',3),(4,'q4',4)]:
        case_id=Plot_GetSelected(root,case,2)
        t=config['display']['snapshot_s']; field=Plot_GetSnapshot(root,case_id,t)
        fig=plt.figure(figsize=(12,5))
        Plot_DrawSurface(fig,field,t,model,inputs,f'第{q}问','独立二维求解；官方表来源始终为一维')
        path=folder/f'q{q}_distribution_3d.png'; fig.savefig(path); plt.close(fig); manifest.append(str(path.relative_to(root)))
    comparison=root/'results/comparison'
    if (comparison/'summary.json').exists():
        fig,axes=plt.subplots(2,1,figsize=(10,7),layout='constrained')
        for case in ['q1','q23','q4']:
            data=np.genfromtxt(comparison/f'{case}_pointwise.csv',delimiter=',',skip_header=1)
            axes[0].plot(data[:,0]/3600,data[:,2],label=case)
            axes[1].plot(data[:,0]/3600,data[:,10],label=case)
        for axis,threshold,label in zip(axes,[.2,.003],['最大绝对温差 / ℃','最大绝对干基含水率差 / (kg/kg)']):
            axis.axhline(threshold,color='firebrick',ls='--',label='端面比较阈值'); axis.set(xlabel='t / h',ylabel=label); axis.legend(); axis.grid(alpha=.2)
        fig.suptitle('二维核验减去一维参考：实际采样时刻的全域最大差值')
        path=folder/'end_effect_comparison.png'; fig.savefig(path); plt.close(fig); manifest.append(str(path.relative_to(root)))
    Storage_WriteJson(folder/'manifest.json',dict(source='computed caches only',files=manifest))
