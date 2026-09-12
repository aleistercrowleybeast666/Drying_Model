"""Separated evidence layers, control contrasts, and factorial interactions."""
from pathlib import Path
import numpy as np
from ..storage import Storage_WriteArray,Storage_WriteJson
from .baseline import Baseline_HashFile,Baseline_ReadJson
from .analysis import Analysis_LoadSeries
from .metrics import Metrics_GetEventSensitivity,Metrics_GetStages


def Synthesis_Find(manifest,case,mode='M00',kind='production',tail=60):
    if mode=='M00' and kind=='production':return manifest['baseline_keys'][case]
    return next((key for key,entry in manifest['series'].items() if entry['case']==case and entry['mode']==mode
        and entry['kind']==kind and manifest['specs'][key]['tail_minutes']==tail),None)


def Synthesis_Build(root,manifest,publish=True):
    root=Path(root);tables={name:[] for name in ['Index','Verification','EndEffects','FrontMilestones','DryingStages',
        'Geometry','Environment','ThermalModes','Interactions','EventEvidence','EvidenceLayers','Sources']}
    baseline=Baseline_ReadJson(root/'work/baseline_snapshot/baseline_manifest.json');series={}
    rule_path=root/'configs/studies_analysis.json';rule=Baseline_ReadJson(rule_path)['stage_identification']
    manifest['stage_identification_rule']=dict(rule,source=rule_path.relative_to(root).as_posix(),sha256=Baseline_HashFile(rule_path),
        interpretation='median rates near the beginning of the pre-peak limb and end of the post-peak limb; configured fraction of each limb; both contrasts required and at least 3 samples per limb; no state smoothing')
    for case in ['q1','q23','q4']:
        evidence=baseline['validation'][case+'_1d']
        for name,passed in [('frozen time validation',evidence['time_passed']),('frozen official stage validation',evidence['spatial_passed'])]:
            tables['Verification'].append(dict(case=case,mode='M00',evidence=name,status='PASS' if passed else 'FAIL',
                production_id=evidence['selected_id'],source='work/baseline_snapshot/baseline_manifest.json#validation/'+case+'_1d',
                scope='frozen pre-extension certification; distinct from new full-schedule reference'))
        for pair in evidence.get('spatial_pairs',[]):
            internal=pair.get('all_internal_times_max_error',{})
            tables['Verification'].append(dict(case=case,mode='M00',evidence='legacy fixed grid / diagnostic only',
                production_id=pair['coarse_id'],reference_id=pair['fine_id'],status='PASS' if pair['passed'] else 'FAIL',role='legacy / diagnostic only',
                failure_reasons=pair.get('failure_reasons',[]),
                max_abs_T_K=pair.get('official_temperature',{}).get('value'),max_abs_C=pair.get('official_moisture',{}).get('value'),
                scope='legacy comparison cannot veto current stage production'))
            if internal:
                tables['Verification'].append(dict(case=case,mode='M00',evidence='internal RK4 audit / diagnostic only',
                    reference_id=pair['fine_id'],status='COMPLETE_DIAGNOSTIC' if internal.get('complete') else 'INCOMPLETE',
                    max_abs_T_K=internal.get('temperature',{}).get('value'),max_abs_C=internal.get('moisture',{}).get('value'),
                    sample_count=internal.get('sample_count'),scope='internal accepted-step union; not official output acceptance',
                    source='work/baseline_snapshot/baseline_manifest.json#validation/'+case+'_1d/spatial_pairs'))
    for key,entry in manifest['series'].items():
        data=Analysis_LoadSeries(root,entry);series[key]=data;status=manifest['statuses'][key];spec=manifest['specs'][key]
        event=status.get('event');td=status.get('drying_time_h');tt=entry['thermal_equilibration_time_s']
        if spec['kind']=='production':
            tables['Index'].append(dict(case=spec['case'],mode=spec['mode'],experiment_id=key,status=status['status'],
                source='frozen official M00' if entry['baseline'] else 'supplementary 1D model',time_cap_h=data['time_s'][-1]/3600,
                drying_time_h=td,reason='' if event else 'Q1 observation window; no drying endpoint required' if spec['case']=='q1' else 'NOT_DRY_WITHIN_72H'))
            stage_row=dict(case=spec['case'],mode=spec['mode'],tT_s=tt,tC_h=td,
                tT_status=entry['thermal_equilibration_status'],
                tC_over_tT=td*3600/tt if td is not None and tt else None,
                peak_mean_loss_time_h=float(data['time_s'][np.nanargmax(data['loss_Cmean_s'])]/3600),
                peak_mean_loss_kg_kg_s=float(np.nanmax(data['loss_Cmean_s'])),
                reason='thermal equilibration to environment applies only to M00; no forced three-stage pattern',
                rule_source='configs/studies_analysis.json')
            for quantity in ['Cmax','Cmean']:
                identified=Metrics_GetStages(data['time_s'],data['loss_'+quantity+'_s'],rule,event['report_s'] if event else None)
                stage_row.update({quantity+'_'+k:v for k,v in identified.items()})
            tables['DryingStages'].append(stage_row)
            for i,threshold in enumerate([2.,1.,.5,.15]):
                dry=np.flatnonzero(data['front_status'][:,i]=='ALL_DRY');j=int(dry[0]) if len(dry) else None
                partial=np.flatnonzero(data['front_status'][:,i]!='ALL_WET');start=int(partial[0]) if len(partial) else None
                center=np.flatnonzero(data['Ccenter']<=threshold)
                tables['FrontMilestones'].append(dict(case=spec['case'],mode=spec['mode'],threshold_kg_kg=threshold,
                    first_non_all_wet_sample_h=float(data['time_s'][start]/3600) if start is not None else None,
                    preceding_non_all_wet_sample_h=float(data['time_s'][max(0,start-1)]/3600) if start is not None else None,
                    first_center_threshold_sample_h=float(data['time_s'][center[0]]/3600) if len(center) else None,
                    first_all_dry_sample_h=float(data['time_s'][j]/3600) if j is not None else None,
                    preceding_sample_h=float(data['time_s'][max(0,j-1)]/3600) if j is not None else None,
                    multiple_or_non_core_samples=int(np.isin(data['front_status'][:,i],['MULTIPLE_CROSSINGS','NON_CORE']).sum()),
                    official_threshold=threshold==.15,source='sample bracket; official endpoint uses Event_Locate',
                    status='REACHED' if j is not None else 'NOT_REACHED'))
            if entry['baseline']:
                for metric,quadrature in [('theta_V',entry['clock_quadrature']),('theta_c',entry['clock_center_quadrature'])]:
                    tables['Verification'].append(dict(case=spec['case'],mode='M00',evidence='diffusion-clock temporal quadrature diagnostic',
                        metric=metric,unit='dimensionless',full_sampling_integral=quadrature['full'],
                        half_sampling_integral=quadrature['half_sampling'],absolute_difference=quadrature['absolute_difference'],
                        relative_difference=quadrature['absolute_difference']/max(abs(quadrature['full']),1e-30),
                        status='CHECKED_DIAGNOSTIC',production_id=key,scope='actual saved timestamps versus every second timestamp; not PDE time validation'))
            if spec['case']!='q1':
                check=next((c for c in manifest['checks'] if c['production_id']==key and c['full_schedule_reference_passed'] is not None),None)
                error=max((e['Cmax'] for e in check['events']),default=None) if check else None
                sensitivity=Metrics_GetEventSensitivity(data['time_s'],data['Cmax'],data['ties'][:,1],data['ties'][:,2],event,error) if error is not None else dict(status='NOT_APPLICABLE',reason='full reference unavailable',estimated_dt_s=None)
                tables['EventEvidence'].append(dict(case=spec['case'],mode=spec['mode'],dimension=1,production_id=key,drying_time_h=td,
                    **({k:event[k] for k in ['left_s','right_s','width_s','raw_event_s','report_s','left_max_C','right_max_C','report_max_C']} if event else {}),
                    report_condition_passed=bool(event['report_max_C']<spec['physics']['threshold']) if event else None,
                    event_state_source='saved Event_Locate genuine reintegration state' if event else 'no drying event',
                    **sensitivity))
            tables['ThermalModes'].append(dict(case=spec['case'],mode=spec['mode'],latent=spec['mode'] in ['M10','M11'],
                explicit_moisture_heat=spec['mode'] in ['M01','M11'],drying_time_h=td,
                event_reason='' if event else 'Q1 observation window; no drying endpoint required' if spec['case']=='q1' else 'NOT_DRY_WITHIN_72H',
                final_Cmax=float(data['Cmax'][-1]),final_Cmean=float(data['Cmean'][-1]),last_real_time_h=float(data['time_s'][-1]/3600),
                balance_verification=next((a['status'] for a in manifest.get('thermal_audits',[]) if a['experiment_id']==key),'NOT_APPLICABLE_M00' if entry['baseline'] else 'INCOMPLETE'),
                water_domain_status='NOT_APPLICABLE_M00' if entry['baseline'] else 'PASS' if data['Tmin_K'].min()>=spec['water']['temperature_range_K'][0] and data['Tmax_K'].max()<=spec['water']['temperature_range_K'][1] else 'THERMAL_MODEL_OUT_OF_DOMAIN',
                minimum_temperature_C=float(data['Tmin_K'].min()-273.15),minimum_moisture=float(data['profile'][:,1].min()),
                status=status['status'],time_verification=next((c['status'] for c in manifest['checks'] if c['production_id']==key and c['time_half_passed'] is not None),
                    'BASELINE_CERTIFIED' if entry['baseline'] else 'INCOMPLETE'),
                space_verification=next((c['status'] for c in manifest['checks'] if c['production_id']==key and c['full_schedule_reference_passed'] is not None),'INCOMPLETE')))
    for check in manifest['checks']:
        tables['Verification'].append({k:v for k,v in check.items() if not isinstance(v,(dict,list))})
        for metric,unit,key in [('temperature','K','max_abs_T_K'),('moisture','kg/kg','max_abs_C'),('event','s','event_delta_s')]:
            tables['EvidenceLayers'].append(dict(case=check['case'],mode=check['mode'],layer='time' if check['time_half_passed'] is not None else 'full spatial',
                metric=metric,unit=unit,value=check[key],reference=check['reference_id'],status=check['status'],
                range_s=str(check['common_time_range_s']),meaning='numerical comparison, not physical uncertainty'))
    for check in manifest.get('historical_checks',[]):
        tables['Verification'].append(dict(case=check['case'],mode=check['mode'],evidence='superseded supplemental mesh',
            reference_id=check['reference_id'],status=check['status'],role=check['role'],max_abs_T_K=check['max_abs_T_K'],max_abs_C=check['max_abs_C']))
    for case in ['q1','q23','q4']:
        main=manifest['baseline_keys'][case];reference=series[main]
        for mode in ['M10','M01','M11']:
            key=Synthesis_Find(manifest,case,mode)
            if not key:continue
            actual=series[key];times,bi,oi=np.intersect1d(reference['time_s'],actual['time_s'],return_indices=True)
            for metric,unit in [('Cmax','kg/kg'),('Tmin_K','K')]:
                value=float(np.max(np.abs(actual[metric][oi]-reference[metric][bi])))
                tables['EvidenceLayers'].append(dict(case=case,mode=mode,layer='thermal structure',metric='max common-time '+metric+' difference',
                    unit=unit,value=value,reference=main,status='MODEL_COMPARISON',range_s=str([float(times[0]),float(times[-1])]),
                    meaning='alternative effective thermal closure; not numerical error or experimental uncertainty'))
    for effect in manifest['end_effects']:
        tables['EndEffects'].append({k:v for k,v in effect.items() if not isinstance(v,dict)})
        for metric in ['T','C']:
            tables['EvidenceLayers'].append(dict(case=effect['case'],mode='M00',layer='dimension',metric='affected depth '+metric,
                unit='m',value=effect['max_depth_'+metric+'_m'],reference='matched 1D versus frozen 2D',status='PARTIAL_2D',
                meaning='matched grid model discrepancy; partial 2D refinement'))
    manifest['counterfactuals']=[];manifest['interactions']=[]
    for case in ['q23','q4']:
        key=Synthesis_Find(manifest,case);base=series[key];base_td=manifest['statuses'][key].get('drying_time_h')
        controls=[('tail',30),('tail',90)]+([('fixed_radius',60)] if case=='q4' else [])
        for kind,tail in controls:
            other_key=Synthesis_Find(manifest,case,kind=kind,tail=tail)
            if not other_key:continue
            other=series[other_key];times,bi,oi=np.intersect1d(base['time_s'],other['time_s'],return_indices=True)
            delta=other['Cmax'][oi]-base['Cmax'][bi];other_td=manifest['statuses'][other_key].get('drying_time_h')
            check=next((c for c in manifest['checks'] if c['production_id']==key and c['full_schedule_reference_passed'] is not None),None)
            resolution=check['max_abs_Cmax'] if check else None
            inputs=baseline['input'];metadata=dict(case=case,kind=kind,tail_minutes=tail,control_id=other_key,reference_id=key,
                control_drying_time_h=other_td,baseline_drying_time_h=base_td,
                last_common_time_h=float(times[-1]/3600),last_control_Cmax=float(other['Cmax'][oi[-1]]),last_baseline_Cmax=float(base['Cmax'][bi[-1]]),
                relative_shortening_fraction=(other_td-base_td)/other_td if other_td is not None and base_td is not None else None,
                event_comparison_reason='' if other_td is not None and base_td is not None else 'at least one trajectory has no drying event; no duration or percentage inferred from cap',
                drying_time_difference_h=other_td-base_td if other_td is not None and base_td is not None else None,
                max_common_Cmax_difference=float(np.max(np.abs(delta))),
                comparison_resolution_Cmax=resolution,resolution_basis='maximum common-time Cmax discrepancy in the full stage reference',
                control_accuracy_scope='control uses the frozen M00 stage strategy; no independent control-grid refinement was budgeted; main-reference discrepancy is diagnostic only',
                status='COMPARED' if other_td is not None and base_td is not None else 'NOT_DRY_WITHIN_72H',
                significance='not significant at numerical resolution' if resolution is not None and np.max(np.abs(delta))<=resolution else 'exceeds current comparison resolution' if resolution is not None else 'reference incomplete',
                interpretation='fixed appendix-4 material, change only shrinkage' if kind=='fixed_radius' else 'tail-window sensitivity, not a confidence interval')
            if kind=='tail':
                from .trajectory import Trajectory_GetInputs
                env,rad,tail_values=Trajectory_GetInputs(root,manifest['specs'][other_key])
                metadata.update(tail_sample_count=tail+1,tail_T_C=float(tail_values[0]-273.15),tail_H=float(tail_values[1]),
                    common_branch_time_s=14400.,initial_history='identical frozen M00 trajectory through 14400 s')
            path=root/f'work/studies/plot_payload/{case}_{kind}_{tail}_contrast.npz'
            Storage_WriteArray(path,time_s=times,base_Cmax=base['Cmax'][bi],control_Cmax=other['Cmax'][oi],
                base_Cmean=base['Cmean'][bi],control_Cmean=other['Cmean'][oi],delta_Cmax=delta,
                base_qualified_volume=1-base['fronts'][bi,3,2],control_qualified_volume=1-other['fronts'][oi,3,2],
                base_radius_m=base['radius_m'][bi],control_radius_m=other['radius_m'][oi])
            metadata.update(path=path.relative_to(root).as_posix(),sha256=Baseline_HashFile(path))
            manifest['counterfactuals'].append(metadata);tables['Geometry' if kind=='fixed_radius' else 'Environment'].append(metadata)
            tables['EvidenceLayers'].append(dict(case=case,mode='M00',layer='geometry' if kind=='fixed_radius' else 'tail window',
                metric='common Cmax difference',unit='kg/kg',value=metadata['max_common_Cmax_difference'],reference=other_key,status=metadata['status'],
                meaning=metadata['interpretation']))
        keys=[Synthesis_Find(manifest,case,mode=m) for m in ['M00','M10','M01','M11']]
        if all(keys):
            times=series[keys[0]]['time_s']
            for k in keys[1:]:times=np.intersect1d(times,series[k]['time_s'])
            values={name:np.array([series[k][name][np.searchsorted(series[k]['time_s'],times)] for k in keys]) for name in ['Cmax','Tmin_K']}
            interaction={name:a[3]-a[1]-a[2]+a[0] for name,a in values.items()}
            td=[manifest['statuses'][k].get('drying_time_h') for k in keys]
            td_interaction=td[3]-td[1]-td[2]+td[0] if all(v is not None for v in td) else None
            path=root/f'work/studies/plot_payload/{case}_interactions.npz';Storage_WriteArray(path,time_s=times,**interaction)
            info=dict(case=case,path=path.relative_to(root).as_posix(),sha256=Baseline_HashFile(path),
                interaction_drying_time_h=td_interaction,status='COMPLETE' if td_interaction is not None else 'EVENT_INTERACTION_NOT_APPLICABLE',
                maximum_abs_I_Cmax=float(np.max(np.abs(interaction['Cmax']))),maximum_abs_I_Tmin_K=float(np.max(np.abs(interaction['Tmin_K']))),
                definition='Y11-Y10-Y01+Y00 at common physical times; model interaction, not causal attribution')
            manifest['interactions'].append(info);tables['Interactions'].append(info)
    for case in ['q23','q4']:
        k=manifest['baseline_keys'][case]
        from .trajectory import Trajectory_GetInputs
        env,rad,tail_values=Trajectory_GetInputs(root,manifest['specs'][k])
        tables['Environment'].append(dict(case=case,tail_minutes=60,tail_sample_count=61,tail_T_C=float(tail_values[0]-273.15),
            tail_H=float(tail_values[1]),status='FROZEN_MAIN_MODEL',control_id=k,drying_time_difference_h=0.))
    for key,status in manifest['statuses'].items():
        for transfer in status.get('transfers',[]):
            tables['EvidenceLayers'].append(dict(case=manifest['specs'][key]['case'],mode=manifest['specs'][key]['mode'],layer='remesh',
                metric='relative volume integral C',unit='dimensionless',value=transfer['volume_integral_relative_error_C'],reference=key,
                status='PASS' if transfer['volume_integral_relative_error_C']<=1e-12 else 'FAIL',range_s=transfer['switch_time'],
                meaning='conservative projection diagnostic; temperature integral is not mixture enthalpy'))
    for source,meaning in [('https://iapws.org/technical-guidance/release/IF97-Rev','saturation water properties for supplementary thermal modes only'),
        ('https://iapws.readthedocs.io/en/stable/iapws.iapws97.html','iapws 1.5.5 SI conversion and state path'),
        ('https://cantera.org/stable/reference/onedim/governing-equations.html','gradient-of-species-enthalpy form; no copied flame physics'),
        ('data/input_manifest.json','problem materials, attachment environment/radius; frozen M00 inputs')]:
        tables['Sources'].append(dict(source=source,scope=meaning))
    tables['Sources'].append(dict(assumption_id='B7_DIFFUSION_CLOCK',unit='dimensionless',scope='state-geometry diagnostic',
        definition='Theta_V uses volume-weighted D and actual R/t; it is not an exact transformation to a constant-coefficient PDE and does not require curve collapse',
        source='sealed trajectory time_s, Dmean_m2_s and radius_m arrays; quadrature checks in Verification'))
    water_path=root/'work/studies/diagnostics/water_properties.json'
    if water_path.exists():
        water=Baseline_ReadJson(water_path)
        for name,value in water.items():
            tables['Sources'].append(dict(assumption_id='THERMAL_WATER_IF97',quantity=name,value=value,
                unit='J/kg' if name=='interpolation_max_abs_J_kg' else 'K' if name=='temperature_range_K' else '',source=water_path.relative_to(root).as_posix(),scope='M10/M01/M11 only'))
    for key,definition,unit in [
        ('THERMAL_DRY_MASS','b0=rho(C0)/(1+C0); b(t)=b0*(R0/R(t))²; not pointwise rho(C)/(1+C)','kg/m³'),
        ('THERMAL_EFFECTIVE_CAPACITY','K=rho(C)*cp(C) is independent empirical heat capacity; no claim of full mixture energy conservation','J/(m³ K)'),
        ('THERMAL_ENTHALPY_GRADIENT','sensible source is -Jw dot grad(hl); invariant to enthalpy reference shift','W/m³'),
        ('THERMAL_SIGNED_LATENT','outer boundary only, signed Jw=b*hm*(Cs-H); condensation reverses latent flux','W/m²'),
        ('THERMAL_FIXED_RADIUS_HISTORY','all Q4 modes use the same given R(t), not thermally predicted shrinkage','m')]:
        tables['Sources'].append(dict(assumption_id=key,definition=definition,unit=unit,scope='effective supplemental closure',source='work/studies/diagnostics/thermal_assumptions.md'))
    manifest['summary_tables']=tables
    from .plan import Plan_Build
    Plan_Build(manifest,series)
    manifest['warnings']=['2D refinement remains PARTIAL; dimension differences are not experimental validation.',
        'Independent evidence layers must not be added into a single physical error.',
        'Legacy fixed-grid failures remain diagnostic only; frozen official stage acceptance is unchanged.']
    manifest['warnings'] += [f"{c['case']} {c['mode']} {c['reference_id']}: {c['status']}" for c in manifest['checks'] if c['status']!='PASS']
    manifest['warnings'] += [f"{c['experiment_id']}: {c['status']}" for c in manifest.get('thermal_audits',[]) if c['status']!='PASS']
    rows=['# Drying_Model 扩展结果','',f"冻结基线：`{manifest['baseline_id']}`。M00 正式 Excel 与正式状态保持不变。",'',
        '| 轨迹 | 模式 | 事件状态 | 烘干时间 / h |','|---|---|---|---|']
    for row in tables['Index']:rows.append(f"| {row['case']} | {row['mode']} | {row['status']} | {row['drying_time_h'] if row['drying_time_h'] is not None else '—'} |")
    rows+=['','正式 M00：Q1–Q4 原阶段空间认证均为 PASS。完整阶段加密参考是新增独立证据：','',
        '| 轨迹 | 模式 | 验证 | 最大 ΔT / K | 最大 ΔC / kg/kg | 事件相对差 |','|---|---|---|---|---|---|']
    for check in manifest['checks']:
        label='实际半步重放' if check['time_half_passed'] is not None else '完整阶段空间参考'
        rows.append(f"| {check['case']} | {check['mode']} | {label}: {check['status']} | {check['max_abs_T_K']:.6g} | {check['max_abs_C']:.6g} | {check['event_relative']} |")
    rows+=['','旧 fixed-grid 80→160：legacy / diagnostic only。早期表面含水率分辨率不足不会否决当前正式阶段方案。','',
        '仅热扩展引入外部水物性。假设与单位见 `work/studies/diagnostics/thermal_assumptions.md`。',
        '72 h 是模拟上限；无真实达标事件时烘干时间为空。','',*['- '+w for w in manifest['warnings']],'']
    if publish:
        path=root/'results/studies/overview.md';path.parent.mkdir(parents=True,exist_ok=True);path.write_text('\n'.join(rows),encoding='utf-8')
        from .export import Studies_Export
        manifest['workbooks']=Studies_Export(root,manifest)


def Synthesis_RefreshOverview(root):
    """Compute-side status refresh without changing payload seals or workbooks."""
    from .baseline import Baseline_Check
    from .plot_contract import StudyPlot_ReadManifest
    root=Path(root);baseline=Baseline_Check(root);manifest=StudyPlot_ReadManifest(root)
    index=Baseline_ReadJson(root/'results/studies/study_index.json')
    receipt=root/'work/studies/diagnostics/render_manifest.json'
    render=Baseline_ReadJson(receipt) if receipt.exists() else {};valid=[]
    if render.get('manifest_seal')==manifest['seal']:
        valid=[v for v in render.get('files',[]) if (root/v['path']).exists() and Baseline_HashFile(root/v['path'])==v['sha256']]
    png=sum(v['path'].endswith('.png') for v in valid);gif=sum(v['path'].endswith('.gif') for v in valid)
    books=sum((root/v['path']).exists() and Baseline_HashFile(root/v['path'])==v['sha256'] for v in manifest['workbooks'])
    geometry=next((v for v in manifest['counterfactuals'] if v['kind']=='fixed_radius'),None)
    geometry_note='B8：固定半径对照尚缺，见 study_index.json。'
    if geometry:
        endpoint=f"烘干时间 {geometry['control_drying_time_h']:.4f} h" if geometry['control_drying_time_h'] is not None else '72 h 未达标，烘干时间及相对缩短率为空'
        geometry_note=f"B8：附录 4 固定半径对照 {endpoint}；末态真实 Cmax={geometry['last_control_Cmax']:.6f} kg/kg。只与附录 4 的 R(t) 方案比较。"
    tails=[v for v in manifest['counterfactuals'] if v['kind']=='tail']
    insignificant=sum(v['significance']=='not significant at numerical resolution' for v in tails)
    sensitivity=manifest['summary_tables']['EventEvidence'];applicable=sum(v['status']=='APPLICABLE' for v in sensitivity)
    gui_path=root/'work/studies/diagnostics/gui_cli_check.json';gui=Baseline_ReadJson(gui_path) if gui_path.exists() else {}
    gui_ok=gui.get('status')=='PASS' and gui.get('app_sha256')==Baseline_HashFile(root/'app.py')
    gui_note='GUI 隐藏窗口配置及实际只读 CLI 子进程检查通过，未做完整人工点击验收。' if gui_ok else 'GUI 需要补充当前版本的交互验收；CLI 可独立使用。'
    lines=['# Drying_Model 扩展结果','',f"基线核验：{baseline['status']}；冻结 ID `{manifest['baseline_id']}`。M00 正式四表、生产数组与事件保持不变。",'',
        f"新增实验完成 {index['current_complete_count']}/{index['expected_experiment_count']}；实际产物：{books}/5 工作簿，{png}/9 PNG，{gif}/2 GIF（文件 hash 与当前 payload 核对）。",'',
        '| 轨迹 | 热模式 | 生产网格 | 烘干时间 / h | 最低温度 / °C | 时间验证 | 完整空间参考 | 收支检查 |','|---|---|---|---|---|---|---|---|']
    for r in manifest['summary_tables']['ThermalModes']:
        td=f"{r['drying_time_h']:.4f}" if r['drying_time_h'] is not None else '— / Q1 观察窗' if r['case']=='q1' else '72 h 未达标'
        key=Synthesis_Find(manifest,r['case'],r['mode'])
        grid='→'.join(str(stage['nr']) for stage in manifest['specs'][key]['schedule'])
        balance=r['balance_verification'] if r['mode']!='M00' else '原模型证据'
        lines.append(f"| {r['case']} | {r['mode']} | {grid} | {td} | {r['minimum_temperature_C']:.4f} | {r['time_verification']} | {r['space_verification']} | {balance} |")
    lines += ['', 'B1/B2：Q1–Q4 已输出匹配径向分辨率下的端面深度、体积分数及控制区域；二维仍为 PARTIAL。',
        'B3–B7/B9：并列控制区、前沿、分别识别的速率阶段、M00 热响应、扩散时钟与收缩时序已输出。',
        geometry_note,
        f'B10：30/60/90 min 尾窗使用 31/61/91 点，已完成 {len(tails)}/4 个对照，其中 {insignificant} 个共同时间 Cmax 差在当前数值分辨能力下不显著；B11 复用真实重新积分事件；B12 分层展示证据。',
        f'N1 已核验点值对数恒等式；N2 四热组合交互按共同物理时间计算；N3 有 {applicable}/{len(sensitivity)} 个事件满足控制区稳定和斜率窗口要求，其余明确记不适用。C 类未加入。','',
        '旧 fixed-grid 80→160：legacy / diagnostic only。原正式阶段方案 Q1–Q4 均为 PASS；完整阶段参考另列。',
        '没有新增 3D 静态图。原 5 个 GIF 原字节迁入 `results/animations/`；新 2 个 GIF 位于 `results/studies/animations/`。','',
        '入口：`compute_studies.py --group all --resume`；已有完整缓存只刷新数据用 `--payload-only`；绘图用 `plot_studies.py`；绘后核对本页用 `compute_studies.py --output-status-only`。GUI 为 `app.py`，仅调用 CLI。',
        '缓存源由 manifest 明确引用；修改绘图样式不改变数值缓存。'+gui_note,'',
        '需人工审阅的假设：干物质有效质量基准、独立经验热容量、饱和路径水焓/潜热、各热模式共享给定 R(t)。见 `work/studies/diagnostics/thermal_assumptions.md`；本扩展不是实验精度认证。','']
    if manifest.get('technical_extension'):
        from .technical_contract import Technical_ReadPayload
        technical=Technical_ReadPayload(root,manifest);cross=technical['geometry_property_cross'];timing=technical['kinetics_summary']
        lines += ['', '## 最终技术补全', '',
            f"独立交叉轨迹 3/3（生产、完整加密、实际半步重放），验证 {technical['cross_validation']['status']}；原 38 个实验及原验证证据保留。", '',
            '| 交叉组 | 烘干时间 / h | Cmax(72 h) / kg/kg | 验证状态 |', '|---|---:|---:|---|']
        for row in cross['groups']:
            td=f"{row['drying_time_h']:.4f}" if row['drying_time_h'] is not None else '72 h 未达标 / null'
            lines.append(f"| {row['group']} | {td} | {row['Cmax_72h']:.6f} | {row['convergence_status']} |")
        lines += ['',f"Q4 峰值时序：T={timing['t_T_peak']:.0f} s，C={timing['t_C_peak']:.0f} s；R 最大速率区间 {timing['R_peak_interval_start']:.0f}–{timing['R_peak_interval_end']:.0f} s。",
            f"t50：T={timing['t_T50']:.1f} s，C={timing['t_C50']:.1f} s，R={timing['t_R50']:.1f} s。时差与导数定义见 `../paper_facts.json`。",
            '本轮只更新 03/05 两张静态图；全部 7 个 GIF 保持字节一致。',
            '本轮刷新：`compute_studies.py --group geometry_cross --resume --payload-only`；只重画两图：`plot_studies.py --technical-only`。',
            '论文唯一直接引用数字来源：`../paper_facts.json` / `../paper_facts.md`；P4 固定组未独立加密，交互项为结构诊断。']
        for case,record in technical['refinement2d'].get('cases',{}).items():
            lines.append(f"二维 60×188 {case}：{record['status']}；{record['reason']}。")
    lines += ['- '+w for w in manifest['warnings']]
    from .mass_report import MassReport_GetLines, MassReport_ReadSummary
    lines += MassReport_GetLines(MassReport_ReadSummary(root))
    from ..auxiliary2d import Auxiliary_GetLines, Auxiliary_ReadSummary
    lines += Auxiliary_GetLines(Auxiliary_ReadSummary(root))
    (root/'results/studies/overview.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(f'OVERVIEW_REFRESHED workbooks={books}/5 png={png}/9 gif={gif}/2',flush=True)
