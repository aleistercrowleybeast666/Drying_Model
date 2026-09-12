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
.\.venv\Scripts\python.exe -m pytest -q -o cache_dir=work/studies/pytest_cache --basetemp=work/studies/pytest_tmp
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
  q3/（同 q1，另有 q3_3d.png）
  q4/（同 q1，另有 q4_3d.png、q4_radius_history.csv）
  animations/    # 原有 5 个 GIF，迁移时逐字节验证，保留画面与播放设置
    q3_3d.gif, q4_3d.gif
    q3_q4_axial_section.gif, q3_q4_radial_section.gif, q3_q4_cutaway_cylinder.gif
  studies/       # 独立扩展，绝不替换上面的正式四表
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

新增扩展入口（一次只运行一个重计算进程）：

```powershell
# 首次在新环境安装扩展水物性依赖；启动器不会自动安装。
.\.venv\Scripts\python.exe -m pip install -r requirements-studies.txt
.\.venv\Scripts\python.exe compute_studies.py --group all --dry-run
.\.venv\Scripts\python.exe compute_studies.py --group all --resume
# verify / postprocess / geometry / environment / thermal 可单独选择；可附 --case q23 --mode M10。
.\.venv\Scripts\python.exe compute_studies.py --group all --resume --payload-only
.\.venv\Scripts\python.exe plot_studies.py
.\.venv\Scripts\python.exe compute_studies.py --output-status-only
.\.venv\Scripts\python.exe plot_studies.py --fig thermal_modes
.\.venv\Scripts\python.exe plot_studies.py --gif thermal_temperature --gif-only
.\.venv\Scripts\python.exe app.py
```

`work/baseline_snapshot/baseline_manifest.json` 冻结当前真实 M00 的输入、配置、轨迹、事件、四表和原有图像。
双击 `studies_compute.bat` 只显示任务、预计缓存命中和缺失输入；实际计算需传入如 `--group all --resume`。`open_gui.bat` 只打开控制界面。两者不联网安装依赖、不自行发起全量重算。
完成且指纹匹配的轨迹始终复用；未完成轨迹需 `--resume` 续算。若只改变生产/参考用途且所有生效参数完全一致，可逐数组核验后复用，记录原轨迹和复用耗时，不把历史求解耗时算成本轮重算。
轨迹 `wall_s` 是实际执行耗时（包含该进程首次 JIT/加载）。`scripts/benchmark_study_startup.py` 另在新进程以零物理步测量内核编译/加载，写 `work/studies/diagnostics/kernel_startup.json`；不倒推或回填历史耗时，不作为精度收益分析。
完整阶段参考从原始初态开始，使用同一个冻结 monitor、同一组切换时刻，各阶段 Nr 加倍。
`full_schedule_reference_passed` 是新增独立证据，不替换旧“早期参考 AND 阶段附加误差 AND 换网格”正式认证。
旧 fixed-grid FAIL 保留 `legacy / diagnostic only`；不影响已经通过的正式阶段方案。
`results/studies/overview.md`、`study_index.json` 和 `validation_summary.json` 汇总扩展证据；根目录正式 overview/status 保持冻结。

补充 M10（仅潜热）、M01（仅显式携热）、M11（两者均计）复用原 FV/RK4，分别进行自身半步重放、完整阶段空间参考和真实事件定位。
`configs/studies_numerics.json` 仅记录补充热模式的保守空间倍数；每条生产方案都对应再加倍的完整参考及同网格半步验证。旧未通过尝试保留诊断，不覆盖 M00 配置或放宽阈值。
新增水物性采用固定版本 IAPWS-IF97 饱和路径，kJ/kg 转 J/kg，有效域 273.16–373.15 K，不对冰区外推。
干料质量换算、带符号凝结通量和有效温度方程假设详见 `work/studies/diagnostics/thermal_assumptions.md`。
新结果是模型比较，不是实验验证；二维精度仍为 PARTIAL；证据层不合并为一个物理误差。
扩散时钟 ΘV 仅作状态与几何尺度诊断，不把非线性 PDE 精确变成常系数方程，也不要求曲线重合。B8/B10 控制组及匹配网格的一维对照未单独增加完整加密求解；主方案参考只为这些模型差提供数值分辨率背景，不冒充控制组独立精度认证。

正式扩展输出为两份汇总工作簿、M10/M01/M11 各一份 `thermal/<模式>/supplement.xlsx`、九张 `figures/*.png` 和两张 `animations/thermal_*.gif`。
每份补充工作簿包含 Q1–Q4 的温度与含水率；Q3/Q4 温度表明确标为 `_extension`，沿用对应问题的坐标、分钟采样和本模式真实终点，不改写原题官方表。
汇总表抽取真实保存时刻；补充表保持 Q1/Q2 每秒、Q3/Q4 每分钟及各自真实事件。72 h 未达标时事件为空。
汇总时间序列保留真实事件：在各热模式的事件时刻对其他模式作真实短程积分，四模式按共同物理时刻导出中心/表面温度、最大/平均含水率与达标状态。
阶段识别只影响诊断，配置在 `configs/studies_analysis.json`：围绕实际速率峰值，分别取峰前区间最初 10% 和峰后区间最后 10% 的速率中位数，两侧各有至少三个样本且峰值相对两端的差均超过峰值的 15% 才标记“慢—快—慢”。窗口按两侧各自的时长定义，避免长尾掩盖短暂升速段；分别判断 Cmax/Cbar，不平滑正式状态。
绘后运行 `compute_studies.py --output-status-only`，由计算侧按当前 payload 和渲染回执的 hash 核对实际产物并刷新扩展 overview；不重新求解、导出工作簿或改变数值清单。
新增动画是 1D 径向场的圆盘映射：两行 Q3/Q4、四列 M00/M10/M01/M11，八图相同物理时间，前 6% 慢放，Q4 半径真实变化。
绘图只读取已密封的 `work/studies/plot_payload/study_manifest.json` 与所列 NPZ；缺数据时列出路径和计算命令，不隐式求解。
渲染样式 hash 与数值缓存指纹分开，渲染失败只写绘图诊断。

GUI 只调用 CLI；参数与来源只读，实验组/轨迹/热模式选择实际进入命令。扩展“停止”写 `work/studies/STOP`，在下一保存点退出；恢复前移除标记。
关闭正在运行的窗口会等待子进程安全结束。主任务使用 `work/studies/BASELINE_STOP`，在当前完整计算阶段保存缓存后停止；扩展任务在下一输出保存点停止。
命令行恢复前删除相应停止标记；GUI 的计算/恢复按钮会清除本任务标记。停止不强行终止进程，不改正式数值内核。
桌面界面采用 PySide6；安装 `requirements.txt` 后可运行 `python app.py`。若图形环境或 PySide6 不可用，上述 CLI 仍可独立使用。

四份 Excel 只使用一维结果，保存后逐单元回读校验；不会因验证状态而复制到不同目录。72 h 未烘干时，summary 中 `drying_time` 为 null，表中保留已计算时序，不添加烘干终点行。`status.json` 的 `time_convergence_passed`、`spatial_convergence_passed`、`two_dimensional_check_completed`、`drying_completed`、`official_output_generated` 分别记录对应状态；完成二维比较不等于空间精度已认证。summary 时间单位为秒。

内部 q23 仅求解一次，第 2 问展示 0–3 h，第 3 问展示到一维烘干终点。第 1 问为 0–1800 s，第 4 问到自身终点。`compare` 从已有场生成四问比较 CSV；compute.py 完成比较、导出和绘图数据打包；plot.py 只读取清单列出的 payload，重画 14 张 PNG。缺少清单或数据会列出具体路径并终止，不自动求解、不扫描求解缓存。最大误差截面按各问时间窗内最大含水率绝对差选时，标注温差峰值时刻；全长截面由实际二维半圆柱解在径向与轴向对称展开。

plot.py 生成五个 GIF：原有两张真实二维场的 3D 动画、一张 q3/q4 过轴截面、一张一维径向解映射的圆形截面，再追加真实二维场旋转展开的斜切圆柱。竖直圆柱在模型中部被与轴线成约 45° 的横向斜平面截断，显示下段外壁及椭圆斜截面。斜切平面方位角保持 35°，相机 yaw 从 −55° 改为 −145°（沿斜面朝外法线的水平方向），俯仰角保持 23°。显示下界由 −12.5 cm 裁至 −6.25 cm，裁去下段的 50%；可见点的物理坐标及三轴单位比例不变，模型全长仍为 25 cm。底部弧线代表显示裁剪边界。1080×960 画布采用接近 1:1 的四个子图，外轮廓 1.1 pt、斜切边界 1.4 pt，配浅色细描边；斜切面增加 0.6 pt 的真实场等值线，温度等值距固定为 0.5 ℃、含水率等值距固定为 0.1 kg/kg，Q3/Q4 及所有帧共用同一组等值级别，最多标注三个数值。均匀场不人为添加等值线。Q4 直径与椭圆边界一起真实收缩。斜切 GIF 按独立二维模型各自的烘干终点播放，保留前 6% 占 160/240 帧的慢放安排，整体为 0.5 倍速（普通帧 80 ms、末帧停留 2 s，总时长 21.12 s），标题注明“前 6% 慢放 · 0.5 倍速”；正式 Excel 的终点取自一维生产方案。综合 GIF 均为左上 Q3 温度、右上 Q4 温度、左下 Q3 含水率、右下 Q4 含水率。三张综合动画使用相同相对进度，各问显示实际物理时间，前 6% 过程放慢；温度和含水率分别固定为 28–53 ℃、0–2.55 kg/kg。第四问在固定坐标范围内显示真实半径收缩。动画逐帧编码并完整解码检查。`animate --case q23` 或 `--case q4` 只重画对应 3D GIF；综合动画用不带筛选的 `animate`。

计算失败只需重跑 compute.py，已完成子阶段可复用、未完成子阶段从检查点恢复。绘图失败只需重跑 plot.py，四份 Excel 和计算缓存保持原样。payload 格式版本与内容 hash 必须匹配；绘图代码样式修改不要求重新计算 PDE。同格式下 plot_version_hash 记录生成数据时的绘图版本，实际绘图版本另写 plot_status.json。需要更新代表时刻/帧计划时用 compute.py --payload-only。缓存和检查点已在 .gitignore 中排除。

空间方法：从旧均匀一维全程轨迹及二维前 1800 s pilot 提取 T/C 无量纲梯度包络，平滑/限制密度后冻结 monitor，通过累计监测量等分生成嵌套网格。q2/q3 共用 q23；第四问每阶段内 ξ 面坐标不变，少量阶段边界才切换拓扑。网格诊断及图位于 `work/validation/mesh_profiles/`。非均匀面通量使用实际距离串联阻力，对称面用任意控制体二阶矩重构；uniform 模式与冻结旧算子回归，另有独立 Robin 圆柱解析解测试。

一维 fixed 40→80→160 保留为历史对照（legacy / diagnostic only）。当前 stage_schedule 的正式空间状态使用下述三项阶段检查，判定时刻仅为题目要求的输出时刻及烘干终点；内部接受步与 RK4 子步误差仅作数值审计。阈值保持最大 ΔT≤0.01 K、ΔC≤0.01 kg/kg、烘干时间相对差≤0.2%，并检查正式误差随加密下降。全场 L∞、体积加权 L2 另存诊断。局部固定 400 验证早期窗口及 200→400 下降趋势，不宣称完整时间域的 400 收敛。数值差值不是物理误差上界。时间验证保留实际步序减半、原阈值及必要时再次减半；0.25 s 明确定义为 dt_max 上限；保留按各 RK 阶段稳定性估计进行二分保护的既定算法，实际步长不超过稳定上限。每阶段 min/mean/max 均写入 status.json 和 overview.md，短尾步计入统计。

二维主轨迹覆盖完整时段，时间减半仍按原方案覆盖前 1800 s。独立径向/轴向加密覆盖早期及当前一维/二维最大差代表时刻；长时终点采用最后一小时粗网格单元平均值的守恒投影，并在加密网格真实积分至终点附近，分别量化两方向敏感性。这是诊断窗口，继承了更早的粗网格误差，故保留 `2D_SPATIAL_VALIDATION_PARTIAL`，不宣称完整二维空间收敛。二维生产过程保持固定网格；一维可采用下述阶段网格。compute.py 及旧 export 命令更新正式状态时同步刷新 results/overview.md；plot.py 只重画图像，不用旧 payload 快照覆盖当前汇总。

正式 M00 不引入题面以外的材料参数；M10/M01/M11 仅使用已声明的补充水物性。不外推72 h之后的半径，不生成论文或报告。原始 PDF 的辅助预览脚本仅用于本机查阅，不是求解依赖。


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

## 最终技术补全：交叉对照与论文事实

新增 `geometry_cross_p3_shrink` 使用完整附录 3 物性及原附件 R(t)，通过既有随体径向 FV/RK4 内核求解。其独立生产方案为 200→160→80，完整参考为 400→320→160，半步轨迹重放本组生产的实际接受步长。每条轨迹保留至 72 h，真实烘干事件另存；不继承 Q3/Q4 的 PASS。空间采用原 0.01 K、0.01 kg/kg、事件相对差 0.2% 判据；时间验证继续沿用更严格的 0.001 K、1e-5 kg/kg、事件差 1 s。原 M00 和各热模式定义、官方来源、阈值均保持冻结。

```powershell
.\.venv\Scripts\python.exe compute_studies.py --group geometry_cross --resume --solve-only
.\.venv\Scripts\python.exe compute_studies.py --group refine2d --resume
.\.venv\Scripts\python.exe compute_studies.py --group geometry_cross --resume --payload-only
.\.venv\Scripts\python.exe plot_studies.py --technical-only
.\.venv\Scripts\python.exe compute_studies.py --output-status-only
```

`Geometry_Property_Cross` 表与 05 图覆盖 P3/P4 × fixed/shrink 四组。`Cmean` 为 FV 体积加权平均；达标体积分数按径向分段线性重构的严格 `C<0.15` 区域积分，等阈值的平台不计入达标体积。交互项按 P4收缩−P4固定−P3收缩＋P3固定计算；没有事件的组保持 `drying_time=null`，不计算缺失时长的交互。P4 fixed 仍未独立加密，因此交互是结构诊断。

`Kinetics` 追加体积平均温度、含水率及三个变化率，`Kinetics_Summary` 记录 Q4 峰值区间、时差和 t50。体积权重使用当时实际 R(t)，不把边界重构节点当成等体积节点。差分只选真实保存的规则时刻，按网格阶段作三点中心差分/二阶单边端点差分；额外事件近重复时刻不参与差分。Q4 用实际 60 s 保存间隔，不虚构更密的 PDE 状态。半径使用附件的分段斜率，最大平台保留完整区间。原始 PDE 状态不平滑。t50 为相对初态到 Q4 正式终点总响应的最早线性插值交点；正时差表示目标晚于来源，负值表示提前，不称相位角。

可选 `refine2d` 从原始初态对 Q3/Q4 各测量 60×188 前 60 s 的实际成本，扣除单独记录的编译/加载耗时。默认若线性估计全 72 h 超过每组 1 h 墙钟预算则停止增强并记录 `PARTIAL_2D`，以免阻塞主流程；该估计不保证后期耗时。显式 `--refine-force-full` 可绕过成本门槛。完整路径仍使用同一冻结连续 monitor 和稳定性控制，并比较原 40×125、代表时刻、真实事件、控制区域及端面效应；仅一轮加密最多称 `2D_FULL_TRAJECTORY_REFINED`，不宣称网格独立性。不会自动使用更大二维网格。

本轮图表只替换 03/05，两份汇总表只新增所需工作表/列。其他七张静态图、全部七个 GIF、三份热模式补充表和四份官方 Excel 均检查保留。`--technical-only` 仅读密封好的技术 payload；`scripts/check_study_render.py --technical-only` 禁止数值模块导入并核对全部数据哈希。

`results/paper_facts.json` 与精简的 `paper_facts.md` 由已有数据自动导出，是后续论文直接引用数字的统一来源。JSON 保存未舍入值、source case id、源文件、输入/物理哈希、生成时间、二维状态和适用范围。正式来源或终点值冲突会阻止事实文件发布；未提供论文正文时只报告未执行初稿对照，不假称检查过论文。
### 二维辅助验收

`python validate_auxiliary_2d.py` 只读已有缓存，统一刷新六份状态/事实摘要，不积分 PDE、不导出 Excel、不画图。独立配置见 `configs/auxiliary_2d_validation.json`，用途为 `auxiliary_end_effect_and_model_reduction_validation`。正式一维阈值和生产结果不变。

辅助 PASS 要求已有时间验证 PASS、径向及轴向覆盖 Q1 0–1800 s / Q23 0–5086 s / Q4 0–10320 s、适用终点相对差不超过原 0.2%、端面误差分布和主体变化趋势一致、终点控制区域稳定、缓存完整且有限。Q23 的 5085–5086 s 使用已有同网格真实续算。定性检查使用原端面/中部区域和体积权重，在明确列出的共同时刻比较缓存单元场；不另设局部点值阈值。

`two_dimensional_auxiliary_validation_passed` 与 `two_dimensional_grid_independence_certified` 分开：当前辅助 PASS，网格独立性仍为 `PARTIAL_2D` / 未认证。Q23/Q4 时间验证仅覆盖 0–1800 s；末期终点细化继承早期粗网格误差。局部 Linf 仅诊断、不否决辅助验收；原严格 FAIL、完整误差、来源哈希和定性样本保存在 `work/validation/auxiliary_2d/summary.json`，旧 `work/validation/summary.json` 原样保留。

冻结保护仍逐文件检查；仅 `status.json` / `overview.md` 允许加入可从上述审计重现的独立摘要。备份旧字节必须匹配原冻结哈希，任何正式字段或正文数值改变仍报错，不重新冻结基线。

### 水质量守恒审计

`python compute_studies.py --group mass_balance --resume` 独立重放 M00/M10/M01/M11 的 Q1、Q23、Q4 全部实际接受步；`--payload-only` 仅复核审计记录并刷新摘要。生产状态、输入、模型、原收敛判据和图表不变。

`solver_mass_balance` 直接捕获原有限体积算子的有符号边界含水通量，按同一步 RK4 的 1:2:2:1 权重积分，拒绝步不计入，累计量采用补偿求和。水质量使用 `b0=rho(C0)/(1+C0)`；Q4 使用 `bd=b0*(R0/R(t))^2` 与实际圆柱体积，轴向半域还原为完整 0.25 m 圆柱。每个接受步检查 `Mw+Mout-Mw(0)`，换网格前后单独记录质量跳变；连续重放不在输出检查点重置状态或累计量。重放状态和接受步分区必须与原缓存一致。`export_mass_balance` 仅诊断，不决定守恒 PASS。

全轨迹记录、最大残差对应的时间/阶段/四个边界流量、换网格记录及阈值依据保存在 `work/validation/mass_balance/`；摘要进入 studies 验证页和 `paper_facts`。全部原始残差测量完成后，以接受步数和浮点通量累计的精度尺度冻结 `policy.json`，不以残差峰值拟合阈值，续跑不再改变该阈值。运行 `python scripts/check_mass_balance.py` 可复核源缓存、29,920,769 个接受步记录、摘要一致性和文件保护。本审计不新增图表或 GIF。
