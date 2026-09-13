如果只想复算题目要求的 4 份 Excel：
直接运行“药材烘干模型_原题表格复算.exe”。

如果希望选择验证、绘图或拓展：
运行“药材烘干模型_GUI.exe”。

两个 EXE 均无需安装 Python。请完整解压并保留 dependencies 文件夹。

四类任务：

- 原题计算：Q1、共享 Q2/Q3、Q4，只生成四表与必要数值摘要。
- 验证：正式阶段网格的完整 x2 参考、实际半步重放、remesh、二维辅助、水质量守恒。
- 原题绘图：正式曲线、三维展示；GIF 单独勾选。
- 拓展：热模式、几何交叉、环境尾窗、前沿、动力学和 diffusion clock 等。

只需题目四表：约数分钟。
论文复现全选：包含必要验证、静态图和创新结果，耗时取决于电脑。
高级完整审计：可能耗时显著更长。

无参数只执行原题计算。验证、绘图、拓展不会随默认双击隐式启动。
GUI 会展示自动依赖，并在补充计算前要求确认。绘图命令缺数据时报 PLOT_INPUT_MISSING，提示 A/B/D 所需数据，不启动 PDE。

Python 方式（建议 Python 3.12，64 位）：

    python -m pip install -r requirements.txt
    python 药材烘干模型_原题表格复算.py
    python 药材烘干模型_GUI.py

Windows 也可运行“安装Python依赖.bat”。源码运行与 EXE 使用同一计算链。

命令行示例：

    药材烘干模型_原题表格复算.exe --original q1 q23 q4
    药材烘干模型_原题表格复算.exe --validation
    药材烘干模型_原题表格复算.exe --plots
    药材烘干模型_原题表格复算.exe --plots --gifs
    药材烘干模型_原题表格复算.exe --extensions
    药材烘干模型_原题表格复算.exe --paper-all
    药材烘干模型_原题表格复算.exe --developer-full-audit
    药材烘干模型_原题表格复算.exe --paper-all --explain-schedule
    药材烘干模型_原题表格复算.exe --all --dry-run
    药材烘干模型_原题表格复算.exe --verify

--workers 默认为 auto，可设 1/2/3。按 CPU 与标称内存分配 1～3 个资源槽，二维占 2 槽，一维占 1 槽，发布独占。并行发生在 case/experiment 层，RK4/FV 内核保持原样。
正常 CLI 每约 5 秒更新一行加权进度和预计剩余时间；重定向输出时改为换行。
--verbose 显示详细 worker 日志；--machine-progress 输出统一 JSON 进度。详细日志始终保留在 logs/。
dry-run 显示用户选择、自动依赖、DAG、缓存预检、是否需要 PDE 和 worker 数，不创建计算缓存。
--verify 只核对发布资源完整性，不声称完成数值验证。

本包不包含历史结果、检查点、跨任务缓存或 CPU 专用 Numba 缓存。
首次运行自动建立 work/recompute/、logs/、results/。已有匹配缓存可复用；删除 results 后也可从输入重新生成。
正式输出：results/tables/result1.xlsx ～ result4.xlsx。
运行记录：work/recompute/timings.json、results/recompute_timing_summary.json。
计算工作区：work/recompute/runtime/；独立 case 目录：work/recompute/workers/。
所有路径均相对于当前程序目录，可以整体移动；不依赖原开发机路径。

冻结网格位于 dependencies/application/code/configs/frozen_mesh/。
它校验输入、数值核心、配置、阶段方案、monitor 和 faces 的哈希。损坏时明确报错，不自动运行长时 pilot。
Q1 到 1800 s；Q23 至少覆盖 Q2 的 10800 s，然后到 Q3 真实烘干报告时刻；Q4 同样在真实报告时刻停止。
拓展另用完整时域轨迹，72 h 定义未改变；早停缓存不能冒充完整轨迹。

冻结参考：Q3 {q3:.4f} h，Q4 {q4:.4f} h。
四表进行逐单元数值回读，以及完整精度数组/事件/半径的参考比对。
TABLE_RECOMPUTE_REFERENCE_MATCH: PASS 表示与冻结数值一致，不是重新进行空间或时间收敛认证。
仅表格复算的数值验证标为 NOT_RERUN_IN_TABLE_ONLY_MODE。
历史 fixed-grid 为 legacy / diagnostic only，不能否决正式阶段方案。
二维通过辅助用途验收也不代表完整二维网格独立性认证；仍保留 PARTIAL_2D 限制。

本机真实实测：{benchmark}
验证、二维、守恒和拓展依赖较多，耗时以每项 timings 为准，不能用任务个数估算剩余时间。
任务进度只来自真实接受步、阶段、文件或帧完成数，不随经过时间自行上涨。总进度按已用时间和关键路径剩余时间估算，并标明可信度：实测/标定显示数值，粗估显示整数和时间区间，缺少证据或百分比与 ETA 冲突时显示“正在校准”。成功完成才到 100%。预计时间不是承诺。
DT_LIMITED_BY_STABILITY 是正常步长保护，每任务默认只提示一次 INFO；原 code、requested/actual dt、网格保留在详细日志。RK 拒绝、接近 min_dt、MAX_STEPS、非有限值、fallback 或验证失败仍警告。
GUI“全选（论文复现）”不选动画。当前论文明确引用 12/12 守恒，因此论文复现保留 12 例并按 production 完成后流水审计；冷启动属于较长的严格检查，不冒充已经验证。高级区域可选动画、强制参考和历史开发诊断。
D 的一维分支不等待二维辅助汇总；仅 matched/end-effect 和最终发布等待二维。B/D 三条同身份 M00 全程参考只算一次。72 h 共同对照仍需要的轨迹共享最长一次，未擅自缩短证据时域。
详细日志可展开、滚动和调整高度。“立即停止”结束本窗口启动的进程树，关闭窗口时会先确认。
外部 CLI 运行只供观察：关闭 GUI 不会停止外部 CLI；点击“停止外部复算”需要另行确认，并再次核验进程身份。
未保存进度可能丢失，重启核验检查点与缓存后恢复。
01_end_effect_extent.png 依赖 matched M00 拓展数据，统一归拓展；只选验证不会隐式运行完整拓展。

构建/验收细节及未实测项目见 dependencies/application/code/RELEASE_V3_VALIDATION.md。
