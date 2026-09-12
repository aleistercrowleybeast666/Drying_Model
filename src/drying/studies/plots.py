"""Nine 2D scientific figures from sealed arrays. No numerical solver imports."""
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from .plot_contract import StudyPlot_Load,StudyPlot_Find


def StudyPlot_SetStyle():
    plt.rcParams.update({'font.sans-serif':['Microsoft YaHei','SimHei','DejaVu Sans'],'axes.unicode_minus':False,
        'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'axes.grid':True,'grid.alpha':.2,
        'lines.linewidth':1.5,'savefig.dpi':160})


def StudyPlot_Create(title,subtitle=''):
    fig,axes=plt.subplots(2,2,figsize=(11.5,8),layout='constrained')
    fig.suptitle(title+('\n'+subtitle if subtitle else ''),fontsize=14)
    return fig,axes


def StudyPlot_Finish(fig,axes,path):
    for ax in axes.flat:
        handles,labels=ax.get_legend_handles_labels()
        if handles:ax.legend(fontsize=8,frameon=False)
        if not ax.get_xlabel():ax.set_xlabel('时间 / h')
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp.png');fig.savefig(temp);plt.close(fig);temp.replace(path)


def StudyPlot_Draw(root,manifest,name):
    output=Path(root)/'results/studies/figures'
    base={c:StudyPlot_Load(root,StudyPlot_Find(manifest,c)) for c in ['q23','q4']}
    labels={'q23':'Q3','q4':'Q4'};colors={'q23':'#3465a4','q4':'#c65b38'}
    if name=='end_effect_extent':
        if len(manifest['end_effects'])<2:raise RuntimeError('MATCHED_DIMENSION_REFERENCE_MISSING: compute_studies.py --group postprocess --resume')
        fig,axes=StudyPlot_Create('端面影响深度与受影响体积','匹配径向 FV 网格；二维验证仍为 PARTIAL；ΔT>0.2 K，ΔC>0.003 kg/kg')
        for entry in manifest['end_effects']:
            if entry.get('question') not in ['Q3','Q4']:continue
            d=StudyPlot_Load(root,entry);case=entry['case'];t=d['time_s']/3600
            for ax,key in zip(axes.flat,['depth_T_m','depth_C_m','volume_fraction_T','volume_fraction_C']):
                ax.plot(t,d[key]*(100 if 'depth' in key else 100),label=labels[case],color=colors[case])
        for ax,text in zip(axes.flat,['温度影响深度 / cm','含水率影响深度 / cm','温度受影响体积 / %','含水率受影响体积 / %']):ax.set_ylabel(text)
    elif name=='drying_fronts':
        fig,axes=StudyPlot_Create('干燥前沿','C*=2、1、0.5、0.15 kg/kg；仅 0.15 为正式阈值')
        for col,case in enumerate(base):
            d=base[case]
            for i,(threshold,style) in enumerate(zip([2,1,.5,.15],['-','--','-.',':'])):
                axes[0,col].plot(d['time_s']/3600,d['fronts'][:,i,0]*100,style,label=f'C*={threshold}')
                axes[1,col].plot(d['time_s']/3600,d['fronts'][:,i,1],style,label=f'C*={threshold}')
            axes[0,col].set(title=labels[case],ylabel='物理前沿半径 / cm');axes[1,col].set_ylabel('相对前沿半径 rf/R')
    elif name=='drying_kinetics':
        fig,axes=StudyPlot_Create('干燥动力学与早期半径变化','导数按真实时间计算，各网格阶段分别计算；半径分段斜率跳变来自附件插值')
        for case,d in base.items():
            t=d['time_s']/3600;label=labels[case];color=colors[case]
            axes[0,0].plot(t,d['Cmax'],color=color,label=label+' Cmax');axes[0,0].plot(t,d['Cmean'],'--',color=color,label=label+' 平均 C')
            axes[0,1].plot(t,d['loss_Cmean_s']*3600,color=color,label=label+' −d平均C/dt');axes[0,1].plot(t,d['loss_Cmax_s']*3600,':',color=color,label=label+' −dCmax/dt')
            identified=next(row for row in manifest['summary_tables']['DryingStages'] if row['case']==case and row['mode']=='M00')
            for quantity,marker in [('Cmean','o'),('Cmax','s')]:
                if identified.get(quantity+'_three_stage'):
                    axes[0,1].plot(identified[quantity+'_peak_time_s']/3600,identified[quantity+'_peak_rate_kg_kg_s']*3600,
                        marker,color=color,ms=5,label=label+' '+quantity+' 已识别内峰')
            axes[1,0].plot(t,d['Dmean_m2_s'],color=color,label=label+' 体积平均 D');axes[1,0].plot(t,d['Dcenter_m2_s'],'--',color=color,label=label+' 中心 D')
        d=base['q4'];mask=d['time_s']<=14400;t=d['time_s'][mask]/3600
        loss=d['loss_Cmean_s'][mask];rate=-d['radius_rate_m_s'][mask]
        axes[1,1].plot(t,loss/np.nanmax(abs(loss)),label='−d平均C/dt / 窗内最大绝对值')
        axes[1,1].step(t,rate/np.max(abs(rate)),where='post',label='−dR/dt / 窗内最大绝对值')
        for ax,label in zip(axes.flat,['C / kg/kg','含水率损失速率 / (kg/kg)/h','扩散系数 / m²/s','Q4 前 4 h 归一化速率']):ax.set_ylabel(label)
    elif name=='diffusion_clock_drivers':
        fig,axes=StudyPlot_Create('扩散时钟与局部对数驱动分解','ΘV=∫DV/R²dt 为尺度诊断；下排沿 ξ=0，ξ=0.5 见表；不作因果归因')
        for case,d in base.items():
            axes[0,0].plot(d['time_s']/3600,d['Cmax'],label=labels[case]);axes[0,1].plot(d['theta_V'],d['Cmax'],label=labels[case])
        axes[0,0].set_ylabel('Cmax / kg/kg');axes[0,1].set(xlabel='ΘV / 无量纲',ylabel='Cmax / kg/kg')
        for col,case in enumerate(base):
            d=base[case]
            for j,label in enumerate(['BT 温度','BC 含水率','BR 半径']):
                axes[1,col].plot(d['time_s']/3600,d['drivers_center'][:,j],label=label+' ξ=0')
            axes[1,col].set(title=labels[case],ylabel='局部对数变化 / 无量纲')
    elif name=='geometry_control':
        entry=next((v for v in manifest['counterfactuals'] if v['kind']=='fixed_radius'),None)
        if entry is None:raise RuntimeError('STUDY_PAYLOAD_MISSING: Q4 fixed-radius control; run compute_studies.py --group geometry --resume')
        d=StudyPlot_Load(root,entry);t=d['time_s']/3600
        endpoint_note='固定 R0 在 72 h 内未达标；' if entry['control_drying_time_h'] is None else ''
        fig,axes=StudyPlot_Create('附录 4 材料的几何对照',endpoint_note+'仅改变半径方案，材料均为附录 4')
        for prefix,label in [('base','真实 R(t)'),('control','固定 R0')]:
            for ax,key,scale in zip(axes.flat,['Cmax','Cmean','qualified_volume','radius_m'],[1,1,100,100]):ax.plot(t,d[prefix+'_'+key]*scale,label=label)
        for ax,label in zip(axes.flat,['Cmax / kg/kg','体积平均 C / kg/kg','达标几何体积 / %','半径 / cm']):ax.set_ylabel(label)
        axes[0,0].axhline(.15,color='grey',ls=':',lw=1,label='合格线 Cmax=0.15')
    elif name=='environment_robustness':
        entries=[v for v in manifest['counterfactuals'] if v['kind']=='tail']
        if len(entries)<4:raise RuntimeError('STUDY_PAYLOAD_MISSING: environment branches; run compute_studies.py --group environment --resume')
        fig,axes=StudyPlot_Create('环境尾窗敏感性','前 4 h 相同，末 30/60/90 min 均值分别使用 31/61/91 点；不表示置信区间')
        for col,case in enumerate(base):
            d=base[case];axes[0,col].plot(d['time_s']/3600,d['Cmax'],label='60 min 正式')
            for entry in entries:
                if entry['case']!=case:continue
                d=StudyPlot_Load(root,entry);t=d['time_s']/3600
                axes[0,col].plot(t,d['control_Cmax'],label=f"{entry['tail_minutes']} min")
                axes[1,col].plot(t,d['delta_Cmax'],label=f"{entry['tail_minutes']} − 60 min")
            axes[0,col].set(title=labels[case],ylabel='Cmax / kg/kg');axes[1,col].set_ylabel('共同时间 ΔCmax / kg/kg')
            if all(e['significance']=='not significant at numerical resolution' for e in entries if e['case']==case):
                axes[1,col].text(.03,.97,'在当前数值分辨率下不显著',transform=axes[1,col].transAxes,va='top',fontsize=9)
    elif name=='thermal_modes':
        fig,axes=StudyPlot_Create('四种热模型的温度与含水率','相同物理时间，均保留至 72 h；接近重合的曲线用线型区分')
        for col,case in enumerate(base):
            for mode,color,label in [('M00','#252525','均不计'),('M10','#d95f02','仅潜热'),('M01','#2678b2','仅携热'),('M11','#27865d','两者均计')]:
                d=StudyPlot_Load(root,StudyPlot_Find(manifest,case,mode));t=d['time_s']/3600
                style='--' if mode in ['M01','M11'] else '-'
                axes[0,col].plot(t,d['Tmin_K']-273.15,style,color=color,label=mode+' '+label)
                axes[1,col].plot(t,d['Cmax'],style,color=color,label=mode+' '+label)
            axes[0,col].set(title=labels[case],ylabel='最低温度 / °C');axes[1,col].set_ylabel('Cmax / kg/kg');axes[1,col].axhline(.15,color='grey',ls=':',lw=1,label='合格线 Cmax=0.15')
    elif name=='thermal_interactions':
        if len(manifest['interactions'])<2:raise RuntimeError('STUDY_REFERENCE_INCOMPLETE: four thermal modes required')
        fig,axes=StudyPlot_Create('热模型交互项','I=Y11−Y10−Y01+Y00；同一物理时刻；不解释为因果贡献')
        for col,entry in enumerate(manifest['interactions']):
            d=StudyPlot_Load(root,entry)
            axes[0,col].plot(d['time_s']/3600,d['Tmin_K']);axes[1,col].plot(d['time_s']/3600,d['Cmax'])
            axes[0,col].set(title=labels[entry['case']],ylabel='最低温度交互项 / K');axes[1,col].set_ylabel('Cmax 交互项 / kg/kg')
            for ax in axes[:,col]:ax.axhline(0,color='grey',lw=.8)
            overview=[]
            for row in manifest['summary_tables']['ThermalModes']:
                if row['case']!=entry['case']:continue
                td='未达标' if row['drying_time_h'] is None else f"{row['drying_time_h']:.3f} h"
                overview.append(f"{row['mode']}: td={td}, Tmin={row['minimum_temperature_C']:.2f} °C")
            axes[0,col].text(.98,.97,'\n'.join(overview),transform=axes[0,col].transAxes,va='top',ha='right',fontsize=8,
                bbox=dict(facecolor='white',alpha=.85,edgecolor='none'))
    elif name=='verification_evidence':
        checks=[c for c in manifest['checks'] if c['mode']=='M00' and c['full_schedule_reference_passed'] is not None]
        if len(checks)<3:raise RuntimeError('STUDY_REFERENCE_INCOMPLETE: full M00 schedules')
        fig,axes=StudyPlot_Create('完整阶段空间参考与事件证据','空间阈值：0.01 K / 0.01 kg/kg；事件相对阈值 0.2%；证据层不相加')
        for check in checks:
            d=StudyPlot_Load(root,dict(path=check['series_path']));label=check['case']+' '+check['status']
            axes[0,0].plot(d['time_s']/3600,d['abs_T_K'],label=label);axes[0,1].plot(d['time_s']/3600,d['abs_C'],label=label)
        axes[0,0].axhline(.01,color='grey',ls=':');axes[0,1].axhline(.01,color='grey',ls=':')
        axes[0,0].set_ylabel('最大输出点 ΔT / K');axes[0,1].set_ylabel('最大输出点 ΔC / kg/kg')
        event_checks=[c for c in checks if c['event_relative'] is not None]
        axes[1,0].bar([c['case'] for c in event_checks],[100*c['event_relative'] for c in event_checks],color=['#3465a4','#c65b38'])
        axes[1,0].axhline(.2,color='grey',ls=':');axes[1,0].set(xlabel='轨迹',ylabel='达标时间相对差 / %')
        event_rows=[r for r in manifest['summary_tables']['EventEvidence'] if r['mode']=='M00' and r.get('estimated_dt_s') is not None]
        if event_rows:
            x=np.arange(len(event_rows));actual={c['case']:c['event_delta_s'] for c in event_checks}
            axes[1,1].bar(x-.18,[r['estimated_dt_s'] for r in event_rows],width=.36,label='局部斜率估计')
            axes[1,1].bar(x+.18,[actual[r['case']] for r in event_rows],width=.36,label='实际完整参考差')
            axes[1,1].set(xticks=x,xticklabels=[r['case'] for r in event_rows],xlabel='轨迹',ylabel='|δtd| / s（N3 局部诊断）')
        else:
            axes[1,1].axis('off');axes[1,1].text(.05,.8,'N3 不适用：\n'+ '\n'.join(r['case']+': '+r['reason'] for r in manifest['summary_tables']['EventEvidence'] if r['mode']=='M00'),transform=axes[1,1].transAxes,va='top',wrap=True)
    else:raise ValueError(name)
    modes=['M00','M10','M01','M11'] if name in ['thermal_modes','thermal_interactions'] else ['M00']
    descriptions=[]
    for mode in modes:
        checks=[c for c in manifest['checks'] if c['mode']==mode]
        expected=3 if mode=='M00' else 6
        state='PASS' if len(checks)==expected and all(c['status']=='PASS' for c in checks) else 'FAIL' if any(c['status']=='FAIL' for c in checks) else 'INCOMPLETE'
        if any(a['status']!='PASS' for a in manifest.get('thermal_audits',[]) if manifest['specs'][a['experiment_id']]['mode']==mode):state='FAIL'
        descriptions.append(mode+' '+state)
    source='冻结 M00 一维' if modes==['M00'] else '冻结 M00 与一维热扩展'
    scope=''
    if name=='geometry_control':source='M00 方程：固定 R0 新对照与冻结 R(t) 基线';scope='；固定 R0 未独立加密'
    elif name=='environment_robustness':source='M00 方程：尾窗分支与冻结 60 min 基线';scope='；分支未独立加密'
    elif name=='end_effect_extent':source='冻结 M00 二维与匹配网格的一维对照';scope='；二维 PARTIAL，匹配一维未独立加密'
    fig.supxlabel(source+'；正式基线参考：'+', '.join(descriptions)+scope if scope else source+'；数值参考：'+', '.join(descriptions),fontsize=9)
    number=['end_effect_extent','drying_fronts','drying_kinetics','diffusion_clock_drivers','geometry_control','environment_robustness','thermal_modes','thermal_interactions','verification_evidence'].index(name)+1
    path=output/f'{number:02d}_{name}.png';StudyPlot_Finish(fig,axes,path);return path
