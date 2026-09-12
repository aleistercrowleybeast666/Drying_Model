"""Generate traceable paper numbers from validated results; no hard-coded answers."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import numpy as np
from ..storage import Storage_WriteJson
from .baseline import Baseline_ReadJson
from .plot_contract import StudyPlot_Load


def PaperFacts_GetHash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def PaperFacts_Build(root, manifest, technical, publish=True):
    root = Path(root);baseline = Baseline_ReadJson(root/'work/baseline_snapshot/baseline_manifest.json')
    official_status = Baseline_ReadJson(root/'results/status.json')['questions']
    generated = datetime.now(timezone.utc).isoformat()
    def Provenance(key, path, study='official_M00'):
        spec = manifest['specs'].get(key, technical['cross_validation']['specs'][0])
        return dict(source_case_id=key, source_file=path, input_hash=baseline['input']['hash'],
            physics_hash=PaperFacts_GetHash(dict(physics=spec['physics'], mode=spec['mode'],
                material_model=spec.get('material_appendix', {'q1':1, 'q23':3, 'q4':4}[spec['case']]), shrink=spec['shrink'],
                material_formula_sha256=baseline['protected_files']['src/drying/materials.py']['sha256'],
                boundary_definition_sha256=baseline['protected_files']['src/drying/boundaries.py']['sha256'],
                thermal_extension_sha256=spec['source'].get('thermal.py'))),
            study_id=study, generated_at=generated)
    facts = dict(schema_version=1, generated_at=generated, baseline_id=baseline['baseline_id'],
        purpose='only direct numerical quotation source for subsequent paper writing',
        units=dict(time='s unless explicitly suffixed h', temperature='K in arrays; C for Celsius display', moisture='kg water/kg dry material',
            length='m', volume_fraction='dimensionless', diffusivity='m²/s'), official={}, numerical={}, two_dimensional={}, studies={})
    conflicts = []
    for question, case, end in [('Q1','q1',1800.), ('Q2','q23',10800.), ('Q3','q23',None), ('Q4','q4',None)]:
        key = manifest['baseline_keys'][case];status = manifest['statuses'][key];data = StudyPlot_Load(root, manifest['series'][key])
        official = official_status[question.lower()]
        end = end if end is not None else status['event']['report_s']
        i = int(np.searchsorted(data['time_s'], end))
        if abs(data['time_s'][i]-end)>1e-8:raise RuntimeError('PAPER_FACTS_ENDPOINT_MISSING: '+question)
        values = dict(time_s=float(end), Tcenter_C=float(data['Tcenter_K'][i]-273.15),
            Tsurface_C=float(data['radial'][i,0,-1]-273.15), Ccenter=float(data['Ccenter'][i]),
            Csurface=float(data['radial'][i,1,-1]), Cmax=float(data['Cmax'][i]), Cmean=float(data['Cmean'][i]))
        record = dict(Provenance(key, manifest['series'][key]['path']), question=question, mode='M00',
            official_Excel_path=official['table'], key_values=values,
            drying_completed=bool(official['drying_completed']), drying_time_s=official['drying_time'],
            drying_time_h=official['drying_time']/3600 if official['drying_time'] is not None else None,
            endpoint_Cmax=values['Cmax'], controlling_location=dict(r_min_m=float(data['ties'][i,1]),
                r_max_m=float(data['ties'][i,2]), tied_node_count=int(data['ties'][i,0]),
                representative='smallest r among tolerance-tied maxima; no resolved axial coordinate in 1D'),
            convergence_status=dict(time=official['time_convergence_passed'], spatial=official['spatial_convergence_passed']),
            array_sha256=manifest['series'][key]['sha256'])
        if question=='Q4':record['R_at_endpoint_m']=float(data['radius_m'][i])
        if official['one_id'] != key:conflicts.append(dict(question=question, field='source_case_id', formal=official['one_id'], payload=key))
        if abs(official['endpoint_values']['max_moisture']-values['Cmax'])>1e-10:
            conflicts.append(dict(question=question, field='endpoint_Cmax', formal=official['endpoint_values']['max_moisture'], payload=values['Cmax']))
        facts['official'][question]=record
        selected=baseline['selected'][case+'_1d']
        check=next(c for c in manifest['checks'] if c['production_id']==key and c['full_schedule_reference_passed'] is not None)
        facts['numerical'][question]=dict(Provenance(key, 'results/status.json#questions/'+question.lower(), 'numerical_validation'),
            method='classical RK4', dt_max_s=official['requested_dt_max'], stage_schedule=selected['schedule'],
            actual_dt_min_s=official['actual_dt_range_s'][0], actual_dt_mean_s=official['mean_accepted_dt_s'],
            actual_dt_max_s=official['actual_dt_range_s'][1], stage_dt_statistics=official['stage_dt_statistics'],
            full_schedule_reference=check['reference_schedule'], reference_case_id=check['reference_id'],
            max_delta_T_K=check['max_abs_T_K'], max_delta_C=check['max_abs_C'],
            drying_time_relative_difference=check['event_relative'], full_schedule_reference_passed=check['full_schedule_reference_passed'],
            scope='reference evidence covers the full shared trajectory; Q2/Q3 share q23; event errors use genuine reintegration')
    for case in ['q23','q4']:
        selected=baseline['selected'][case+'_2d'];validation=baseline['validation'][case+'_2d']
        effect=next(e for e in manifest['end_effects'] if e['question']==('Q3' if case=='q23' else 'Q4'))
        refined=technical['refinement2d'].get('cases',{}).get(case,{})
        facts['two_dimensional'][case]=dict(source_case_id=selected['case_id'],source_file=effect['path'],
            input_hash=selected['input_hash'],physics_hash=PaperFacts_GetHash(dict(physics=selected['physics'], material_appendix=3 if case=='q23' else 4, shrink=case=='q4', numerical_core=selected['source_hash'])),
            study_id='two_dimensional_check',generated_at=generated,array_sha256=effect['sha256'],
            validation_status='PARTIAL_2D', refinement_status=refined.get('status','NOT_ATTEMPTED'),
            full_refinement_record=refined, independent_grid_certification=False,
            end_effect_depth_T_m=effect['max_depth_T_m'],end_effect_depth_C_m=effect['max_depth_C_m'],
            affected_volume_fraction_T=effect['max_volume_fraction_T'],affected_volume_fraction_C=effect['max_volume_fraction_C'],
            controlling_point_conclusion=effect['event_control_status'], control_checked_samples=effect['control_checked_samples'],
            drying_time_h=selected['drying_time_h'], endpoint_sensitivity=validation['endpoint_sensitivity'],
            terminology='二维核验 / 二维加密结果 / 端面效应敏感性; not an exact or fully converged 2D solution')
    for name, sheet in [('B4','FrontMilestones'),('B5_B6','DryingStages')]:
        rows=[]
        for row in manifest['summary_tables'][sheet]:
            if row['mode']=='M00' and row['case'] in ['q23','q4']:
                key=manifest['baseline_keys'][row['case']]
                rows.append(dict(row,**Provenance(key,manifest['series'][key]['path'],name)))
        facts['studies'][name]=rows
    clocks=[]
    for case in ['q23','q4']:
        key=manifest['baseline_keys'][case];entry=manifest['series'][key];data=StudyPlot_Load(root,entry)
        end=manifest['statuses'][key]['event']['report_s'];i=int(np.searchsorted(data['time_s'],end))
        clocks.append(dict(Provenance(key,entry['path'],'B7'),case=case,official_endpoint_s=end,
            theta_V_endpoint=float(data['theta_V'][i]),theta_c_endpoint=float(data['theta_c'][i]),
            theta_V_72h=float(data['theta_V'][-1]),theta_c_72h=float(data['theta_c'][-1]),
            quadrature=entry['clock_quadrature'],meaning='state/geometry diagnostic; not an exact constant-coefficient PDE transform'))
    facts['studies']['B7']=clocks
    cross=technical['geometry_property_cross'];geometry=[]
    for row in cross['groups']:
        geometry.append(dict(row,**Provenance(row['source_case_id'],cross['path'],'geometry_property_cross')))
    facts['studies']['geometry_2x2']=dict(groups=geometry,interactions=cross['interactions'],
        interaction_definition=cross['interaction_definition'],inference_scope=cross['inference_scope'],array_sha256=cross['sha256'],
        source_file=cross['path'],source_case_id=cross['source_ids'],input_hash=baseline['input']['hash'],
        physics_hash=[row['physics_hash'] for row in geometry],study_id='geometry_property_cross',generated_at=generated)
    validation=technical['cross_validation']
    facts['studies']['geometry_2x2']['new_cross_validation']=dict(status=validation['status'],inherited_pass=False,
        source_file='work/studies/technical/validation/cross_summary.json',
        production_id=validation['specs'][0]['experiment_id'],checks=validation.get('checks',[]),
        remesh_transfer_statuses=[r['status'] for r in validation.get('transfers',[])],
        event_check_statuses=[r['status'] for r in validation.get('events',[])])
    environment=[]
    for case in ['q23','q4']:
        key=manifest['baseline_keys'][case];base=manifest['statuses'][key]['drying_time_h'];values=[]
        for minutes in [30,60,90]:
            if minutes==60:source_key=key;td=base
            else:
                source_key=next(k for k,s in manifest['specs'].items() if s['case']==case and s['kind']=='tail' and s['tail_minutes']==minutes)
                td=manifest['statuses'][source_key]['drying_time_h']
            values.append(dict(Provenance(source_key,manifest['series'][source_key]['path'],'B10'),tail_minutes=minutes,
                sample_count=minutes+1,drying_time_h=td,relative_change_to_60min=(td-base)/base if td is not None else None))
        environment.append(dict(case=case,values=values,max_absolute_relative_change=max(abs(row['relative_change_to_60min']) for row in values if row['relative_change_to_60min'] is not None),
            meaning='input-tail sensitivity; not a confidence interval'))
    facts['studies']['B10']=environment
    thermal=[]
    for row in manifest['summary_tables']['ThermalModes']:
        if row['case'] not in ['q23','q4']:continue
        key=manifest['baseline_keys'][row['case']] if row['mode']=='M00' else next(k for k,s in manifest['specs'].items()
            if s['case']==row['case'] and s['mode']==row['mode'] and s['kind']=='production')
        base=manifest['statuses'][manifest['baseline_keys'][row['case']]]['drying_time_h']
        thermal.append(dict(row,**Provenance(key,manifest['series'][key]['path'],'thermal_modes'),
            relative_change_to_M00=(row['drying_time_h']-base)/base if row['drying_time_h'] is not None else None))
    facts['studies']['thermal']=dict(results=thermal,
        conclusions=[dict(case=case,latent_models_dry_later=all(next(r for r in thermal if r['case']==case and r['mode']==m)['drying_time_h'] >
            next(r for r in thermal if r['case']==case and r['mode']==base)['drying_time_h'] for m,base in [('M10','M00'),('M11','M01')]),
            qualification='supplemental effective-model structural comparison under prescribed common R(t), not experimental validation') for case in ['q23','q4']])
    timing=technical['kinetics_summary'];key=timing['source_case_id']
    facts['studies']['kinetics']=dict(timing,**Provenance(key,technical['kinetics'][key]['path'],'q4_peak_response_timing'),
        array_sha256=technical['kinetics'][key]['sha256'])
    facts['source_conflicts']=conflicts
    facts['draft_comparison']=dict(status='NO_PAPER_DRAFT_PROVIDED',scope='current official status versus payload checked; historical fixed results remain labeled diagnostics')
    facts['warnings']=['2D remains PARTIAL_2D; one finer complete trajectory cannot certify grid independence',
        'P4_fixed lacks independent refinement; factorial interactions are diagnostic',
        'Peak times resolve saved output times; t50 values are interpolated response clocks, not Event_Locate events']
    if cross['interactions']['drying_time_h'] is None:facts['warnings'].append(cross['interactions']['drying_time_reason']+'; no drying-time interaction')
    if timing['C_peak_at_window_boundary']:facts['warnings'].append('Q4 mean-moisture rate maximum is a window-boundary estimate, not an identified interior peak')
    if conflicts:raise RuntimeError('PAPER_FACTS_SOURCE_CONFLICT: '+json.dumps(conflicts))
    from .mass_report import MassReport_ReadSummary
    mass_summary=MassReport_ReadSummary(root)
    if mass_summary:facts['solver_mass_balance']=mass_summary
    from ..auxiliary2d import Auxiliary_ReadSummary, Auxiliary_AttachSummary, KEY
    auxiliary = Auxiliary_ReadSummary(root)
    if auxiliary:Auxiliary_AttachSummary(facts,auxiliary)
    if publish:
        Storage_WriteJson(root/'results/paper_facts.json',facts)
        PaperFacts_WriteMarkdown(root,facts)
    return facts


def PaperFacts_WriteMarkdown(root,facts):
    lines=['# 论文事实冻结表','',f"自动生成于 {facts['generated_at']}。完整来源、单位与未舍入数值见 `paper_facts.json`。",'',
        '## 正式结果','','| 问题 | 时刻 / h | 中心温度 / ℃ | 表面含水率 / kg/kg | 最大含水率 / kg/kg |','|---|---:|---:|---:|---:|']
    for q,row in facts['official'].items():
        v=row['key_values'];lines.append(f"| {q} | {v['time_s']/3600:.4f} | {v['Tcenter_C']:.4f} | {v['Csurface']:.6f} | {v['Cmax']:.9f} |")
    statuses='；'.join(q+' 时间 '+('PASS' if row['convergence_status']['time'] else 'FAIL')+' / 空间 '+('PASS' if row['convergence_status']['spatial'] else 'FAIL') for q,row in facts['official'].items())
    dt_values='/'.join(str(v) for v in sorted(set(row['dt_max_s'] for row in facts['numerical'].values())))
    lines+=['','Q1/Q2 为规定观察时刻；Q3/Q4 为正式一维烘干事件。Q4 终点半径 '+f"{facts['official']['Q4']['R_at_endpoint_m']*100:.4f} cm。",'',
        '## 数值验证','',f'经典 RK4，dt_max={dt_values} s；{statuses}。完整阶段参考独立记录：','',
        '| 问题 | 最大 ΔT / K | 最大 ΔC / kg/kg | 事件相对差 / % |','|---|---:|---:|---:|']
    for q,row in facts['numerical'].items():
        diff='—' if row['drying_time_relative_difference'] is None else f"{100*row['drying_time_relative_difference']:.5f}"
        lines.append(f"| {q} | {row['max_delta_T_K']:.6g} | {row['max_delta_C']:.6g} | {diff} |")
    lines+=['','## 二维核验','','二维独立性仍为 PARTIAL；60×188 本轮状态：']
    for case,row in facts['two_dimensional'].items():
        lines.append(f"- {case}：{row['refinement_status']}；最大 T/C 影响深度 {100*row['end_effect_depth_T_m']:.3f}/{100*row['end_effect_depth_C_m']:.3f} cm，受影响体积 {100*row['affected_volume_fraction_T']:.2f}%/{100*row['affected_volume_fraction_C']:.2f}%。")
    lines+=['','## 几何—物性交叉','','| 组 | 烘干时间 / h | Cmax(72h) | Cmean(72h) | 达标体积分数(72h) |','|---|---:|---:|---:|---:|']
    geometry=facts['studies']['geometry_2x2']
    for row in geometry['groups']:
        td='72 h 未干' if row['drying_time_h'] is None else f"{row['drying_time_h']:.4f}"
        lines.append(f"| {row['group']} | {td} | {row['Cmax_72h']:.6f} | {row['Cmean_72h']:.6f} | {row['qualified_volume_fraction_72h']:.6f} |")
    i=geometry['interactions'];duration_note='烘干时长交互不适用（'+i['drying_time_reason']+'）。' if i['drying_time_h'] is None else f"烘干时长交互={i['drying_time_h']:.4f} h。"
    lines+=['',f"72 h 交互 I（P4收缩−P4固定−P3收缩＋P3固定）：Cmax={i['Cmax_72h']:.6f}，Cmean={i['Cmean_72h']:.6f}，达标体积分数={i['qualified_volume_fraction_72h']:.6f}。{duration_note}",'',
        '## 环境敏感性','']
    for row in facts['studies']['B10']:
        times='/'.join(f"{v['drying_time_h']:.4f}" if v['drying_time_h'] is not None else '未干' for v in row['values'])
        lines.append(f"- {row['case']} 30/60/90 min 尾窗：{times} h；最大相对变化 {100*row['max_absolute_relative_change']:.5f}%。")
    lines+=['','## 热模型','','| 模式 | Q3 / h | Q4 / h | Q3/Q4 最低温度 / ℃ |','|---|---:|---:|---:|']
    thermal=facts['studies']['thermal']['results']
    for mode in ['M00','M10','M01','M11']:
        a=next(r for r in thermal if r['case']=='q23' and r['mode']==mode);b=next(r for r in thermal if r['case']=='q4' and r['mode']==mode)
        lines.append(f"| {mode} | {a['drying_time_h']:.4f} | {b['drying_time_h']:.4f} | {a['minimum_temperature_C']:.3f}/{b['minimum_temperature_C']:.3f} |")
    k=facts['studies']['kinetics'];boundary_note='（观察窗边界）' if k['C_peak_at_window_boundary'] else '（内部峰值）'
    lines+=['','## 动力学时序','',
        f"Q4 观察窗：0–{k['observation_end_s']:.2f} s（正式终点）。峰值：T={k['t_T_peak']:.0f} s；C={k['t_C_peak']:.0f} s{boundary_note}；R={k['R_peak_interval_start']:.0f}–{k['R_peak_interval_end']:.0f} s。",'',
        f"峰值滞后（目标减来源）：R→T 相对区间起/终点为 {k['delta_R_to_T_interval_start_s']:.0f}/{k['delta_R_to_T_interval_end_s']:.0f} s；R→C 为 {k['delta_R_to_C_interval_start_s']:.0f}/{k['delta_R_to_C_interval_end_s']:.0f} s；T→C={k['delta_T_to_C']:.0f} s。",'',
        f"t50：T={k['t_T50']:.1f} s；C={k['t_C50']:.1f} s；R={k['t_R50']:.1f} s。对应 R→T、R→C、T→C 滞后为 {k['delta_R50_to_T50']:.1f}、{k['delta_R50_to_C50']:.1f}、{k['delta_T50_to_C50']:.1f} s。",'',
        '## 注意事项','',
        '- 只有 M00 一维是官方结果；热模式与几何交叉组是补充研究。',
        '- P4固定半径组未达标且未独立加密；不伪造时长或交互精度认证。',
        '- 旧 fixed 网格失败仅作诊断；二维仍未完成网格独立性认证。',
        '- 峰值和 t50 为时序诊断，均值/差分定义与括区见 JSON；不称相位角。',
        '- 未提供论文初稿；当前正式汇总与数据源未发现数字冲突。']
    from .mass_report import MassReport_GetLines
    lines+=MassReport_GetLines(facts.get('solver_mass_balance'))
    from ..auxiliary2d import Auxiliary_GetLines, KEY
    lines+=Auxiliary_GetLines(facts.get(KEY))
    path=Path(root)/'results/paper_facts.md';temporary=path.with_suffix('.tmp.md')
    temporary.write_text('\n'.join(lines)+'\n',encoding='utf-8');temporary.replace(path)
