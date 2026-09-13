# release_v2 进度与发布验收

基线：main `15b2bf1`。本轮只修改调度、只读进度观察、GUI、输出分类和发布层。原题数学模型、物性、FV、RK4、事件定位、网格、stage schedule、dt_max=0.25、阈值和正式结果未改变。旧 `release/` 未覆盖、移动或清理。

## A. 修改内容

- CLI/GUI 共用 schema_version=1 进度协议，包含 phase/task/group、任务与总进度、elapsed/ETA、running/completed/total、cache_reused；run_id/PID/create_time 用于外部任务校验。
- 按工作量加权，准备目录、输入、冻结网格及 JIT 也参与。不再按任务数平均；成功才精确 100%，STOP/FAIL 保持小于 100%。
- A 的独立 observer 在原 RK4 分块调用返回后统计接受步，每约 1.5 s 限频报告；按阶段实测 wall 和 accepted/expected steps 加权，Q3/Q4 使用真实报告终点。不改变数值模块或其调用参数、次数、分块、浮点运算次序。
- B full reference/半步/守恒按阶段和接受步观察；静态图按图片数、GIF 按帧数；导出和发布有明确子步骤。尚不便安全插入的旧 2D/拓展模块按耗时保守预测，最多 95%，实际 PASS 回执才到 100%。
- ETA 混合历史耗时与当前速度，按 worker 数及 DAG 依赖作简单 list scheduling，再平滑显示。CLI 每约 5 s 更新，TTY 复用单行、重定向换行，WARNING/ERROR 独立行。`--verbose`、`--machine-progress`、`--gui-run` 分工明确；`--dry-run` 仍输出 JSON DAG。
- GUI 0～10000、显示 0.1%，每 200 ms 仅向已收到的安全上界插值。关闭自己的运行任务先确认；关闭只观察外部 CLI 的 GUI 不停止外部进程。停止外部任务须确认并重新核验 PID、创建时间、命令行和根目录，身份变化则拒绝停止。
- `01_end_effect_extent.png` 统一归 D；B 不隐式依赖完整 D。全部 39 个现存 PNG/GIF/XLSX 登记 group、required_sources、producer_tasks，并与 DAG 对照。绘图不启动 PDE。
- 重定向 CLI 不再触发双击窗口的回车等待。进度参考使用稳定的数值输入 hash，避免 worker 刷新描述性输入清单后误判失配；配置损坏只回退显示估计，不影响科学缓存。

## B. 权重依据

发布的 `configs/progress_reference.json` 已用最终成功冷启动 `work/release_v2/progress_cold_benchmark.json` 更新。阶段权重是 wall 秒，使用时在任务内归一化；task wall 含导出和回读等开销。Q2/Q3 共用一个 task。最终冷启动使用前一次校准权重，随后 warm 自动采用最新成功 task wall；发布种子再同步这次最终实测，数值身份不变。

| Task | task wall/s | accepted steps | 各阶段 Nr / steps / wall_s |
|---|---:|---:|---|
| A.q1 | 9.599320 | 39,720 | 200 / 7,320 / 0.624290；160 / 15,600 / 1.260113；80 / 14,400 / 0.814591；40 / 2,400 / 0.184094 |
| A.q23 | 162.785126 | 3,392,650 | 200 / 20,100 / 9.329748；160 / 91,414 / 7.007353；80 / 3,281,136 / 109.632429 |
| A.q4 | 45.897116 | 986,857 | 200 / 19,215 / 8.896771；160 / 95,969 / 6.552999；80 / 221,046 / 9.035998；40 / 650,627 / 12.722460 |

每阶段 nz=1、起止时刻和实际平均 dt 保存在参考 JSON。准备四子阶段实测 0.125、0.344、0.266、18.359 s；总准备/JIT 19.528088 s。还保存来源 run、生成时间、11 个数值文件 hash、输入 hash、frozen schedule/mesh hash 和密封 hash。全部匹配才复用；最近同身份成功非缓存 task wall 优先，warm 不覆盖 cold 权重。无数据时按 stage/cell/step 和任务类型保守估算，不冒充实测。

## C. 实测

最终 EXE cold **185.989863 s（3.100 min）**，warm **7.737003 s**。cold 无 work/results、PATH 无外部 Python、stdin/stdout 重定向，只运行 A 三个 task，2 workers，包含启动、准备/JIT、求解、Excel、回读和发布。warm 三个 task 全部 cache_reused，四 Excel SHA256 与 cold 相同。测试期间还打开并关闭实际 GUI 观察外部 CLI，CLI 持续运行；不把机器负载变化解释成求解器加速。

| 指标 | cold | warm |
|---|---:|---:|
| 准备/JIT / s | 19.528088 | 1.496009 |
| 事件数 | 198 | 22 |
| 最大事件间隔 / s | 1.062 | 1.016 |
| 最大总分数保持间隔 / s | 8.110 | 1.016 |
| 最后非终态 ETA 误差 / s | +3.554 | +1.156 |
| 单调不下降，成功最终 1.0 | PASS | PASS |
| 计入的进度开销 / s | 0.874 | 0.348 |
| 计入的进度开销 / % | 0.470 | 4.498 |

cold 结束前约 10 s 的 ETA 误差 +3.468 s。分数最长保持出现在早期阶段切换附近，期间心跳仍更新；没有为消除停顿虚造接受步。事件间隔与分数保持间隔分别统计。

进度开销按 parent 写盘/输出计时、worker 报告计时与成对空调用 guard 探针估计，不是完整 PDE A/B 严格差分。warm 很短，固定开销占比较大，不声称所有场景均小于 1%。不逐步写盘，父进程约每秒保存一次快照。原有 DT_LIMITED_BY_STABILITY 提示保留，无新增运行 FAIL。

## D. 数值不变性

- Q3 **57.6215 h**（207437.4 s）；Q4 **51.1824 h**（184256.64 s）。
- 四 Excel 保持原格式、域外空白和正式来源。time/T/C/R/surface/event 的 frozen full-precision reference 最大差均 **0**；四份逐单元 readback PASS。cold/warm 四 Excel SHA256 相同。
- `TABLE_RECOMPUTE_REFERENCE_MATCH: PASS` 不冒充收敛验证，A-only 为 `NOT_RERUN_IN_TABLE_ONLY_MODE`。历史 fixed-grid 为 legacy / diagnostic only，二维保留 PARTIAL_2D。
- materials、boundaries、operators、rk4、sampling、inputs、events、geometry、cases、stages、table_solver、thermal、trajectory 字节与 main 基线一致。冻结 numerical_source_hash：`829d9811ef26a6abdfe29ca1179bebbd4b5572578c888f4f24940e3c4e5098ad`。11 个进度身份源码 hash 另存参考 JSON；原 publication manifest 的 88 个受保护文件另行逐文件核验。

## E. 测试与发布

完整 pytest **192 passed in 69.98 s**，覆盖加权/并行/单调/STOP/FAIL、准备/JIT、内部进度、cache/stale reference、workers=1/2/3 ETA、CLI tty/redirected/machine、GUI 协议与 0.1%、外部关闭不杀进程、外部停止确认和身份重验、自有进程及子进程停止、输出分类/DAG、数值 hash 与原 Excel 检查。

实际双 EXE 另测：GUI 打开、观察并关闭后，外部 CLI 的 PID/create_time 未变且继续计算，PASS。

真实 Q1 保存检查点后停止，停时进度 85.028% 而非 100%；重启恢复，退出码 0，参考/回读 PASS。Windows venv launcher 与实际 runner PID 分开识别。

实际 EXE `--verify`、`--runtime-check`、`--dry-run` 和 GUI 可见性 smoke 在 clean PATH 下执行。证据在 `work/release_v2/`，包中只复制回归记录，不复制数值缓存；这些是开发机证据，不代表评委电脑已执行测试。

发布到 `release_v2/A题_药材烘干模型/`：共享 dependencies、两个 EXE、两个 Python 入口、说明、依赖文件及 manifest。验收 work/results/logs 移入开发目录留证，首次启动自动新建。新 EXE SHA256：

| EXE | SHA256 |
|---|---|
| 药材烘干模型_GUI.exe | `5624c9b4fa15b71d1c0ccb7cb091b4f86767e79018b0ce054c7e9aa90d6c6ee0` |
| 药材烘干模型_原题表格复算.exe | `e503a1b0aea07eacb55a81d9ee3c5b24b154d6eb812463e31e8d2823fbf77d81` |

## F. 尚未实测

本轮未启动完整 B、2D 全冷、12 例守恒全冷、D 全冷、全部 GIF 或 `--all` 全冷，均为 **未全冷实测**。workers=1/3 覆盖调度/ETA 测试，没有另跑完整 A 冷启动。B/C/D 观察和估算经路由/单元测试，不宣称其端到端性能和进度已全实测。

上一轮一维正式验证、M00 三例守恒、原题静态图及辅助图证据仍在 `work/release_v2/`，本轮保留未重跑，不能替代未实测的完整任务组。
