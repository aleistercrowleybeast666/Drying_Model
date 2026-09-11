"""Compact overview from an explicit evidence snapshot; rendering never reads caches."""
from datetime import datetime
from pathlib import Path
import json


def Overview_Format(value, digits=6):
    return '—' if value is None else f'{value:.{digits}g}'


def Overview_Gather(root):
    from .cases import Case_LoadConfig, Case_GetSourceHash, Case_ReadStatus, Case_GetSelected
    root = Path(root)
    def Read(name):
        path = root/name
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    sources = {}
    for case in ['q1','q23','q4']:
        for dim in [1,2]:
            case_id = Case_GetSelected(root,case,dim)
            if (root/'work/cache'/case_id/'status.json').exists():
                sources[f'{case}_{dim}d'] = Case_ReadStatus(root,case_id)
    return dict(generated_at=datetime.now().astimezone().isoformat(timespec='seconds'),
        input_hash=Read('data/input_manifest.json').get('hash'),source_hash=Case_GetSourceHash(root),
        config=Case_LoadConfig(root),status=Read('results/status.json'),
        validation=Read('work/validation/summary.json'),comparison=Read('work/comparison/summary.json'),
        compute=Read('work/diagnostics/compute_status.json'),sources=sources)


def Overview_Render(data):
    fmt = Overview_Format; cfg = data['config']; val = data['validation']; warnings = []; projection_lines=[]
    lines = ['# A题计算结果总览','',f'更新时间：{data["generated_at"]}',
        f'输入 hash：{data.get("input_hash", "—")[:16]}；物理离散核心 hash：{data["source_hash"][:16]}。','',
        '正式结果采用一维圆柱模型；二维轴对称模型核验端面影响。物性、边界、Q4 收缩及 Excel 格式保持既定定义。',
        f'经典 RK4，dt_max={cfg["numerics"]["dt_s"]} s 是上限；每步同时受当前网格稳定性、输入断点和输出/事件时刻约束。',
        '阶段内网格固定，切换时按环形体积重叠投影；T 体积积分仅为投影诊断，不等同于非线性焓守恒。','',
        '| 模型 | 当前正式/候选来源 | 阶段（s: Nr） | 实际 dt min / mean / max（s） |',
        '|---|---|---|---|']
    for case in ['q1','q23','q4']:
        question = {'q1':'q1','q23':'q3','q4':'q4'}[case]
        source = data['status'].get('questions',{}).get(question,{})
        entry = val.get(case+'_1d',{})
        stages = source.get('stage_dt_statistics') or [dict(t_start=0,t_end=source.get('cap'),nr=source.get('nr'),
            actual_dt_min=source.get('minimum_dt'),actual_dt_mean=source.get('cap',0)/source['steps'] if source.get('steps') else None,
            actual_dt_max=source.get('maximum_dt'))]
        schedule = '; '.join(f'{fmt(s["t_start"])}–{fmt(s["t_end"])}: {s["nr"]}' for s in stages)
        stats = '; '.join(' / '.join(fmt(s.get(k),5) for k in ['actual_dt_min','actual_dt_mean','actual_dt_max'])+
            f' (限步 {s.get("stability_limited_count",source.get("limited",0))})' for s in stages)
        lines.append(f'| {case} | {source.get("execution_mode","fixed")}<br>`{source.get("one_id","—")}` | {schedule} | {stats} |')
        if source.get('stability_limited_count'):
            warnings.append(case+': DT_LIMITED_BY_STABILITY（按稳定性减小实际步长，dt_max 上限保持不变）')
        if not source.get('spatial_convergence_passed'):
            warnings.append(case+': SPATIAL_CONVERGENCE_FAILED（严格误差或下降趋势未通过；当前结果为候选）')
        if any(not t['passed'] for t in entry.get('stage_schedule_trials',[])):
            warnings.append(case+': STAGE_COARSENING_TOO_AGGRESSIVE（部分阶段方案超出附加误差阈值，已据实回退）')
    lines += ['', '| 问题 | 求解 / 时间 / 正式空间 / 阶段敏感性 | 干燥时间 h | 终点 Cmax | Excel |',
              '|---|---|---|---|---|']
    def Flag(value): return 'PASS' if value else 'FAIL'
    for q in range(1,5):
        item = data['status'].get('questions',{}).get(f'q{q}',{})
        stages = '/'.join([Flag(item.get('solver_completed')),Flag(item.get('time_convergence_passed')),
            Flag(item.get('spatial_convergence_passed')),Flag(item.get('stage_schedule_passed')) if item.get('stage_schedule_enabled') else 'SKIPPED'])
        drying = item.get('drying_time')
        lines.append(f'| Q{q} | {stages} | {fmt(drying/3600 if drying is not None else None)} | {fmt(item.get("endpoint_values",{}).get("max_moisture"),10)} | [result{q}.xlsx](tables/result{q}.xlsx) |')
        if not item.get('time_convergence_passed'): warnings.append(f'Q{q}: TIME_VALIDATION_INCOMPLETE_OR_FAILED')
    lines += ['', '以下正式状态、来源、阶段网格及烘干时间均取自最新 status.json。',
              '', '| 问题 | fixed-grid validation（legacy / diagnostic only） | stage-schedule validation | official spatial convergence |',
              '|---|---|---|---|']
    for q in range(1,5):
        item = data['status'].get('questions',{}).get(f'q{q}',{})
        lines.append(f'| Q{q} | {Flag(item.get("fixed_grid_spatial_passed"))} | {Flag(item.get("stage_schedule_spatial_passed"))} | {Flag(item.get("spatial_convergence_passed"))} |')
    lines += ['', '| 模型 | 固定 80→160 最大 ΔT / ΔC（legacy / diagnostic only） | 阶段方案相对固定 160：ΔT / ΔC / Δt(s) / Δt(%) |',
              '|---|---|---|']
    for case in ['q1','q23','q4']:
        entry = val.get(case+'_1d',{}); pair = (entry.get('spatial_pairs') or [{}])[-1]
        baseline = fmt(pair.get('official_temperature',{}).get('value'))+' / '+fmt(pair.get('official_moisture',{}).get('value'))
        trials = []
        for trial in entry.get('stage_schedule_trials',[]):
            relative = trial.get('event_relative_difference')
            active_id=data['status'].get('questions',{}).get({'q1':'q1','q23':'q3','q4':'q4'}[case],{}).get('one_id')
            role='current production' if trial.get('schedule_id')==active_id else 'legacy / diagnostic only'
            trials.append('→'.join(str(s['nr']) for s in trial.get('schedule',[]))+f' ({role}): '+
                ' / '.join([fmt(trial['official_temperature']['value']),fmt(trial['official_moisture']['value']),
                    fmt(trial.get('event_difference_s')),fmt(relative*100 if relative is not None else None)])+' '+Flag(trial['passed']))
        lines.append(f'| {case} | {baseline} | {"; ".join(trials) or "SKIPPED"} |')
        if not entry.get('fixed_grid_spatial_passed',entry.get('spatial_passed')):
            peak=pair.get('official_moisture',{})
            reason='早期表面含水率分辨率不足' if peak.get('time_s',float('inf'))<=600 and peak.get('value',0)>cfg['validation']['spatial']['moisture_abs'] else '固定网格正式误差或下降趋势超限'
            projection_lines.append(f'- {case} 旧 fixed 80→160 FAIL（legacy / diagnostic only）：{reason}；ΔC={fmt(peak.get("value"))}，t={fmt(peak.get("time_s"))} s，不否决已通过的正式阶段方案。')
        early=entry.get('early_refinement')
        if early:
            peak=early['official_moisture']
            projection_lines.append(f'- {case} 早期 {early.get("early_production_nr","—")}→{early.get("early_reference_nr",cfg["validation"]["spatial"]["early_refined_nr"])}（0–{fmt(early["reference_end_s"])} s）：'
                f'ΔC={fmt(peak["value"])}，t={fmt(peak["time_s"])} s，r={fmt(peak["r_m"])} m；'
                f'局部严格 {Flag(early["passed"])}；下降趋势 {Flag(early["convergence_trend"]["passed"])}。')
            if not early['passed']: warnings.append(case+': EARLY_SPATIAL_CONVERGENCE_FAILED（200→400 局部参考仍超限或趋势未通过）')
        internal=pair.get('all_internal_times_max_error',{}); official=pair.get('official_output_times_max_error',{})
        projection_lines.append(f'- {case} 80→160：内部步 ΔC={fmt(internal.get("moisture",{}).get("value"))}；'
            f'正式输出时刻 ΔC={fmt(official.get("moisture",{}).get("value"))}。')
        question = {'q1':'q1','q23':'q3','q4':'q4'}[case]
        attempts = data['status'].get('questions',{}).get(question,{}).get('stage_schedule_attempts',[])
        transfers = [v for a in attempts for v in a['transfers']]
        if transfers:
            projection_lines.append(f'- 投影 {case}：最大 ΔT={fmt(max(v["projection_max_abs_T"] for v in transfers))} K，'
                f'ΔC={fmt(max(v["projection_max_abs_C"] for v in transfers))}；体积积分相对误差 '
                f'T/C={fmt(max(v["volume_integral_relative_error_T"] for v in transfers))}/'
                f'{fmt(max(v["volume_integral_relative_error_C"] for v in transfers))}。')
        for attempt in attempts:
            if attempt['case_id'] != data['sources'].get(case+'_1d',{}).get('case_id'):
                stats = '; '.join(f'nr{s["nr"]}: '+ '/'.join(fmt(s[k],5) for k in
                    ['actual_dt_min','actual_dt_mean','actual_dt_max'])+f' (限步 {s.get("stability_limited_count","—")})'
                    for s in attempt['stage_dt_statistics'])
                projection_lines.append(f'- {case} 未采用阶段方案 dt min/mean/max（s）：{stats}。')
    tol = cfg['validation']['spatial']
    lines += ['',*projection_lines,'',f'阈值：ΔT≤{tol["temperature_abs_K"]} K、ΔC≤{tol["moisture_abs"]} kg/kg、干燥时间相对差≤{100*tol["drying_time_relative"]:g}%。正式阶段空间 PASS = 早期 200→400 PASS ∧ 阶段精度 PASS ∧ 网格切换完整性/守恒 PASS；旧 fixed 结果仅作诊断。','',
        '| 问题 | 一维/二维最大 ΔT / ΔC | C 差峰值 (t s, r m, z m) |', '|---|---|---|']
    for q in range(1,5):
        item = data['comparison'].get(f'q{q}',{}); peak = item.get('max_abs_moisture',{})
        lines.append(f'| Q{q} | {fmt(item.get("max_abs_temperature",{}).get("value"))} / {fmt(peak.get("value"))} | '
            f'({fmt(peak.get("time_s"))}, {fmt(peak.get("r_m"))}, {fmt(peak.get("z_m"))}) |')
        if item.get('status') == 'END_EFFECT_NOT_NEGLIGIBLE': warnings.append(f'Q{q}: END_EFFECT_NOT_NEGLIGIBLE')
    if any(v.get('numerical_status') == '2D_SPATIAL_VALIDATION_PARTIAL' for k,v in val.items() if k.endswith('_2d')):
        warnings.append('2D_SPATIAL_VALIDATION_PARTIAL（早期/代表时刻方向加密及局部终点核验，不是全程空间认证）')
    sources = list(data['sources'].values()); run = data.get('compute',{})
    lines += ['', '斜切 GIF 使用真实二维场及各自二维烘干终点；正式 Excel 使用一维生产方案及一维终点。',
        '一维/二维差值仍包含空间离散误差，不能单独视为纯端面效应。',
        '正式判定只使用题目要求的输出时刻及烘干终点，并要求正式误差随加密下降。内部 RK4 子步与回投影误差仅作审计，超阈值记日志、不否决；内部审计的时间插值不用于终点场值判定。',
        '选用轨迹求解耗时合计 '+fmt(sum(s.get('wall_s',0) for s in sources))+' s；采样 peak RSS '+
        fmt(max((s.get('peak_rss_bytes',0) for s in sources),default=0)/1024**2)+' MiB。',
        f'本次 compute 状态：{run.get("status","—")}；阶段：{run.get("phase","—")}；wall time：{fmt(run.get("wall_s"))} s。']
    if run.get('status') == 'FAILED': warnings.append('COMPUTE_FAILED: '+run.get('error',''))
    lines += ['', '仍未解决的 WARNING/FAIL：','',*(['- '+w for w in dict.fromkeys(warnings)] or ['None.']),
        '', '[完整状态](status.json)；逐项验证见 work/validation；独立绘图入口为 plot.py。']
    return '\n'.join(lines)+'\n'


def Overview_Write(root, evidence=None):
    data = Overview_Gather(root) if evidence is None else evidence
    path = Path(root)/'results/overview.md'; path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(Overview_Render(data),encoding='utf-8')
    return data
