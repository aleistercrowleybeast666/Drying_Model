# release_v2 计算链与验收记录

已构建独立双 EXE 包。默认原题四表冷启动 **217.791 s（3.630 min）**，退出码 0；再次复用缓存 **9.112 s**。这不是全验证或全拓展耗时。测试期间未停止任何旧任务，CPU 可能存在竞争。167 项回归测试通过。

以下逐项对应 prompt 的 25 项汇报。未实测项目不宣称 PASS。

1. **Table-only DAG**：父进程准备输入、冻结网格并预热 → A.q23 与 A.q4 并行 → 空闲槽执行 A.q1 → 每个 case 独立导出、Excel 回读和参考核对 → 父进程合并。Q2/Q3 仅用一条共享轨迹。实际冷启动只有这三个任务。

2. **冻结 mesh**：configs/frozen_mesh/manifest.json，加 Q1/Q23/Q4 的 radial/axial monitor 共六个 NPZ。验证输入、mesh/numerics 配置、stage 配置、八个数值核心、monitor 文件 SHA256、连续 monitor 内容及常用 faces 哈希；运行时生成所需 faces 并校验。缺失或损坏报 FROZEN_MESH_CONFIGURATION_MISSING_OR_MISMATCH。Q23 保留已接受的 **200→160→80**，Q1/Q4 为 200→160→80→40，切换时刻不变。

3. **Runtime pilot**：judge 所有路径使用冻结资源，无 pilot 回退；实际默认日志无 pilot。开发者 scripts/regenerate_frozen_mesh.py 在隔离目录生成、比较，只有显式 --accept 才更新冻结配置。

4. **Early stop**：沿用原 Event_Locate、Rk4_Advance，真实积分至原精度的 report_s。最终输出、检查点保存真实报告状态；接受步分区裁去分钟输出过冲，换成事件重积分的实际接受步。Q23 至少覆盖 10800 s；拓展仍用独立完整 72 h 身份。新 A 与旧完整 M00 前缀逐项核对，Q1/Q23/Q4 分别比较 1801/14079/3072 个保存状态，最大差 **0**，事件字典完全一致。此对照读取旧冻结完整缓存，未重新求解旧完整轨迹。

5. **Validation_Run**：A 完全绕开。导出显式指定 production case_id；仅表格复算时数值验证标为 NOT_RERUN_IN_TABLE_ONLY_MODE，表格参考 PASS 不冒充收敛认证。

6. **二维**：A 没有二维或热模式依赖。冷启动日志没有 2D、M10/M01/M11。仅生成四表、必要 CSV/JSON、overview 和耗时记录，没有 PNG/GIF 或拓展输出。

7. **移出 judge 的 legacy**：fixed40/80/160 筛选/对比、旧 uniform、early trend、独立 early reference、两套阶段方案筛选、fixed-grid dt/2。旧代码和历史结果保留为 developer / legacy / diagnostic only，不参与当前生产认证。

8. **正式 B 链路**：复用 A → 每 case 完整 x2 阶段参考 → A 实际接受分区减半重放 → 原 remesh 判据 → 串行发布。二维、12 个守恒任务和一致性检查分别调度。Q1/Q23/Q4 新一维验证已经实跑 PASS，数据见下表。

9. **Full x2 实现**：复用原 Trajectory_GetSpec(kind='full_reference', factor=2)、Trajectory_Solve、缓存封存和 Analysis_Compare。参考从初态贯穿全部阶段，Nr×2，保持完整参考时域；正式误差在题目要求时刻和真实烘干终点判定。

10. **时间验证**：只针对当前正式 stage production 的真实接受分区 dt/2，保留原温度、含水率、事件和 remesh 阈值，无 fixed-grid 时间筛选。

11. **二维结论**：保持原方向加密、端点敏感性和 auxiliary 判据；临界窗覆盖不足时补足同方向参考。原冻结二维场配合新 A、新比较数据运行辅助评估和 8 张验证图，PASS；绘图禁用求解器探针通过。仍为 **PARTIAL_2D / 未认证完整二维网格独立性**。完整二维求解链本轮没有在 v2 空缓存下全部实跑。

12. **Mass balance**：保留 solver 真实边界通量、实际接受 RK4 步和冻结阈值；四模式×三个 case 各自独立。实际新增 M00 三条 A 全接受轨迹审计均 PASS，最大绝对残差 **9.797718e-15 kg**，最大相对残差 **4.387806e-14**；Q4 986857 个接受步、三次 remesh 最大质量跳变 **0 kg**，未检出非物理来源或损失。Q23 remesh 最大跳变 2.775558e-17 kg。新热 JIT 的短步质量插桩一致性已测，但 **12 例完整审计未在新路由下全跑**。

13. **输出归属**：A：results/tables/result1.xlsx～result4.xlsx、必要 CSV/summary、overview/status。B：work/validation/、8 张 compare/max-section PNG、09_verification_evidence.png；01_end_effect_extent.png 依赖 D matched 数据，但归 B。C：4 张曲线、2 张 3D PNG、单独选择的 5 个原题 GIF。D：study_summary.xlsx、study_timeseries.xlsx、三个热模式 supplement.xlsx、技术汇总、其余 7 张研究 PNG、2 个热 GIF、paper_facts。完整分类在 configs/output_groups.json。

14. **GUI 依赖**：四组独立，默认 A。B 补必要 A，守恒缺热 production 时明确列出；D 补 baseline、二维和必要验证。C 缺数据时 GUI 显示所需 A/B 并确认；CLI 纯绘图报 PLOT_INPUT_MISSING，不自动求解。白底、可展开日志、单调进度、立即停止/关闭 GUI 结束本次进程树保留，旧 release 不在新 GUI 所有权范围内。

15. **Scheduler**：有界 subprocess DAG。A/B 按 case 私有工作区，D 按 experiment 独立目录；production→reference/half 保持依赖。索引、全局 summary、workbook 和发布由 parent/exclusive 节点串行写入。任务 JSON 使用相对发布根的路径。记录每任务 PID、起止、wall、缓存复用；组 wall 取活跃区间并集，另报累计 worker 秒，不混同总耗时。

16. **Heavy workers**：默认 **2**，允许 --workers 1 或 3。

17. **JIT**：父进程先预热一次 M00 必要签名；热任务前独占预热各 case/mode 不同常数的内核。进程共享运行目录 NUMBA_CACHE_DIR，不发布 CPU 缓存。原 thermal 数学函数体和 RK4 AST 原样生成可缓存模块，只绑定到 judge。实测一次冷编译 6.239 s、全新进程复用 0.539 s，短步所有 RK4 输出逐位一致。新热 JIT 的全部完整模式轨迹尚未实跑。

18. **分组 wall time**：A 外部冷计时 217.791 s，准备/JIT 25.284 s，A worker 活跃并集 188.240 s。B 一维三 case 调用总计 **1642.216 s（27.370 min）**，验证活跃并集 1612.689 s，包含 A 复用及 Q1 已完成参考缓存，不能当完整 B 冷启动。M00 守恒 Q1/Q23/Q4 分别 7.344/96.453/35.203 s。C 六张静态图缓存绘制实测 54.124 s（见 work/release_v2/static_acceptance.json）；B 辅助评估+8 图缓存复核 18.963 s。完整 B、D、GIF 和 --all 的端到端 wall time **未测试**。

19. **A 全冷实测**：实际 EXE 在无 work/results、PATH 无外部 Python、重定向 stdin 条件下运行，包含准备/JIT/Excel/回读，外部计时 **3.630 min**，退出码 0。源码另测 207.871 s。最新外部代码更新后的实际 EXE 缓存复用 9.112 s，四 Excel SHA256 未变。

20. **旧 17-step 对比**：没有同条件已完成的旧 17-step 总耗时，不声称具体加速倍数。确认默认降为三个必要 production，移除验证/二维/拓展/pilot，达到并优于本机 4–7 min 的目标范围。

21. **Q3/Q4**：完全保持 **57.6215 h / 51.1824 h**，报告时刻 207437.4 s / 184256.64 s。完整精度数组、半径、表面值、事件逐项一致。

22. **Excel readback**：四份 PASS，原版式、有效单元格和域外空白不变。完整精度 time/T/C/R/surface 数组对冻结参考最大差均 0。三个 TABLE_RECOMPUTE_REFERENCE_MATCH: PASS 覆盖四份 Excel。

23. **数值核心**：materials/boundaries/operators/rk4/sampling/inputs/events/geometry 八文件及 cases.py、stages.py、thermal.py、trajectory.py 保持字节不变。没有改物性、FV、边界、RK4、dt_max=0.25、阶段方案和阈值；没有 fastmath、float32、内核 parallel、GPU 或减网格。新增 table solver 只拆出调度，调用同一数值核心。

24. **发布路径与 SHA256**：release_v2/A题_药材烘干模型/。

    | EXE | SHA256 |
    |---|---|
    | 药材烘干模型_GUI.exe | a982d22872d8872e35a0661628524ec9bde119586d4458f2434f1c9375862866 |
    | 药材烘干模型_原题表格复算.exe | af9ad6633b2e4b0e35866e776830331204d12815ea2d2ddccf67d9256e6abe44 |

    双 EXE、双 Python 入口、同模板 README/TXT、requirements、安装 BAT、dependencies 和 manifest 齐全。本轮验收 work/results/logs 移到 work/release_v2/ 留证，不发布历史缓存。首次运行自行建目录，删除 results 也能生成。

25. **旧 release**：本轮未修改、移动、覆盖、清理 release/A题_药材烘干模型/，未停止其进程。构建对旧目标强制拒绝。原工程冻结正式结果、输入、既有配置和核心另按原 publication manifest 核验。

## 新一维验收实测

| Case | 空间 max ΔT/K | 空间 max ΔC | 时间 max ΔT/K | 时间 max ΔC | 正式状态 |
|---|---:|---:|---:|---:|---|
| Q1 | 0.000695156861 | 0.002117508331 | 3.868365e-9 | 6.354917e-13 | PASS |
| Q23（Q2/Q3 共用） | 0.000430596724 | 0.002025627860 | 5.967422e-10 | 5.172307e-12 | PASS |
| Q4 | 0.001276140920 | 0.004620363231 | 1.281819e-10 | 1.076472e-12 | PASS |

保留 DT_LIMITED_BY_STABILITY 正常自适应日志、PARTIAL_2D 及端面影响明显等科学限制，没有通过改阈值消除这些信息。已修复重定向 stdin 误等待回车、验证图缺少终点位置元数据两个接线问题，真实 EXE/缓存绘图复测通过。

证据在 work/release_v2/：cold_benchmark、warm_acceptance、full_prefix_acceptance、table_mass_acceptance、auxiliary_publisher_acceptance、static_acceptance 和测试日志。这些是开发机记录，不表示评委电脑已经重跑，也不替代未测的全量 B/D/--all 验收。
