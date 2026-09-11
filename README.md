# A题药材烘干求解工程

打开 `A_Drying.code-workspace` 即可在 VS Code 中使用已配置的 Python 环境和任务。当前源码、原始输入、缓存、图表、日志均在本目录内。

Windows PowerShell（在本目录执行）：

```powershell
# 本机已经安装好独立环境。换电脑时：
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 日常只需两个入口，均支持复用匹配缓存：
.\.venv\Scripts\python.exe compute.py
.\.venv\Scripts\python.exe plot.py

# 测试；仅刷新绘图数据（不解 PDE）：
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe compute.py --payload-only
# 求解、验证和导出均完成，只有最后汇总/打包失败时：
.\.venv\Scripts\python.exe compute.py --resume-finalize

```

`solve` 支持 `--nr`、`--nz`、`--dt`、`--cap`（秒）、`--tag`、`--mesh uniform|adaptive`。默认空间模式取配置；`validate` 按配置执行 40/80/160 并自动选正式网格。运行中每模拟一小时写检查点；重复同一命令可续算。输入、物性/离散核心或配置哈希不一致时拒绝复用；实验性改变请使用新 `--tag`，不要覆盖旧缓存。网格面坐标、冻结 monitor 哈希进入 case 指纹，旧均匀缓存只可作为经过校验的 pilot/对照。`run.py` 保留低层调试命令；`run.py all` 顺序调用 compute.py 和 plot.py。日常修改图样后只运行 plot.py。

配置在 `configs/default.toml`，固定建模约定在 `configs/assumptions.json`。主模型为单元中心圆柱有限体积和经典四阶段 RK4；一维官方格式输出始终来自一维。第四问内部使用随体坐标，填表时转换到**当前空间中的固定 r**。域外点留空，表面独立重构。烘干事件经局部重新积分，保存不超过 0.1 s 的未达标/严格达标区间；报告时间向上取到 0.0001 h 并重新积分验证，另加在整分钟行之后。

输出按问题划分，文件位置表示结果类型，验证状态统一写入 `results/status.json` 和各问 summary：

```text
results/
  tables/result1.xlsx … result4.xlsx
  q1/q1_curves.png, q1_1d_2d_compare.png, q1_max_error_section.png
     q1_compare.csv, q1_summary.json, q1_key_values.csv
  q2/（同 q1，以 q2 命名）
  q3/（同 q1，另有 q3_3d.png、q3_3d.gif）
  q4/（同 q1，另有 q4_3d.png、q4_3d.gif、q4_radius_history.csv）
  q3_q4_axial_section.gif
  q3_q4_radial_section.gif
  q3_q4_cutaway_cylinder.gif
  status.json
  overview.md     # 自动生成的简要数值结果、阶段状态和未解决警告
work/
  cache/          # 1D/2D 轨迹、共享 q23、事件场；exports/ 为全精度填表数组
  checkpoints/    # 按 case_id 保存续算检查点
  validation/     # 程序测试、解析基准、通量、时间和空间对照原始数据
  comparison/     # 逐时间、沿轴向比较及内部汇总
  plot_payload/   # 唯一绘图入口 plot_manifest.json、独立节点场/曲线/总览证据
  diagnostics/    # diagnostics.csv、失败明细、导出来源、耗时与图像清单
logs/
  run.log
  events.jsonl
```

四份 Excel 只使用一维结果，保存后逐单元回读校验；不会因验证状态而复制到不同目录。72 h 未烘干时，summary 中 `drying_time` 为 null，表中保留已计算时序，不添加烘干终点行。`status.json` 的 `time_convergence_passed`、`spatial_convergence_passed`、`two_dimensional_check_completed`、`drying_completed`、`official_output_generated` 分别记录对应状态；完成二维比较不等于空间精度已认证。summary 时间单位为秒。

内部 q23 仅求解一次，第 2 问展示 0–3 h，第 3 问展示到一维烘干终点。第 1 问为 0–1800 s，第 4 问到自身终点。`compare` 从已有场生成四问比较 CSV；compute.py 完成比较、导出和绘图数据打包；plot.py 只读取清单列出的 payload，重画 14 张 PNG。缺少清单或数据会列出具体路径并终止，不自动求解、不扫描求解缓存。最大误差截面按各问时间窗内最大含水率绝对差选时，标注温差峰值时刻；全长截面由实际二维半圆柱解在径向与轴向对称展开。

plot.py 生成五个 GIF：原有两张真实二维场的 3D 动画、一张 q3/q4 过轴截面、一张一维径向解映射的圆形截面，再追加真实二维场旋转展开的斜切圆柱。竖直圆柱在模型中部被与轴线成约 45° 的横向斜平面截断，显示下段外壁及椭圆斜截面。斜切平面方位角保持 35°，相机 yaw 从 −55° 改为 −145°（沿斜面朝外法线的水平方向），俯仰角保持 23°。显示下界由 −12.5 cm 裁至 −6.25 cm，裁去下段的 50%；可见点的物理坐标及三轴单位比例不变，模型全长仍为 25 cm。底部弧线代表显示裁剪边界。1080×960 画布采用接近 1:1 的四个子图，外轮廓 1.1 pt、斜切边界 1.4 pt，配浅色细描边；斜切面增加 0.6 pt 的真实场等值线，温度等值距固定为 0.5 ℃、含水率等值距固定为 0.1 kg/kg，Q3/Q4 及所有帧共用同一组等值级别，最多标注三个数值。均匀场不人为添加等值线。Q4 直径与椭圆边界一起真实收缩。斜切 GIF 按独立二维模型各自的烘干终点播放，保留前 6% 占 160/240 帧的慢放安排，整体为 0.5 倍速（普通帧 80 ms、末帧停留 2 s，总时长 21.12 s），标题注明“前 6% 慢放 · 0.5 倍速”；正式 Excel 的终点取自一维生产方案。综合 GIF 均为左上 Q3 温度、右上 Q4 温度、左下 Q3 含水率、右下 Q4 含水率。三张综合动画使用相同相对进度，各问显示实际物理时间，前 6% 过程放慢；温度和含水率分别固定为 28–53 ℃、0–2.55 kg/kg。第四问在固定坐标范围内显示真实半径收缩。动画逐帧编码并完整解码检查。`animate --case q23` 或 `--case q4` 只重画对应 3D GIF；综合动画用不带筛选的 `animate`。

计算失败只需重跑 compute.py，已完成子阶段可复用、未完成子阶段从检查点恢复。绘图失败只需重跑 plot.py，四份 Excel 和计算缓存保持原样。payload 格式版本与内容 hash 必须匹配；绘图代码样式修改不要求重新计算 PDE。同格式下 plot_version_hash 记录生成数据时的绘图版本，实际绘图版本另写 plot_status.json。需要更新代表时刻/帧计划时用 compute.py --payload-only。缓存和检查点已在 .gitignore 中排除。

空间方法：从旧均匀一维全程轨迹及二维前 1800 s pilot 提取 T/C 无量纲梯度包络，平滑/限制密度后冻结 monitor，通过累计监测量等分生成嵌套网格。q2/q3 共用 q23；第四问每阶段内 ξ 面坐标不变，少量阶段边界才切换拓扑。网格诊断及图位于 `work/validation/mesh_profiles/`。非均匀面通量使用实际距离串联阻力，对称面用任意控制体二阶矩重构；uniform 模式与冻结旧算子回归，另有独立 Robin 圆柱解析解测试。

一维 fixed 40→80→160 保留为历史对照（legacy / diagnostic only）。当前 stage_schedule 的正式空间状态使用下述三项阶段检查，判定时刻仅为题目要求的输出时刻及烘干终点；内部接受步与 RK4 子步误差仅作数值审计。阈值保持最大 ΔT≤0.01 K、ΔC≤0.01 kg/kg、烘干时间相对差≤0.2%，并检查正式误差随加密下降。全场 L∞、体积加权 L2 另存诊断。局部固定 400 验证早期窗口及 200→400 下降趋势，不宣称完整时间域的 400 收敛。数值差值不是物理误差上界。时间验证保留实际步序减半、原阈值及必要时再次减半；0.25 s 明确定义为 dt_max 上限；保留按各 RK 阶段稳定性估计进行二分保护的既定算法，实际步长不超过稳定上限。每阶段 min/mean/max 均写入 status.json 和 overview.md，短尾步计入统计。

二维主轨迹覆盖完整时段，时间减半仍按原方案覆盖前 1800 s。独立径向/轴向加密覆盖早期及当前一维/二维最大差代表时刻；长时终点采用最后一小时粗网格单元平均值的守恒投影，并在加密网格真实积分至终点附近，分别量化两方向敏感性。这是诊断窗口，继承了更早的粗网格误差，故保留 `2D_SPATIAL_VALIDATION_PARTIAL`，不宣称完整二维空间收敛。二维生产过程保持固定网格；一维可采用下述阶段网格。compute.py 及旧 export 命令更新正式状态时同步刷新 results/overview.md；plot.py 只重画图像，不用旧 payload 快照覆盖当前汇总。

本工程不引入题面以外的材料参数，不外推72 h之后的半径，不生成论文或报告。原始 PDF 的辅助预览脚本仅用于本机查阅，不是求解依赖。


阶段配置位于 configs/stage_schedule.json，configs/default.toml 的 stage_mesh.mode 支持 fixed / stage_schedule / early_refined_stage_schedule。默认 early_refined_stage_schedule：Q1 在 60、300、1200 s，Q23 在 300、1800、21600 s，Q4 在 600、3600、21600 s 执行 200→160→80→40。另对三组均实测后期保持 80 的 200→160→80 方案。正式候选早期使用 200；400 仅作同一早期窗口的局部核验，不全程使用。二维保持 40×125。每个固定拓扑子阶段拥有独立缓存、指纹和检查点；聚合轨迹在切换时采用新网格的状态，时间点不重复。

投影采用 xi²/eta 区间重叠的正权重平均，守恒同一时刻 T/C 的体积积分。max/L2 投影误差以“旧网格状态与新网格反投影状态之差”定义，量化损失的子网格变化。它不声称非线性物性下的总焓严格守恒。切换日志包含新旧网格、时刻、max/L2 和体积积分误差。

阶段附加误差沿用新严格阈值，分别比较固定 160 与两套 early refined schedule；默认方案失败则选择通过验证的 200→160→80，均失败时回退 fixed 160 候选。回投影损失的子网格变化只作内部数值审计，超阈值记日志，不否决阶段方案；非有限状态、非正含水率、越界温度或体积积分守恒失败仍中止计算。候选阶段另做实际步序减半检查。`fixed_grid_spatial_passed` 只保留旧 fixed 对照诊断；`stage_schedule_spatial_passed` 表示当前阶段生产方案通过 `early_reference_passed AND stage_schedule_accuracy_passed AND remesh_transfer_passed`。`spatial_convergence_passed` 只表示当前正式生产方案：阶段方案通过三项检查即可 PASS，旧 fixed FAIL 不再否决它。若实际回退到 fixed 生产，则使用该 fixed 证据。网格切换门槛保留求解器的非有限/非正/越界检查及体积积分相对误差 ≤1e-12；回投影 max/L2 幅值属于内部审计，超阈值仅记日志。时间收敛独立报告，不冒充空间判据。所有尝试、推荐方案及失败原因保存在 work/validation/*_stage_summary.json。

```text
fixed_grid_spatial_passed          = 旧 fixed 对照的诊断状态
stage_schedule_spatial_passed      = early_reference_passed AND stage_schedule_accuracy_passed AND remesh_transfer_passed
spatial_convergence_passed         = 当前正式生产方案的空间状态
```

采用阶段生产时，第三项等于第二项；旧 fixed FAIL 不参与该合取。三项阶段门槛缺失或未通过均不能标为 PASS。

当前正式来源统一记录在 results/status.json：Q1 为 200→160→80→40，Q2/Q3 为 200→160→80，Q4 为 200→160→80→40；Q1～Q4 正式空间均 PASS，旧 fixed 80→160 均 FAIL（legacy / diagnostic only，早期表面含水率分辨率不足）。Q1/Q2 使用固定输出时间窗；Q3/Q4 正式一维烘干时间分别为 207437.4 s / 184256.64 s（约 57.6215 h / 51.1824 h）。未采用的阶段尝试同样只作诊断。仅刷新六份汇总及 payload 中的证据快照可运行 `.\.venv\Scripts\python.exe scripts/refresh_summaries.py`；不会求解 PDE、重新打包数值场或改写 Excel。

plot_manifest.json 包含 schema/input/plot hash、每问正式来源与阶段信息、明确的 payload/cache/Excel 路径、代表时刻/最大误差时刻、动画实际时间数组、固定色标和输出名；payload_files 保存逐文件 hash 与大小。渲染器只消费重构后的物理节点场，不访问内部求解对象，也不导入求解模块。

本轮严格阈值统一为 ΔT≤0.01 K、ΔC≤0.01 kg/kg、烘干时间相对差≤0.2%（配置为 0.002）。内部误差审计位于 src/drying/audit.py：重放缓存实际接受的经典 RK4 步序，逐保存区间核对重放末状态与原缓存，遍历两条轨迹全部内部步端点；另一轨迹在相邻接受状态间作时间线性插值。它是离散内部时刻审计，不是连续时间误差上界。`all_internal_times_max_error` 与 `official_output_times_max_error` 分别保留；全场 L∞、体积 L2、时刻/位置及事件误差也保留。固定 40→80、80→160 是全时域比较，200→400 明确只覆盖早期。

真实表面 Robin 重构使用实际 R-r_center[-1]；仍保留既定的局部线性串联阻力公式，没有平滑或事后改写表面值。极早期初值与 Robin 边界不相容造成的离散表面误差由内部审计暴露，内部超阈值仅记日志，不参与正式 PASS/FAIL。正式空间收敛仅在题目实际要求的输出时刻及两条轨迹各自烘干终点判定，终点场值采用真实局部积分，不作时间插值；下降趋势也仅使用这些正式时刻的误差。

只重画斜砍 GIF：`.\.venv\Scripts\python.exe plot.py --gif cutaway --gif-only`。14 张 PNG、其余四个 GIF 和结果汇总原样保留。省略 `--gif-only` 时也更新 PNG；不加参数时从独立 payload 重画全部图。绘图入口均不导入或调用 PDE 求解器。最终 results 中不额外输出斜砍静态 PNG。
