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

- 2D refinement remains PARTIAL; dimension differences are not experimental validation.
- Independent evidence layers must not be added into a single physical error.
- Legacy fixed-grid failures remain diagnostic only; frozen official stage acceptance is unchanged.
