from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from .cases import Case_LoadMesh, Case_LoadConfig, Case_LoadInputs, Case_ReadStatus
from .sampling import Sampling_GetNodes
from .storage import Storage_WriteJson
from .geometry import Geometry_GetCells
from .comparison import Comparison_IterFields, Comparison_EnsureQuestions, Comparison_ReadSnapshot
from .outputs import Output_GetEnd, Output_GetSelected, Output_PrepareFolders, Output_UpdateSummary


def Plot_SetStyle():
    plt.rcParams.update({'font.family':'sans-serif', 'font.sans-serif':['Microsoft YaHei','SimHei','DejaVu Sans'],
        'axes.unicode_minus':False, 'font.size':10, 'figure.dpi':120,
        'savefig.dpi':150, 'axes.spines.top':False, 'axes.spines.right':False})


def Plot_GetSelected(root, case, dim):
    return Output_GetSelected(root, case, dim)


def Plot_GetSnapshot(root, case_id, at_time):
    return Comparison_ReadSnapshot(root, case_id, at_time)


def Plot_DrawSurface(fig, field, t, model, inputs, label, status, limits=None, mesh=None):
    r,z,nodes = Sampling_GetNodes(field,t,model,inputs,mesh)
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


def Plot_GetComparisonSection(root, info, model, inputs):
    t = info['max_abs_moisture']['time_s']
    one = Plot_GetSnapshot(root, info['one_id'], t)
    two = Plot_GetSnapshot(root, info['two_id'], t)
    r1, _, values1 = Sampling_GetNodes(one, t, model, inputs, Case_LoadMesh(root,info['one_id']))
    r, z, actual = Sampling_GetNodes(two, t, model, inputs, Case_LoadMesh(root,info['two_id']))
    reference = np.broadcast_to(np.stack([np.interp(r, r1, values1[p, :, 0]) for p in [0, 1]])[:, :, None], actual.shape)
    return t, r, z, actual, reference


def Plot_DrawComparison(root, q, info, section):
    t, r, z, actual, reference = section
    data = np.loadtxt(Path(root)/info['csv'], delimiter=',', skiprows=1, ndmin=2)
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
    path = Path(root)/f'results/q{q}/q{q}_1d_2d_compare.png'
    fig.savefig(path); plt.close(fig)
    return str(path.relative_to(root))


def Plot_DrawMaxSection(root, q, info, section):
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
    path = Path(root)/f'results/q{q}/q{q}_max_error_section.png'
    fig.savefig(path); plt.close(fig)
    return str(path.relative_to(root))


def Plot_DrawCurves(root, q, case, model, inputs):
    case_id = Plot_GetSelected(root, case, 1)
    status = Case_ReadStatus(root, case_id)
    end = Output_GetEnd(q, status)
    mesh = Case_LoadMesh(root,case_id)
    times, profiles, means, maxima, radii = [], [], [], [], []
    snapshots = {}
    keys = [100, 600, 1200, 1800] if q == 1 else [1800, 3600, 7200, 10800]
    maximum_T, minimum_C = -np.inf, np.inf
    # All extrema use all stored samples; plotted time curves keep a modest density.
    for t, field in Comparison_IterFields(root, case_id):
        if t > end+1e-8:
            break
        r, _, nodes = Sampling_GetNodes(field, t, model, inputs, mesh)
        maximum_T = max(maximum_T, float(nodes[0].max()))
        minimum_C = min(minimum_C, float(nodes[1].min()))
        if t in keys:
            snapshots[t] = (r, nodes[:, :, 0].copy())
        if q <= 2 or abs(t/60-round(t/60)) < 1e-8 or abs(t-end) < 1e-8:
            times.append(t)
            positions = np.array([0, .25, .5, .75, 1])*r[-1]
            profiles.append(np.stack([np.interp(positions, r, nodes[p, :, 0]) for p in [0, 1]]))
            means.append(np.average(field[1, :, 0], weights=Geometry_GetCells(field.shape[1],1,r[-1],mesh=mesh)[2][:,0]))
            maxima.append(nodes[1].max()); radii.append(r[-1])
    if not times or abs(times[-1]-end) > 1e-8:
        raise RuntimeError(f'PLOT_FAILED: q{q} endpoint absent from cache')
    times, profiles = np.array(times), np.array(profiles)
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
    path = Path(root)/f'results/q{q}/q{q}_curves.png'
    fig.savefig(path); plt.close(fig)
    Output_UpdateSummary(root, q, max_temperature=maximum_T-273.15, min_moisture=minimum_C,
                         temperature_unit='degC', moisture_unit='kg/kg', extrema_source='All stored 1D samples in question window')
    return str(path.relative_to(root))


def Plot_Run(root):
    root = Path(root)
    Output_PrepareFolders(root); Plot_SetStyle()
    inputs = Case_LoadInputs(root); config = Case_LoadConfig(root)
    comparison = Comparison_EnsureQuestions(root)
    manifest = []
    for q, case, model in [(1, 'q1', 1), (2, 'q23', 3), (3, 'q23', 3), (4, 'q4', 4)]:
        manifest.append(Plot_DrawCurves(root, q, case, model, inputs))
        info = comparison[f'q{q}']
        if q >= 3:
            end = info['time_range_s'][-1]
            field = Plot_GetSnapshot(root, info['two_id'], end)
            r, z, nodes = Sampling_GetNodes(field, end, model, inputs, Case_LoadMesh(root,info['two_id']))
            i, j = np.unravel_index(nodes[1].argmax(), nodes[1].shape)
            location = dict(r_m=float(r[i]), z_m=float(z[j]), C=float(nodes[1, i, j]))
            info['endpoint_max_moisture_location'] = location
            Output_UpdateSummary(root, q, endpoint_2d_max_moisture_location=location)
        section = Plot_GetComparisonSection(root, info, model, inputs)
        manifest.append(Plot_DrawComparison(root, q, info, section))
        manifest.append(Plot_DrawMaxSection(root, q, info, section))
        if q >= 3:
            case_id = Plot_GetSelected(root, case, 2)
            t = config['display']['snapshot_s']
            field = Plot_GetSnapshot(root, case_id, t)
            fig = plt.figure(figsize=(12, 5))
            Plot_DrawSurface(fig, field, t, model, inputs, f'第{q}问', '独立二维 PDE 解', mesh=Case_LoadMesh(root,case_id))
            path = root/f'results/q{q}/q{q}_3d.png'
            fig.savefig(path); plt.close(fig); manifest.append(str(path.relative_to(root)))
        print(f'PLOTS_GENERATED q{q}', flush=True)
    Storage_WriteJson(root/'work/diagnostics/plots_manifest.json', dict(source='computed caches only', files=manifest))
