# Drying_Model 扩展结果

基线核验：PASS；冻结 ID `52a1433275fe31fa47ce7c80b1373e98c50508de5544f573123311138fdce7e2`。M00 正式四表、生产数组与事件保持不变。

新增实验完成 38/38；实际产物：5/5 工作簿，9/9 PNG，2/2 GIF（文件 hash 与当前 payload 核对）。

| 轨迹 | 热模式 | 生产网格 | 烘干时间 / h | 最低温度 / °C | 时间验证 | 完整空间参考 | 收支检查 |
|---|---|---|---|---|---|---|---|
| q1 | M00 | 200→160→80→40 | — / Q1 观察窗 | 28.0000 | BASELINE_CERTIFIED | PASS | 原模型证据 |
| q23 | M00 | 200→160→80 | 57.6215 | 28.0000 | BASELINE_CERTIFIED | PASS | 原模型证据 |
| q4 | M00 | 200→160→80→40 | 51.1824 | 28.0000 | BASELINE_CERTIFIED | PASS | 原模型证据 |
| q1 | M10 | 200→160→80→40 | — / Q1 观察窗 | 8.9120 | PASS | PASS | PASS |
| q23 | M10 | 200→160→80 | 60.6681 | 10.2234 | PASS | PASS | PASS |
| q1 | M01 | 200→160→80→40 | — / Q1 观察窗 | 28.0000 | PASS | PASS | PASS |
| q23 | M01 | 200→160→80 | 57.6227 | 28.0000 | PASS | PASS | PASS |
| q4 | M10 | 400→320→160→80 | 56.5393 | 14.0791 | PASS | PASS | PASS |
| q4 | M01 | 200→160→80→40 | 51.1834 | 28.0000 | PASS | PASS | PASS |
| q1 | M11 | 200→160→80→40 | — / Q1 观察窗 | 8.9559 | PASS | PASS | PASS |
| q23 | M11 | 200→160→80 | 60.6693 | 10.2529 | PASS | PASS | PASS |
| q4 | M11 | 400→320→160→80 | 56.5404 | 14.0951 | PASS | PASS | PASS |

B1/B2：Q1–Q4 已输出匹配径向分辨率下的端面深度、体积分数及控制区域；二维仍为 PARTIAL。
B3–B7/B9：并列控制区、前沿、分别识别的速率阶段、M00 热响应、扩散时钟与收缩时序已输出。
B8：附录 4 固定半径对照 72 h 未达标，烘干时间及相对缩短率为空；末态真实 Cmax=0.224925 kg/kg。只与附录 4 的 R(t) 方案比较。
B10：30/60/90 min 尾窗使用 31/61/91 点，已完成 4/4 个对照，其中 1 个共同时间 Cmax 差在当前数值分辨能力下不显著；B11 复用真实重新积分事件；B12 分层展示证据。
N1 已核验点值对数恒等式；N2 四热组合交互按共同物理时间计算；N3 有 8/8 个事件满足控制区稳定和斜率窗口要求，其余明确记不适用。C 类未加入。

旧 fixed-grid 80→160：legacy / diagnostic only。原正式阶段方案 Q1–Q4 均为 PASS；完整阶段参考另列。
没有新增 3D 静态图。原 5 个 GIF 原字节迁入 `results/animations/`；新 2 个 GIF 位于 `results/studies/animations/`。

入口：`compute_studies.py --group all --resume`；已有完整缓存只刷新数据用 `--payload-only`；绘图用 `plot_studies.py`；绘后核对本页用 `compute_studies.py --output-status-only`。GUI 为 `app.py`，仅调用 CLI。
缓存源由 manifest 明确引用；修改绘图样式不改变数值缓存。GUI 隐藏窗口配置及实际只读 CLI 子进程检查通过，未做完整人工点击验收。

需人工审阅的假设：干物质有效质量基准、独立经验热容量、饱和路径水焓/潜热、各热模式共享给定 R(t)。见 `work/studies/diagnostics/thermal_assumptions.md`；本扩展不是实验精度认证。


## 最终技术补全

独立交叉轨迹 3/3（生产、完整加密、实际半步重放），验证 PASS；原 38 个实验及原验证证据保留。

| 交叉组 | 烘干时间 / h | Cmax(72 h) / kg/kg | 验证状态 |
|---|---:|---:|---|
| P3_fixed | 57.6215 | 0.137832 | PASS |
| P3_shrink | 25.2756 | 0.103439 | PASS |
| P4_fixed | 72 h 未达标 / null | 0.224925 | NOT_INDEPENDENTLY_REFINED |
| P4_shrink | 51.1824 | 0.123755 | PASS |

Q4 峰值时序：T=1800 s，C=0 s；R 最大速率区间 0–1800 s。
t50：T=3055.7 s，C=16018.5 s，R=8450.0 s。时差与导数定义见 `../paper_facts.json`。
本轮只更新 03/05 两张静态图；全部 7 个 GIF 保持字节一致。
本轮刷新：`compute_studies.py --group geometry_cross --resume --payload-only`；只重画两图：`plot_studies.py --technical-only`。
论文唯一直接引用数字来源：`../paper_facts.json` / `../paper_facts.md`；P4 固定组未独立加密，交互项为结构诊断。
二维 60×188 q23：PARTIAL_2D；MANDATORY_WORK_PRIORITY: only cost probe retained; full refinement deferred for the newly requested solver mass audit; no full-trajectory or grid-independence claim。
二维 60×188 q4：PARTIAL_2D；MANDATORY_WORK_PRIORITY: only cost probe retained; full refinement deferred for the newly requested solver mass audit; no full-trajectory or grid-independence claim。
- 2D refinement remains PARTIAL; dimension differences are not experimental validation.
- Independent evidence layers must not be added into a single physical error.
- Legacy fixed-grid failures remain diagnostic only; frozen official stage acceptance is unchanged.

## 水质量守恒审计

solver_mass_balance：PASS；已完成 12/12 个完整生产轨迹。
最大绝对残差 1.121325e-13 kg；最大相对残差 5.021739e-13。
Q4 换网格最大水质量跳变 2.775558e-17 kg。
采用实际接受的 RK4 步与原边界通量积分；导出数据仅作诊断。完整记录：`work/validation/mass_balance/`。
独立审计阈值：相对残差 ≤ 1.0e-10，换网格相对质量跳变 ≤ 1.0e-12；未修改空间或时间收敛阈值。

| 模式 | Q1 | Q23 | Q4 |
|---|---|---|---|
| M00 | PASS | PASS | PASS |
| M10 | PASS | PASS | PASS |
| M01 | PASS | PASS | PASS |
| M11 | PASS | PASS | PASS |
