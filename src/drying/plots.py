from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def Plot_SetStyle():
    plt.rcParams.update({'font.family':'sans-serif', 'font.sans-serif':['Microsoft YaHei','SimHei','DejaVu Sans'],
        'axes.unicode_minus':False, 'font.size':10, 'figure.dpi':120,
        'savefig.dpi':150, 'axes.spines.top':False, 'axes.spines.right':False})


def Plot_DrawSurfaceNodes(fig, r, z, nodes, t, label, status, limits=None):
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


def Plot_MirrorSection(r, z, nodes):
    """Reflect the actual half-cylinder across both symmetry planes."""
    radial = np.r_[-r[:0:-1], r]
    axial = np.r_[-z[:0:-1], z]
    values = np.concatenate((nodes[:, :0:-1, :], nodes), axis=1)
    values = np.concatenate((values[:, :, :0:-1], values), axis=2)
    return radial, axial, values


def Plot_DrawComparison(root, q, info, section, data, destination):
    t, r, z, actual, reference = section
    long = q >= 3
    factor = 1 if q == 1 else 3600
    unit = 's' if q == 1 else 'h'
    fig, axes = plt.subplots(2, 3 if long else 2, figsize=(15 if long else 11, 7.5), layout='constrained')
    for p, offset in enumerate([2, 10]):
        label = '温度绝对差 / K' if p == 0 else '含水率绝对差 / (kg/kg)'
        for col in range(2 if long else 1):
            axis = axes[p, col]
            cutoff = min(10800, data[-1, 0]) if col == 1 else data[-1, 0]
            selected = data[:, 0] <= cutoff
            for index, name, color, style in [(offset, '全域最大', '#24272b', '-'),
                (offset+5, '端面最大', '#d05b26', '--'), (offset+4, '中截面最大', '#197db3', ':')]:
                axis.plot(data[selected, 0]/factor, data[selected, index], label=name,
                          color=color, ls=style, lw=2 if index == offset else 1.6)
            axis.set(xlabel=f't / {unit}', ylabel=label, xlim=(0, cutoff/factor),
                     title='早期放大（前 3 h）' if col else '全过程' if long else '规定时间范围')
            axis.text(.03, .95, f'中截面峰值 {data[:, offset+4].max():.3g}',
                      transform=axis.transAxes, va='top', color='#197db3', fontsize=9)
            axis.legend(loc='center right', fontsize=8); axis.grid(alpha=.2)
        axis = axes[p, -1]
        profile = np.max(np.abs(actual[p]-reference[p]), axis=0)
        axis.plot(z*100, profile, color='#d05b26', lw=2)
        axis.set(xlabel='z / cm（0：中截面；12.5：端面）', ylabel=label,
                 title=f'沿轴向的径向最大差，t={t/3600:.3f} h', xlim=(0, 12.5))
        axis.grid(alpha=.2)
    title = f'第{q}问：一维与真实二维解的差异（端面与全域曲线可能重合）'
    if q >= 3:
        location = info['endpoint_max_moisture_location']
        title += f'\n终点二维最大含水率位置：r={location["r_m"]*100:.3g} cm，z={location["z_m"]*100:.3g} cm（中截面为 z=0）'
    fig.suptitle(title, fontsize=13)
    path = Path(root)/destination
    fig.savefig(path); plt.close(fig)
    return str(path.relative_to(root))


def Plot_DrawMaxSection(root, q, info, section, destination):
    t, r, z, actual, reference = section
    radial, axial, actual = Plot_MirrorSection(r, z, actual)
    reference = Plot_MirrorSection(r, z, reference)[2]
    error = np.abs(actual-reference)
    fig, axes = plt.subplots(2, 3, figsize=(15, 6.8), layout='constrained')
    for p in [0, 1]:
        fields = [actual[p]-(273.15 if p == 0 else 0), reference[p]-(273.15 if p == 0 else 0), error[p]]
        lower, upper = min(fields[0].min(), fields[1].min()), max(fields[0].max(), fields[1].max())
        for col, field in enumerate(fields):
            axis = axes[p, col]
            mesh = axis.pcolormesh(axial*100, radial*100, field, shading='gouraud',
                cmap='magma' if col == 2 else 'inferno' if p == 0 else 'viridis',
                vmin=0 if col == 2 else lower, vmax=max(float(field.max()), 1e-15) if col == 2 else upper)
            axis.set(xlabel='z / cm', ylabel='r / cm', xlim=(-12.5, 12.5), ylim=(-2, 2),
                title=['实际二维场', '一维沿轴向复制的参考场', '绝对误差 |二维 − 一维|'][col])
            axis.axvline(0, color='white', lw=.6, ls=':', alpha=.6)
            fig.colorbar(mesh, ax=axis, shrink=.8, label=('温差 / K' if col == 2 else '温度 / ℃') if p == 0 else 'C / (kg/kg)')
    fig.suptitle(f'第{q}问：最大含水率差时刻 t={t:.2f} s（{t/3600:.4f} h）\n'
        f'温度最大差时刻 {info["max_abs_temperature"]["time_s"]:.2f} s；z=0 为中截面，两端由对称性展开', fontsize=13)
    path = Path(root)/destination
    fig.savefig(path); plt.close(fig)
    return str(path.relative_to(root))


def Plot_DrawCurves(root, q, payload, destination):
    times, profiles = payload['time_s'], payload['profiles']
    means, maxima, radii = payload['mean_C'], payload['max_C'], payload['R_m']
    end = float(times[-1])
    snapshots = {float(t):(payload[f'snapshot_r_{i}'],payload[f'snapshot_nodes_{i}'])
                 for i,t in enumerate(payload['snapshot_time_s'])}
    factor = 1 if q == 1 else 3600
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), layout='constrained')
    labels = ['中心', 'r/R=0.25', 'r/R=0.50', 'r/R=0.75', '表面']
    colors = ['#243e64', '#197c80', '#7e972b', '#d29125', '#bd423b']
    for p in [0, 1]:
        axis = axes[p, 1] if q <= 2 else axes[0, p]
        for i in range(5):
            axis.plot(times/factor, profiles[:, p, i]-(273.15 if p == 0 else 0),
                      color=colors[i], label=labels[i], lw=1.6)
        axis.set(xlabel='t / s' if q == 1 else 't / h',
                 ylabel='温度 / ℃' if p == 0 else '干基含水率 C / (kg/kg)', xlim=(0, end/factor))
        if q <= 2:
            for t, (r, values) in snapshots.items():
                axes[p, 0].plot(r*100, values[p]-(273.15 if p == 0 else 0), label=f'{t:g} s')
            axes[p, 0].set(xlabel='r / cm', ylabel='温度 / ℃' if p == 0 else '干基含水率 C / (kg/kg)')
    if q >= 3:
        axes[1, 0].plot(times/3600, maxima, label='全域最大', color='#243e64')
        axes[1, 0].plot(times/3600, means, label='体积加权平均', color='#197c80')
        axes[1, 0].axhline(.15, color='#bd423b', ls='--', label='烘干阈值 0.15')
        axes[1, 0].set(xlabel='t / h', ylabel='干基含水率 C / (kg/kg)', xlim=(0, end/3600))
        rate = -np.gradient(np.array(maxima), times/3600)
        axes[1, 1].plot(times/3600, rate, color='#197c80', label='最大含水率下降速率')
        axes[1, 1].set(xlabel='t / h', ylabel='−dCmax/dt / (kg/kg/h)', xlim=(0, end/3600))
        if q == 4:
            radius_axis = axes[1, 1].twinx()
            radius_axis.plot(times/3600, np.array(radii)*100, color='#bd423b', ls='--', label='R(t)')
            radius_axis.set_ylabel('当前半径 R / cm', color='#bd423b')
    for axis in axes.flat:
        axis.grid(alpha=.2); axis.legend(fontsize=8, ncol=2)
    if q == 4:
        lines1, labels1 = axes[1, 1].get_legend_handles_labels()
        lines2, labels2 = radius_axis.get_legend_handles_labels()
        axes[1, 1].legend(lines1+lines2, labels1+labels2, fontsize=8, loc='upper right')
    title = f'第{q}问：一维结果，0–{end/factor:.4f} {"s" if q == 1 else "h"}'
    if q == 4:
        title += '\n曲线按当前相对半径取样；正式表仍使用固定空间 r'
    fig.suptitle(title, fontsize=13)
    path = Path(root)/destination
    fig.savefig(path); plt.close(fig)
    return str(path.relative_to(root))


def Plot_Run(root):
    from .presentation import Presentation_Run
    return Presentation_Run(root, png=True, gif=False)
