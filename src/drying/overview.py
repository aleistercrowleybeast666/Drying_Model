"""One-page human overview derived from current evidence; never solves PDEs."""
from datetime import datetime
from pathlib import Path
from .cases import Case_GetSourceHash, Case_LoadConfig
from .outputs import Output_ReadJson


def Overview_Format(value, digits=6):
    return '—' if value is None else f'{value:.{digits}g}'


def Overview_Stage(passed, exists=True):
    return 'PASS' if passed else 'FAIL' if exists else 'SKIPPED'


def Overview_Write(root):
    root = Path(root); config = Case_LoadConfig(root); num = config['numerics']
    levels = [config['mesh'][key] for key in ['base_nr','refined_nr','verification_nr']]
    status = Output_ReadJson(root/'results/status.json'); validation = Output_ReadJson(root/'work/validation/summary.json')
    comparisons = Output_ReadJson(root/'work/comparison/summary.json')
    code_hash = Case_GetSourceHash(root); input_hash = Output_ReadJson(root/'data/input_manifest.json').get('hash','—')
    cache = [Output_ReadJson(p) for p in (root/'work/cache').glob('*/status.json')]
    cache = [s for s in cache if s.get('source_hash') == code_hash]
    lookup = {s['case_id']:s for s in cache}; fmt = Overview_Format
    validation = {key:value for key,value in validation.items()
        if value.get('selected_id') in lookup and
        value.get('selected_fingerprint') == lookup[value['selected_id']]['fingerprint']}
    lines = ['# A题计算结果总览','',f'生成时间：{datetime.now().astimezone().isoformat(timespec="seconds")}',
        f'代码 hash：{code_hash[:16]}；输入 hash：{input_hash[:16]}。','',
        f'经典 RK4，请求 dt={num["dt_s"]} s，保留实际分区减半时间检查；梯度驱动静态非均匀有限体积。正式表格取一维；二维用于端面效应核验。ξ/η 面坐标固定，第四问仅按 R(t) 缩放。',
        '监测函数：T、C 实际范围归一化的梯度包络，M=1+√(GT²+GC²)，平滑/限幅后向均匀密度混合；同一冻结函数等监测量生成嵌套网格。','',
        '| 模型 | Pilot / 冻结强度 | 正式 nr / 验证 | Δr 初始 min–max；全程最小 (mm) | 二维 nr×nz / Δz (mm) |',
        '|---|---|---|---|---|']
    meshes = {}; warnings = []
    for case in ['q1','q23','q4']:
        mesh = Output_ReadJson(root/f'work/validation/mesh_profiles/{case}_mesh.json'); meshes[case] = mesh
        entry = validation.get(case+'_1d',{}); selected = lookup.get(entry.get('selected_id'),{})
        if not selected:
            candidates = [s for s in cache if s['case'] == case and s['dim'] == 1 and not s.get('tag') and s.get('complete')]
            selected = max(candidates,key=lambda s:s['nr']) if candidates else {}
        dr = selected.get('radial_initial',{}); minimum = selected.get('radial_minimum',{})
        two = next((s for s in cache if s['case'] == case and s['dim'] == 2 and not s.get('tag')),{})
        axial = two.get('axial',{})
        mm = lambda v: fmt(v*1000 if v is not None else None,5)
        reused = sum(bool(v.get('pilot_reused')) for v in mesh.get('profiles',{}).values())
        lines.append(f'| {case} | {reused}/2 缓存复用；{fmt(mesh.get("monitor_strength"))} | {selected.get("nr","—")} / {",".join(map(str,levels))} | {mm(dr.get("min"))}–{mm(dr.get("max"))}；{mm(minimum.get("min"))} | {two.get("nr","—")}×{two.get("nz","—")} / {mm(axial.get("min"))}–{mm(axial.get("max"))} |')
        if any(not s['dt_compatible'] for s in mesh.get('stability',[])):
            warnings.append(case+': ADAPTIVE_MESH_DT_CONFLICT（细网格与全程 0.25 s 不兼容；保护机制仍启用）')
    lines += ['','空间阈值：官方物理点 ΔT ≤ '+fmt(config['validation']['spatial']['temperature_abs_K'])+
        ' K、ΔC ≤ '+fmt(config['validation']['spatial']['moisture_abs'])+
        ' kg/kg；烘干时间相对差 ≤ '+fmt(100*config['validation']['spatial']['drying_time_relative'])+'%。数值验收不代表物理精度。','',
        f'| 模型 | {levels[0]}→{levels[1]} 官方 ΔT / ΔC | {levels[1]}→{levels[2]} 官方 ΔT / ΔC | {levels[1]}→{levels[2]} 全场 L∞ T / C；L2 T / C | 烘干时间差 s / % | 空间 |',
        '|---|---|---|---|---|---|']
    for case in ['q1','q23','q4']:
        entry = validation.get(case+'_1d',{}); pairs = entry.get('spatial_pairs',[])
        pair = pairs[-1] if pairs else {}
        peaks = lambda v: fmt(v.get('official_temperature',{}).get('value'))+' / '+fmt(v.get('official_moisture',{}).get('value'))
        field = ' / '.join(fmt(pair.get(key,{}).get('value')) for key in ['maxima_temperature','maxima_moisture'])
        rms = ' / '.join(fmt(pair.get(key,{}).get('value')) for key in ['volume_L2_temperature','volume_L2_moisture'])
        relative = pair.get('event_relative_difference')
        lines.append(f'| {case} | {peaks(pairs[0]) if pairs else "—"} | {peaks(pair)} | {field}；{rms} | {fmt(pair.get("event_difference_s"))} / {fmt(relative*100 if relative is not None else None)} | {Overview_Stage(entry.get("spatial_passed"),bool(pairs))} |')
        if pairs and not entry.get('spatial_passed'):
            warnings.append(case+': SPATIAL_CONVERGENCE_FAILED（'+', '.join(pair.get('failure_reasons',[]))+f'）；nr={entry.get("selected_nr",levels[-1])} 仅为最高分辨率候选')
    lines += ['','| 问题 | 阶段 P/M/S/T/G/D/E* | 计算范围 s / 结果 | 终点 T 范围 K；Cmax / 控制 r m | 表格 |',
        '|---|---|---|---|---|']
    for q in range(1,5):
        key = f'q{q}'; item = status.get('questions',{}).get(key,{}); case = item.get('source_case',{1:'q1',2:'q23',3:'q23',4:'q4'}[q])
        entry = validation.get(case+'_1d',{}); solved = lookup.get(item.get('one_id'),{})
        active = entry.get('selected_id') == item.get('one_id') and entry.get('selected_fingerprint') == solved.get('fingerprint')
        if not active: entry = {}
        two = validation.get(case+'_2d',{})
        stages = [Overview_Stage(bool(meshes[case].get('profiles')),bool(meshes[case])),
            Overview_Stage(bool(meshes[case]),bool(meshes[case])),Overview_Stage(solved.get('complete'),bool(solved)),
            Overview_Stage(item.get('time_convergence_passed'),bool(entry.get('temporal'))),
            Overview_Stage(item.get('spatial_convergence_passed'),bool(entry.get('spatial_pairs'))),
            Overview_Stage(two.get('spatial_passed'),bool(two.get('radial'))),
            Overview_Stage(item.get('official_output_generated'),bool(item))]
        ep = item.get('endpoint_values',{}); dry = item.get('drying_time')
        outcome = f'烘干 {fmt(dry/3600)} h' if dry is not None else item.get('drying_note','待计算')
        lines.append(f'| Q{q} | {"/".join(stages)} | 0–{fmt(item.get("simulation_end"))} / {outcome} | {fmt(ep.get("min_temperature_K"))}–{fmt(ep.get("max_temperature_K"))}；{fmt(ep.get("max_moisture"),10)} / {fmt(ep.get("controlling_r_m"))} | [result{q}.xlsx](tables/result{q}.xlsx) |')
        if entry.get('temporal') and not entry.get('time_passed'): warnings.append(case+': TIME_CONVERGENCE_FAILED')
    lines += ['','*P=Pilot，M=网格，S=生产计算，T=时间验证，G=一维空间验证，D=二维空间验证，E=导出；FAIL 包括未完成完整认证的部分二维核验，详见下列覆盖范围。','',
        '| 问题 | 1D/2D 最大 ΔT K / ΔC | C 差峰值 (t s, r m, z m) | 烘干时间差 s |',
        '|---|---|---|---|']
    for q in range(1,5):
        item = status.get('questions',{}).get(f'q{q}',{}); check = comparisons.get(f'q{q}',{})
        if not item.get('two_dimensional_check_completed'): check = {}
        if check.get('status') == 'END_EFFECT_NOT_NEGLIGIBLE':
            warnings.append(f'Q{q}: END_EFFECT_NOT_NEGLIGIBLE（一维/二维差值超过既有端面效应阈值）')
        peak = check.get('max_abs_moisture',{}); a,b = check.get('one_drying_time_h'),check.get('two_drying_time_h')
        delta = abs(a-b)*3600 if a is not None and b is not None else None
        lines.append(f'| Q{q} | {fmt(check.get("max_abs_temperature",{}).get("value"))} / {fmt(peak.get("value"))} | ({fmt(peak.get("time_s"))}, {fmt(peak.get("r_m"))}, {fmt(peak.get("z_m"))}) | {fmt(delta)} |')
    lines += ['', '一维/二维差值还包含未收敛的空间离散误差，不能单独视为纯端面效应。', '']
    for case in ['q1','q23','q4']:
        entry = validation.get(case+'_2d',{})
        if entry.get('numerical_status') == '2D_SPATIAL_VALIDATION_PARTIAL':
            windows = entry.get('endpoint_sensitivity',[])
            text = '；'.join(v['direction']+' '+fmt(v.get('event_difference_s'))+' s' for v in windows)
            lines.append(f'- {case} 二维：早期/代表时刻加密至 {fmt(entry.get("early_refinement_end_s"))} s；终点末段窗口敏感性 {text or "不适用"}（非全程误差）。')
            scope = '局部终点窗口继承粗网格早期误差' if windows else '仅作径向/轴向独立加密检查'
            warnings.append(case+': 2D_SPATIAL_VALIDATION_PARTIAL（'+scope+'，未作完整空间精度认证）')
            if any(v.get('status') == 'SPATIAL_REFERENCE_INCOMPLETE' for v in windows):
                warnings.append(case+': SPATIAL_REFERENCE_INCOMPLETE（局部窗口未找到参考终点）')
    lines += ['',f'旧均匀 nr={config["mesh"]["pilot_nr"]} 对照（新正式/候选减旧；官方点最大绝对差 T/C，烘干时间绝对差）：','']
    for case in ['q1','q23','q4']:
        old = validation.get(case+'_1d',{}).get('old_uniform_comparison',{})
        lines.append(f'- {case}: {fmt(old.get("official_temperature",{}).get("value"))} K / {fmt(old.get("official_moisture",{}).get("value"))} kg/kg；{fmt(old.get("event_difference_s"))} s。')
    lines += ['','计算性能（当前数值核心的缓存，耗时相加并非并行总历时）：','']
    for case in ['q1','q23','q4']:
        group = [s for s in cache if s['case'] == case]
        main = [s for s in group if not s.get('tag')]
        detail = ', '.join(f'{s["dim"]}D-{s["nr"]}×{s["nz"]}: {fmt(s.get("wall_s"),5)}s' for s in main)
        lines.append(f'- {case}: {detail or "待计算"}；含验证 {fmt(sum(s.get("wall_s",0) for s in group),6)} s。')
    event_rows = (root/'logs/events.jsonl').read_text(encoding='utf-8').splitlines() if (root/'logs/events.jsonl').exists() else []
    import json
    events = [json.loads(row) for row in event_rows if row.strip()]
    reuse = sum(row.get('event') == 'CACHE_REUSED' and row.get('case_id') in lookup for row in events)
    # Logger schema uses "code" in older runs; accept both explicit event keys.
    reuse += sum(row.get('code') == 'CACHE_REUSED' and row.get('case_id') in lookup for row in events if row.get('event') != 'CACHE_REUSED')
    total = sum(s.get('wall_s',0) for s in cache); peak = max((s.get('peak_rss_bytes',0) for s in cache),default=0)
    lines.append(f'- 求解/时间参考总计 {fmt(total,7)} s；采样 peak RSS {fmt(peak/1024**2,6)} MiB；当前缓存复用记录 {reuse} 次；pilot 复用 {sum(bool(v.get("pilot_reused")) for m in meshes.values() for v in m.get("profiles",{}).values())}/6。')
    formal_ids = {v.get('one_id') for v in status.get('questions',{}).values()}
    limited = [s for s in cache if s.get('complete') and s['case_id'] in formal_ids and s.get('limited')]
    if limited:
        lines.append('- 所选一维网格实际步长：'+'；'.join(f'{s["case"]} nr{s["nr"]}: min/平均 {fmt(s.get("minimum_dt"),5)}/{fmt(s["simulated_time_s"]/s["steps"],5)} s' for s in limited)+'。min 含输出短尾步；均值及稳定性限制次数说明长期缩步。')
    lines += ['','仍未解决的 WARNING/FAIL：','',*(['- '+w for w in dict.fromkeys(warnings)] or ['None.']),
        '','[完整状态](status.json)；网格及逐项验证：../work/validation/。']
    (root/'results/overview.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
