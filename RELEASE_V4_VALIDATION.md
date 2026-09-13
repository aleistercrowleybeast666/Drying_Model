# V4 验收记录

基线 main `23c5aaf`。本轮修改调度、进程、私有工作区及范围表达，没有修改数值核心。V2 禁止修改或停止。V3 发布目录经进程核验后按用户授权删除，覆盖附件中的 V3 保留要求。没有启动完整 Developer Full Audit 长跑。

## A. Crash fix

`Judge_PreparePrivate(runtime, name, source_case=...)` 显式传递 q1/q23/q4，force 时间戳不参与 case 解析。回归覆盖 ref/q1/q23/q4、two、dev、full 和 force developer 计划。重复二维运行另外修复共享硬链接被 copy2 写穿的问题：只链接完成的输入文件，写入继续使用原子替换。

## B. 完整审计范围

Developer：102 个 logical tasks，87 个 logical PDE/replay 请求，4 个 exact aliases，99 个实际调度任务，其中 83 个 PDE/replay 单元。保留 thermal 18 条、mass 12 条、完整二维辅助、环境 tail、cross、fixed radius、matched、静态图、两类 GIF、legacy diagnostics、consistency 与最终 publish。

计数是调度单元，不是 RK4 调用数；正式一维验证和 legacy diagnostics 内仍有原有多次计算。paper-all 为 77 个实际任务 / 62 个 PDE/replay 单元，不含 thermal 18 条、legacy 3 条及原题 GIF；未选 supplemental 显示 NOT_SELECTED_SUPPLEMENTAL，不能冒充 PASS。force-reference 单独勾选。

## C. 并行架构

- auto CPU tokens = min(max(1, physical cores−1), 6)，本机 6 物理核为 5；显式支持 1～6。
- 内存预算为初始 available 的 72%，实际启动还须保留至少 2 GiB；同身份历史 RSS 加 30% 余量，最少按 512 MiB；原题已有匹配实测最大约 231 MiB，未知 1D 1 GiB、2D 2 GiB。观察到更大 RSS 时提高占用。
- 2D 子 DAG：base → time-half / seed；seed → radial / axial / 两个 endpoint；最后 assess。Q1 无 endpoint。仍调用原函数和原窗口。
- baseline、validation、study index、render 使用逻辑写锁；独立 PDE 不因短发布全部排空。
- bottom-level 关键路径优先；同 runtime 一维实验及守恒使用 persistent worker，二维与私有参考保持 one-shot。
- OMP/MKL/OPENBLAS/NUMEXPR/NUMBA 线程均为 1，worker below-normal。每任务 finally 恢复 observer/日志/环境，独立 receipt，不传 scientific result 对象。
- receipt 包含启动、import/JIT、solve、postprocess、wall、CPU、RSS、缓存。首次非零积分内编译仍计入 solve；RSS、空闲原因及启动节省为采样/估计，不虚构精度。

## D. 精确去重

`D.M00.q1/q23/q4.full_reference → B.reference.q1/q23/q4`；新增 `D.full.q1 → A.q1`。完整 Q1 实测：1,801 个保存状态、39,720 个接受步逐元素完全一致，最大状态差 0。状态数据 SHA256：`9bb3828498efd0e0f0ad485375e01a71ae47c9ebd443285ee526d13ac93658bb`。运行仍检查完整时域、冻结 schedule、dt、配置及正式参考。

Q23/Q4 四表真实终点与完整 72 h 不同；matched 网格不同；加密与半步分区不同；cross 物性/几何不同，均不合并。有效 numerical spec 不含纯显示 kind；未知规格保持独立。

## E. 有界实测

原始记录在 `work/release_v4/*.json`。测试期间 V2 仍可能占用资源。全部采用完整 Q1 1800 s、冻结网格、原 factor/dt；不是截短 Q23 的结果，更不是完整 developer 总耗时。

| 6 个 thermal Q1 reference/half | wall 秒 | CPU 秒合计 | 进程树采样峰值 MiB |
|---|---:|---:|---:|
| 3 workers | 47.32 | 129.27 | 480.14 |
| 4 workers | 41.67 | 133.00 | 633.01 |
| 5 workers | 40.28 | 128.59 | 780.36 |

5 worker 相对 3 worker 的 wall 降低约 14.9%。

| 2D Q1 base + thermal Q1 references | 总 wall 秒 | 2D worker wall 秒 | 2D solve 秒 | 进程树采样峰值 MiB |
|---|---:|---:|---:|---:|
| 单独（warm 对照） | 12.03 | 10.30 | 7.60 | 514.11 |
| +2 个 1D | 42.21 | 10.45 | 7.66 | 882.23 |
| +3 个 1D | 42.18 | 10.80 | 7.81 | 1021.93 |

最初单独一次包含首次 JIT（34.43 s），不能与 warm 混跑直接比较；上表单独列是补做 warm 对照。2D worker wall 增约 1.5% / 4.9%。调度保留内存余量，本轮未直接采集逐进程 swap 计数，不能据此声称全部长时 2D 都无交换。

Persistent：同 5 个完整 Q1 任务、1 worker，one-shot 83.79 s，persistent 77.95 s（降低约 7.0%），输出 NPZ SHA256 全部一致。worker 内峰值 145.62 / 153.42 MiB。该对照最初 parent 只采到 venv launcher，故不采用约 4 MiB 的无效树 RSS；后续修复为递归采样，其他表均使用修复版本。

同一个 persistent PID 连续运行 production 和 M10/Q1 solver mass replay 均 PASS，21.04 s；守恒残差绝对约 9.21e-16 kg、相对约 4.98e-15。不把这一例冒充完整 12 例重审。

真实 Q1 完整拆分 2D evidence 与原 V3 bundle 字典逐项一致。首次子计算 107.06 s（部分 base 已 warm），缓存复跑 24.52 s。Q23/Q4 相同原函数/参数的 fake integration 对照通过，本轮未重跑完整长轨迹。

## F. 完整审计时间情景

未完整实测，GUI 仍显示“正在校准”。用户提供的约 4.5 h 本身也是估计。以下只是明确条件下的规划情景，不是承诺：

- conservative：关键路径/内存使并行收益为零时仍约 4.5 h，外部负载可能导致更久。
- likely 条件情景：若总 wall 的 50%～75% 获得本轮 3→5 的 14.9% 收益，其余不变，约 4.0～4.2 h；没有完整 Q23 数据证明这个占比，不能称为统计上最可能。
- optimistic：若全部 wall 都获得上述并行收益和 7% pool 收益且可相乘，约 3.6 h；全量含不同关键路径、2D/GIF，不保证满足。

不从 Q1 外推更激进的加速。实际以首次完整 `developer_full_audit_timing.json` 为准。

## G. 数值与测试

13 个数值模块与 HEAD 一致（仅统一换行比较），88 个冻结发布资源 SHA256 一致；V2 的 165 个 EXE/源码文件哈希一致。核心聚合哈希 `829d9811ef26a6abdfe29ca1179bebbd4b5572578c888f4f24940e3c4e5098ad`。

完整 pytest、V4 EXE 四表 reference/readback、GUI/CLI 与包检查见下方最终验收记录。科学 WARNING（end effect、PARTIAL_2D、legacy fixed-grid）继续保留；没有放宽阈值。

## H. 发布

仅发布 `release_v4/A题_药材烘干模型/`；V2 未改，V3 发布目录按用户授权删除。精简包不含历史 work/results/logs。EXE 完整 SHA256 写入 `release_manifest.json` 及下方最终验收记录。工作区 benchmark 数据不随包作为历史缓存交付。


## 最终验收完成记录（2026-09-13）

- pytest：260 passed，71.01 s；额外覆盖内存等待时 ETA 必须为 unknown。原 259 项通过后，EXE 实际测试发现内存不足时旧 ETA 仍偏短，已修正并重跑全量。
- force-reference：34 个真实私有工作区准备 PASS，无 PDE；最终 EXE developer + force dry-run PASS。
- GUI Windows smoke：白底、选择按钮、详细日志、无隐式计算 PASS；新增 developer preset 另有 Qt 点击回归。
- 清空外部 Python 路径的 EXE verify / runtime-check / dry-run PASS；Numba、SciPy、Qt 等运行依赖检查通过。
- EXE persistent：同一 PID 连续执行 production 与 mass（匹配缓存）PASS，正常 shutdown；这项检查只验证打包协议与任务清理，数值等价另见有界重算 benchmark。
- V4 EXE 四表匹配缓存验收：18.42 s、1 worker。早先一次因外部可用内存不足暂停派发，已停止本轮 V4 测试进程后接入真实匹配 RSS，未触及 V2，未降低 2 GiB 保留阈值。该中止尝试不计入成功性能数据。
- Q3 = 57.6215 h；Q4 = 51.1824 h；完整精度参考最大差 = 0，四份 Excel 逐单元 readback PASS（1800 / 10800 / 3458 / 3071 行）。缓存验收没有新求解 PDE，不冒充冷启动。
- 完整 Developer Full Audit、Q23/Q4 的长时二维拆分和所有 GIF 没有重新全量实跑；它们的功能、依赖和原数学/判据保留，不能声称本轮全量审计已 PASS。
- 当前验收无未解决的程序 FAIL。历史 end-effect / PARTIAL_2D / fixed-grid 限制照常保留。

EXE SHA256：

- 药材烘干模型_GUI.exe: `7f22b27492e5deacf4b5f49675039b29b40e9d8f6dc1ff1f6df7eebe600fecb4`
- 药材烘干模型_原题表格复算.exe: `e678e21da58d70a41670f9f894d4204298adb202611aec7de0c91816c66c4201`
