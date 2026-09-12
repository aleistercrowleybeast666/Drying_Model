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
    药材烘干模型_原题表格复算.exe --all
    药材烘干模型_原题表格复算.exe --all --dry-run
    药材烘干模型_原题表格复算.exe --verify

--workers 默认为 2，可设 1 或 3。并行发生在 case/experiment 层，RK4/FV 内核保持原样。
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
进度按已完成任务单调增加。详细日志可展开、滚动和调整高度。
“立即停止”结束本次进程树；关闭 GUI 也会结束同目录本次复算。未保存进度会丢失，重启时重新核验缓存。

构建/验收细节及未实测项目见 dependencies/application/code/RELEASE_V2_VALIDATION.md。
