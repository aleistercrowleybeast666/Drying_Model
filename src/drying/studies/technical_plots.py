"""The two final static figures read only sealed, prepared analysis arrays."""
from pathlib import Path
import json
import numpy as np
import matplotlib.pyplot as plt
from .plot_contract import StudyPlot_Load, StudyPlot_Find, StudyPlot_GetHash
from .technical_contract import Technical_ReadPayload


def Technical_Draw(root, manifest, name):
    root=Path(root);technical=Technical_ReadPayload(root,manifest)
    if name=='drying_kinetics':
        fig=Technical_DrawKinetics(root,manifest,technical)
        filename='03_drying_kinetics.png'
    else:
        fig=Technical_DrawCross(root,technical)
        filename='05_geometry_property_cross.png'
    path=root/'results/studies/figures'/filename
    temporary=path.with_suffix('.tmp.png');fig.savefig(temporary);plt.close(fig);temporary.replace(path)
    if filename=='05_geometry_property_cross.png':
        old=root/'results/studies/figures/05_geometry_control.png'
        if old.exists():
            receipt=json.loads((root/'work/studies/technical/pre_extension_render.json').read_text(encoding='utf-8'))
            expected=next(item['sha256'] for item in receipt['files'] if item['path']==old.relative_to(root).as_posix())
            if StudyPlot_GetHash(old)!=expected:raise RuntimeError('LEGACY_FIGURE_CHANGED: preserve for review')
            old.unlink()
    return path


def Technical_DrawCross(root, technical):
    entry=technical['geometry_property_cross'];d=StudyPlot_Load(root,entry)
    rows=entry['groups'];groups=[r['group'] for r in rows]
    colors=['#31688e','#35a89d','#b35d2e','#cba33c'];styles=['-','--','-','--']
    fig=plt.figure(figsize=(12,6.7),layout='constrained');grid=fig.add_gridspec(2,2,width_ratios=[1.35,1])
    left=fig.add_subplot(grid[:,0]);upper=fig.add_subplot(grid[0,1]);lower=fig.add_subplot(grid[1,1])
    for group,color,style,row in zip(groups,colors,styles,rows):
        left.plot(d['time_s']/3600,d[group+'_Cmax'],style,color=color,label=group)
        if row['drying_time_h'] is not None:
            left.plot(row['drying_time_h'],row['endpoint_Cmax'],'o',ms=4,color=color)
    left.axhline(.15,color='#555555',ls=':',lw=1,label='正式阈值 0.15')
    left.set(xlabel='时间 / h',ylabel='最大含水率 / kg/kg',xlim=(0,72),title='四组完整轨迹；圆点为各自真实烘干事件')
    left.legend(loc='upper right',fontsize=9,frameon=False)
    positions=np.arange(4)
    for offset,metric,hatch,label in [(-.18,'Cmax','', 'Cmax'),(.18,'Cmean','///','体积平均 C')]:
        upper.bar(positions+offset,[row[metric+'_72h'] for row in rows],width=.34,color=colors,hatch=hatch,
            edgecolor='#555555',linewidth=.5,label=label)
    upper.set(ylabel='72 h 含水率 / kg/kg',xticks=positions,xticklabels=groups)
    upper.legend(fontsize=9,frameon=False,ncol=2)
    bars=lower.bar(positions,[row['qualified_volume_fraction_72h']*100 for row in rows],color=colors,width=.58)
    lower.bar_label(bars,fmt='%.1f%%',fontsize=9,padding=2)
    lower.set(ylabel='72 h 达标体积 / %',xticks=positions,xticklabels=groups,ylim=(0,112))
    interaction=entry['interactions'];status=technical['cross_validation']['status']
    fig.suptitle('几何—物性 2×2 交叉对照\n固定 R0 / 附件 R(t)；物性分别完整采用附录 3 或附录 4',fontsize=14)
    fig.supxlabel(f"72 h 交互 I：Cmax={interaction['Cmax_72h']:+.4f}，平均 C={interaction['Cmean_72h']:+.4f} kg/kg，达标体积={interaction['qualified_volume_fraction_72h']*100:+.2f} 个百分点\n"
        +f"P3 收缩独立验证 {status}；P4 固定组未独立加密，交互仅作结构诊断；未干组时长不外推",fontsize=9)
    return fig


def Technical_DrawKinetics(root, manifest, technical):
    fig,axes=plt.subplots(2,2,figsize=(12,8.8),layout='constrained')
    colors={'q23':'#31688e','q4':'#bc5739'};labels={'q23':'Q3','q4':'Q4'};stage_notes=[]
    for case in ['q23','q4']:
        d=StudyPlot_Load(root,StudyPlot_Find(manifest,case));t=d['time_s']/3600;color=colors[case];label=labels[case]
        axes[0,0].plot(t,d['Cmax'],color=color,label=label+' Cmax')
        axes[0,0].plot(t,d['Cmean'],'--',color=color,label=label+' 平均 C')
        axes[0,1].plot(t,d['Dmean_m2_s'],color=color,label=label+' 体积平均 D')
        axes[0,1].plot(t,d['Dcenter_m2_s'],'--',color=color,label=label+' 中心 D')
        k=StudyPlot_Load(root,technical['kinetics'][manifest['baseline_keys'][case]])
        axes[1,0].plot(k['time_s']/3600,k['minus_dCmean_dt']*3600,color=color,label=label+' 平均 C')
        axes[1,0].plot(t,d['loss_Cmax_s']*3600,'--',color=color,label=label+' Cmax')
        row=next(r for r in manifest['summary_tables']['DryingStages'] if r['case']==case and r['mode']=='M00')
        if row.get('Cmean_three_stage'):
            stage_notes.append(label+' 平均 C：已识别慢—快—慢内峰')
        else:stage_notes.append(label+' 平均 C：未识别慢—快—慢')
        if row.get('Cmax_three_stage'):
            axes[1,0].plot(row['Cmax_peak_time_s']/3600,row['Cmax_peak_rate_kg_kg_s']*3600,'o',color=color,ms=4)
            stage_notes.append(label+' Cmax：慢—快—慢，圆点为内峰')
    for ax in axes.flat:ax.set_xlabel('时间 / h')
    axes[0,0].set(ylabel='含水率 / kg/kg',title='(a) 共同时间的含水率轨迹',xlim=(0,72))
    axes[0,0].axhline(.15,color='gray',ls=':',lw=.9)
    axes[0,1].set(ylabel='扩散系数 / m²/s',title='(b) 材料扩散率的状态响应',xlim=(0,72))
    axes[1,0].set(ylabel='失水速率 / (kg/kg)/h',title='(c) 失水速率与阶段识别',xlim=(0,72))
    axes[1,0].text(.98,.95,'\n'.join(stage_notes),transform=axes[1,0].transAxes,ha='right',va='top',fontsize=8.5,
        bbox=dict(facecolor='white',edgecolor='none',alpha=.85))
    key=manifest['baseline_keys']['q4'];d=StudyPlot_Load(root,technical['kinetics'][key]);k=technical['kinetics_summary'];ax=axes[1,1]
    end=k['observation_end_s'];window=max(k['t_T50'],k['t_C50'],k['t_R50'],k['t_T_peak'],k['t_C_peak'],k['R_peak_interval_end'])*1.18
    mask=d['time_s']<=min(end,window);clock_colors=['#b5463b','#2a7f96','#79743e']
    for field,peak,label,color in [('dTmean_dt','vT_peak','T 温升率',clock_colors[0]),
        ('minus_dCmean_dt','vC_peak','C 失水率',clock_colors[1]),('minus_dR_dt','vR_peak','R 收缩率',clock_colors[2])]:
        rate=d[field][mask]/k[peak];t=d['time_s'][mask]/3600
        if field=='minus_dR_dt':ax.step(t,rate,where='post',color=color,label=label)
        else:ax.plot(t,rate,color=color,label=label)
    for start,stop in k['R_peak_intervals_s']:
        ax.axvspan(start/3600,stop/3600,color=clock_colors[2],alpha=.12)
    for field,color,label in [('t_T_peak',clock_colors[0],'T peak'),('t_C_peak',clock_colors[1],'C peak')]:
        ax.plot(k[field]/3600,1,'v',color=color,ms=7,clip_on=False,label=label)
    for field,color,label in [('t_T50',clock_colors[0],'T50'),('t_C50',clock_colors[1],'C50'),('t_R50',clock_colors[2],'R50')]:
        ax.axvline(k[field]/3600,ls=':',color=color,lw=1.2,label=label)
    ax.set(xlim=(-.04,window/3600),ylim=(-.08,1.11),ylabel='速率 / 各自在正式窗口内的最大值',title='(d) Q4 三速率与响应时钟（早期放大）')
    ax.text(.98,.95,'阴影：R peak interval\nC peak 位于观察窗起点',transform=ax.transAxes,ha='right',va='top',fontsize=8.5)
    for panel in axes.flat:
        if panel==ax:panel.legend(fontsize=8,frameon=False,ncol=4,loc='upper center',bbox_to_anchor=(.5,-.16))
        else:panel.legend(fontsize=8,frameon=False,ncol=2,loc='best')
    fig.suptitle('干燥动力学与 Q4 峰值时序\n体积加权均值；阶段内中心差分；半径采用附件分段斜率',fontsize=14)
    fig.supxlabel('冻结 M00 一维；原始 PDE 状态不平滑。t50 基于初态至 Q4 正式烘干终点的总响应；时序诊断不表示因果关系。',fontsize=9)
    return fig
