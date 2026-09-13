# V3 验收记录

基线 main ee767c6。V2 运行中，本轮只操作源码、work/release_v3 和 release_v3；旧 release 已核验无进程后删除。

## A. 稳定性诊断

仅 presentation 将正常 DT_LIMITED_BY_STABILITY 分类为 INFO / NORMAL_STABILITY_LIMIT，每 task 默认一次。原始 worker 日志保留完整 code 和参数。历史 Q1 早期 nr=200 的真实示例：requested dt=0.25 s，accepted dt=0.006880767643451691 s。接近 min_dt、RK rejection、MAX_STEPS、非有限值、fallback、validation fail 仍警告；未修改求解器、网格或阈值。

## B. Console

Windows 尝试启用 VT 后用 CR+ANSI 清整行；不可用时按终端列宽清空。中文输出按显示列宽截断，时间放在长任务名前，避免换行残影。重定向为普通换行、无 ANSI。自动测试覆盖长短行、中文、10:05→9:59、2:00→12:00 和 fallback；新 EXE 重定向实跑通过。未另做 Windows cmd/Windows Terminal 人工逐终端观感测试。

## C. Progress / ETA

删除 elapsed/历史 wall 推进 task_fraction 的逻辑。真实任务进度来自接受步、阶段或文件/帧完成；总进度为 elapsed/(elapsed+critical-path ETA)，附 measured/calibrated/rough/unknown。ETA 慢 EMA，rough 显示区间和整数百分比，unknown 显示校准中。百分比与 ETA 不一致时自动降级。GUI tau=10 s，上升不超过 0.8 个百分点/s；真实 run PASS 才到 100%。更新后的 GUI smoke 已验证选择按钮、日志、无自动求解及白色界面。

## D. 调度优化

D 一维生产/参考与 B 二维独立；仅 matched/end-effect 和最终 publish 等二维。短独占汇总会先排空当前 worker，避免被后续计算饿死。守恒按每条 production 完成后优先进入队列，最后统一发布。论文引用 12/12，因此保留 12 例：M00 是原题正式 accepted trajectory 至真实报告端点，thermal 是各自完整生产轨迹，不能混称 M00 的烘干后 72 h 延长段也重新审计。

B/D M00 full_reference 去重 3 条；实际 reference ID 核对相同。Q1 使用真实旧密封证据完成“参考任务→正式验证任务”交接测试，空间/时间均 PASS，测试禁止 PDE 调用且实际调用为 0。缓存参考回执标记 cache_reused，避免被学习成冷成本。CPU+RAM 自动 1/2/3 槽，本机 nominal 16 GB 为 3 槽；1D 一槽、2D 两槽、publish 全槽。

## E. 选择范围与任务数

| 范围 | logical tasks | 实际调度任务 | unique PDE/replay 任务单元 | 去重 |
|---|---:|---:|---:|---:|
| paper-all | 79 | 76 | 65 | 3 |
| developer-full-audit | 83 | 80 | 68 | 3 |

PDE/replay 数是 DAG 单元数，二维验证单元包含下表列出的多个真实子求解，不等于单次 RK4 调用数。Paper-all 不选 5 个原题 GIF、2 个 thermal GIF 或 legacy 诊断；developer 额外选择动画、强制重算参考和 fixed-grid 诊断。

## F. 实测和估算

230 项 pytest 全部通过（74.41 s）。两 EXE 构建 PASS；清理 PATH 后 CLI verify/runtime-check/dry-run 和 Windows GUI smoke PASS。新目录最初没有 work/results，资源检查与 GUI 可以启动并自行准备；四表 warm 使用明确匹配的历史 A 缓存，未使用活动 V2 工作目录。

| 项目 | 耗时 | 证据类别 |
|---|---:|---|
| V3 A warm，1 slot，含启动/准备/检查 | 11.15 s | 本轮 EXE 实测 |
| 新 V3 路径已有数值缓存、尚无本地 JIT 缓存 | 33.94 s，其中准备/JIT 21.64 s | 本轮 EXE 实测，不能称 PDE cold |
| V3 A cold | 未实测 | V2 仍在运行，低可用内存阶段避免争用；历史 V2 185.99 s 仅作背景 |
| Q23 base 2D，40×125，72 h | 1062.30 s | 既有完成 status，1036800 accepted steps；本轮未冷跑 |
| M10 Q23 production，72 h | 195.33 s | 既有完成 status，4221848 accepted steps；本轮未冷跑 |
| paper-all，auto=3 | 中心估计 3.86 h；粗略区间 2.31～6.56 h | 混合历史成本+调度模型，rough，**无完整 calibrated 实测估计** |
| developer-full-audit，auto=3 | 中心估计 6.46 h；粗略区间 3.87～10.97 h | rough，未全冷实测 |

二维历史共 16 条，trajectory 历史 40 条；没有 1D×500。上述全选时间只在开发验收记录注明估算，不写入评委 README 为实测承诺。旧 V2 timings 导入先检查科学身份，拆分后 scope 不同的 B 复合任务不直接学习。新版本不依赖 V2 文件存在。

## G. 数值不变性

本轮 V3 四表复跑 Q3=57.6215 h、Q4=51.1824 h；四份 full-precision reference max diff=0。另用现有 Export_Readback 逐单元读取本轮发布结果，表名、尺寸、数值、格式、空白和事件时间均 PASS。表格模式明确标 NOT_RERUN_IN_TABLE_ONLY_MODE，不能将数值一致误写为重新完成全套收敛认证。13 个数值模块与 HEAD 相同，88 个冻结发布文件哈希不变。数值核心聚合 SHA256：`829d9811ef26a6abdfe29ca1179bebbd4b5572578c888f4f24940e3c4e5098ad`。

## H. Release 与文件保护

发布位置：`release_v3/A题_药材烘干模型/`。仅保留两个 EXE、两个 Python 入口、说明、依赖安装文件、dependencies 和 manifest 共 10 个顶层项目；验收生成的 work/results/logs 保存在仓库 work/release_v3，不随包交付。

- GUI EXE SHA256：`a6d67f67cbfd44d3365dac07e05eb8d154b0c0afd9eb49aaffae7dfb067272fa`
- CLI EXE SHA256：`b0d27e8b3def2955ba218ef211f23448664e85354387e3816ce8488f860827c3`
- 旧 release/ 已核验没有活动 PID/create_time/cmdline 后删除。
- release_v2/ 未写入、删除、移动或停止；156 个静态文件逐项哈希复核一致。活动 V2 自身继续写运行日志是正常行为。
- 完整证据：work/release_v3/final_tests.log、full_test_receipt.json、excel_readback.json、reference_reuse.json、invariance.json、paper_plan.json、developer_plan.json 和 build/ 中 smoke 记录。

## 二维路径对照

| 证据 | V2 judge 路径 | V3 judge 路径 | 论文用途 |
|---|---|---|---|
| base 2D | 每 case 一次全观察窗 | 保留，同一 Case_Solve | 端面影响、模型降维 |
| 时间验证 | 既定早期实际半步 | 保留原 Validation_CheckTime | 辅助 PASS |
| 径向/轴向参考 | 先 max(1800, representative)，不足 critical window 再求解一次 | 直接 max(原窗口, representative, critical window)，一次每方向 | 覆盖原证据及 Q23 5086 s / Q4 10320 s |
| 两端点配对 | Case_SolvePairEvents | 保留；独立 case 工作区没有其他 case 数据，避免跨问题重复 | 真实报告场对照 |
| 终点方向敏感性 | 原晚期投影+真实积分 | 保留原 Validation_CheckEndpoint | Q3/Q4 endpoint diagnostics |
| fixed/uniform/candidate | 不在 V2 默认二维路径 | 不增添，仅 developer 诊断保留 | legacy / diagnostic only |

原 Validation_Run 数学与判据文件未修改；V3 adapter 仅调整局部调度窗口，不改配置文件、求解器或阈值。二维仍 PARTIAL_2D，不能宣称完整二维网格独立性。

## 时域检查

缩短数量为 0。M00/thermal 的共同时间表、72 h 几何性质对照、fixed-radius 无事件和共同图表仍读取 72 h 数据；Q1 本来就是 1800 s。kinetics/t50/front/driver 不另开 trajectory，直接截取共享最长数据。当前不能仅为速度提前截断这些共同源。B/D 三组 M00 full reference 的实际 experiment_id 已逐项核对完全一致，去重 3 条；不同 horizon/purpose/replay 不合并。

## 尚未实测

完整 paper-all、developer-full-audit、二维全冷、thermal 全冷、12 例守恒全冷和全部 GIF 未全冷实测。V2 正在执行，优先使用已有密封 A 缓存和历史成本，不与 V2 同时启动完整审计。静态图的 skipped GIF 不应被描述为已生成。
