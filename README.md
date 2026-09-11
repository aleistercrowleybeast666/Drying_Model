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

plot.py 生成五个 GIF：原有两张真实二维场的 3D 动画、一张 q3/q4 过轴截面、一张一维径向解映射的圆形截面，再追加真实二维场旋转展开的斜切圆柱。斜面穿过圆柱中部，其方向角和轻微轴向倾角可在 display 中修改。综合 GIF 均为左上 Q3 温度、右上 Q4 温度、左下 Q3 含水率、右下 Q4 含水率。三张综合动画使用相同相对进度，各问显示实际物理时间，前 6% 过程放慢；温度和含水率分别固定为 28–53 ℃、0–2.55 kg/kg。第四问在固定坐标范围内显示真实半径收缩。动画逐帧编码并完整解码检查。`animate --case q23` 或 `--case q4` 只重画对应 3D GIF；综合动画用不带筛选的 `animate`。

计算失败只需重跑 compute.py，已完成子阶段可复用、未完成子阶段从检查点恢复。绘图失败只需重跑 plot.py，四份 Excel 和计算缓存保持原样。payload 格式版本与内容 hash 必须匹配；绘图代码样式修改不要求重新计算 PDE。同格式下 plot_version_hash 记录生成数据时的绘图版本，实际绘图版本另写 plot_status.json。需要更新代表时刻/帧计划时用 compute.py --payload-only。缓存和检查点已在 .gitignore 中排除。

空间方法：从旧均匀一维全程轨迹及二维前 1800 s pilot 提取 T/C 无量纲梯度包络，平滑/限制密度后冻结 monitor，通过累计监测量等分生成嵌套网格。q2/q3 共用 q23；第四问每阶段内 ξ 面坐标不变，少量阶段边界才切换拓扑。网格诊断及图位于 `work/validation/mesh_profiles/`。非均匀面通量使用实际距离串联阻力，对称面用任意控制体二阶矩重构；uniform 模式与冻结旧算子回归，另有独立 Robin 圆柱解析解测试。

一维空间验证完成全过程 40→80→160，以官方物理半径（含真实表面）最大 ΔT≤0.01 K、ΔC≤0.002 kg/kg，以及烘干时间相对差≤0.1% 验收。全场 L∞、体积加权 L2 另存诊断。第二轮通过选 80；未通过选 160 候选并保持空间 FAIL，不自动继续到 320。数值差值不是物理误差上界。时间验证保留实际步序减半、原阈值及必要时再次减半；0.25 s 明确定义为 dt_max 上限；保留按各 RK 阶段稳定性估计进行二分保护的既定算法，实际步长不超过稳定上限。每阶段 min/mean/max 均写入 status.json 和 overview.md，短尾步计入统计。

二维主轨迹覆盖完整时段，时间减半仍按原方案覆盖前 1800 s。独立径向/轴向加密覆盖早期及当前一维/二维最大差代表时刻；长时终点采用最后一小时粗网格单元平均值的守恒投影，并在加密网格真实积分至终点附近，分别量化两方向敏感性。这是诊断窗口，继承了更早的粗网格误差，故保留 `2D_SPATIAL_VALIDATION_PARTIAL`，不宣称完整二维空间收敛。二维生产过程保持固定网格；一维可采用下述阶段网格。已有图和 GIF 的布局/帧计划不变，只更新真实非均匀坐标和对应场数据。compute.py、plot.py 及旧 export 命令自动刷新 results/overview.md；plot.py 使用打包的计算证据。

本工程不引入题面以外的材料参数，不外推72 h之后的半径，不生成论文或报告。原始 PDF 的辅助预览脚本仅用于本机查阅，不是求解依赖。


阶段配置位于 configs/stage_schedule.json，configs/default.toml 的 stage_mesh.mode 支持 fixed / stage_schedule。默认一维 Q1 在 300、1200 s，Q23 在 1800、21600 s，Q4 在 3600、21600 s 执行 160→80→40。二维保持 40×125。每个固定拓扑子阶段拥有独立缓存、指纹和检查点；聚合轨迹在切换时采用新网格的状态，时间点不重复。

投影采用 xi²/eta 区间重叠的正权重平均，守恒同一时刻 T/C 的体积积分。max/L2 投影误差以“旧网格状态与新网格反投影状态之差”定义，量化损失的子网格变化。它不声称非线性物性下的总焓严格守恒。切换日志包含新旧网格、时刻、max/L2 和体积积分误差。

阶段附加误差沿用空间阈值，比较固定 160 与默认 schedule；失败则检查 160→80，仍失败回退 fixed 160。候选阶段另做实际步序减半检查。stage_schedule_passed 只表示相对固定 160 的附加误差合格，不能消除既有空间 FAIL。所有尝试、推荐方案及失败原因保存在 work/validation/*_stage_summary.json。

plot_manifest.json 包含 schema/input/plot hash、每问正式来源与阶段信息、明确的 payload/cache/Excel 路径、代表时刻/最大误差时刻、动画实际时间数组、固定色标和输出名；payload_files 保存逐文件 hash 与大小。渲染器只消费重构后的物理节点场，不访问内部求解对象，也不导入求解模块。
