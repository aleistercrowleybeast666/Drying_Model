# 评委交付版构建与验证记录

## 当前精简交付与立即停止

最终路径仍为 release/A题_药材烘干模型/，覆盖原发布目录。顶层仅共享 dependencies、两个 EXE、对应两个 PY、安装依赖 BAT、requirements、README/TXT 和 manifest。源码/配置/原始输入位于 dependencies/application/；不携带已有 results、work、检查点或跨进程运行状态。运行时自动初始化目录，无缓存可从头计算，有缓存仅按原有验证规则复用。无结果时 --verify 只证明随包资源完整，不宣称数值验收已重新完成。

“立即停止”终止已确认属于本目录的复算进程树；正常关闭 GUI 同样终止它，包括重新打开 GUI 后识别的任务。校验 PID 创建时间（新任务）及入口路径以避免旧锁/PID 复用误杀。强停写 interrupted.json 并清理对应锁。缓存/检查点的原 JSON/NPZ 写入采用临时文件替换，路由记录也改为原子替换；仍可能丢失未保存进度或留下未完成导出，不保证强停后所有文件都完整，也不改写数值阈值为通过。

最新测试：158 passed（66.17 s）；真实 frozen EXE 无外部 Python 冷启动、原输入初始化、目录重建，以及 GUI 关闭时终止自有/已有任务和子进程均 PASS。未运行全套长时 PDE。证据：work/release/minimal_acceptance.json、minimal_cold.log、minimal_lifecycle.log。当前 EXE SHA256：GUI 9fe4d0e915f35ef92feea52512582d3b1e017be51f98d806ba10ba0e1ef24562；CLI 78fbfea2fe368602ef472e5b469351b1849debf26f043b5e8580f87bf8420372。以下是历次版本记录，旧目录/停止行为/EXE 哈希以本节和当前 manifest 为准。

本轮仅修改界面、入口、任务编排、运行时文件定位和发布设施。交付位置：`release/A题_药材烘干模型/`。正式结果仍为 M00 一维径向模型，Q3 57.6215 h、Q4 51.1824 h。以下记录区分已执行检查和未执行的长时复算。

追加修复：用户删除发布目录 results 后，旧启动代码无条件复制它而失败。现在允许 results 缺失及上次初始化不完整；从原始输入创建私有工作区，完成的复算输出自动重建 results，已有原交付文件仍不覆盖。日志使用 16 px 深色文字、可拖动分隔区、横向滚动，失败自动展开。实际执行“移动到含中文/空格的新目录、从其他工作目录启动、无 results/work、PATH 无 Python”的 EXE 集成检查：真实路由初始化、真实子进程、原始输入准备、Numba/运行库和结果目录重建均 PASS。该测试替换为有界诊断任务，不声称完成长时 PDE；证据为 work/release/cold_relocation.json/.log、cold_gui_smoke.json/.png。路径不依赖开发机目录，内部任务工作目录及持久记录使用相对路径。

使用 `scripts/build_release.py --update-code` 对现有发布目录更新代码和说明，保留用户删除的 results 状态和已有 work。下述原始正式文件哈希是冻结参考，不表示用户已删除的发布副本仍存在。

追加回归结果：152 passed（68.21 s），覆盖缺失 results、部分初始化恢复、删除后的输出重建及移动目录定位。正式数值文件仍保持原冻结哈希。

白色背景与单调进度更新：154 passed（75.07 s）。新增深色系统调色板测试及乱序/失败进度不回退测试；实际 EXE 窗口截图为 work/release/white_gui_smoke.png。移除循环条，进度按阶段完成增加，长阶段内保持不变。

安全停止追加修复：与 QProcess 启动/运行状态绑定，运行中使用橙色启用样式；点击后禁用以等待安全退出。重开 GUI 时读取同目录 runner.lock 并检查 PID，支持对已有复算请求停止，不启动重复任务。全选 17 阶段的正式 PNG/GIF 在第 5 阶段生成；第 1 阶段 Q1 仅一维验证、Excel 和数值导出，不会提前生成依赖二维数据的比较图。工作记录已确认此前仅 q1 阶段完成。

1. **GUI 启动失败的实际原因。** 原虚拟环境缺少 PySide6，旧入口在顶层导入 Qt。实际 EXE 构建又发现 imageio 分发元数据遗漏、MSYS 的同名 ICU DLL 被误收集，以及 GUI 独立模块包缺少外部应用源码使用的 `json` 等标准库。用户本轮看到的弹窗对应最后一项。

2. **修复。** 安装 PySide6 6.11.2，入口延迟导入并给出可读缺依赖提示；统一 scoped enum。spec 收集运行包元数据，构建 PATH 排除 MSYS，两个 EXE 共享完整 Python 模块集合和原生依赖。正常启动失败写 `logs/gui_startup_error.txt` 并显示中文提示。截图检查还修正了 Windows 深色主题下浅底白字的问题。

3. **单页布局。** 顶部已有正式结果；中间正式/补充项目两列；下方选择按钮、开始按钮、当前任务、单调任务进度、安全停止及默认折叠日志。没有页签导航、目录浏览或数值参数编辑。源码和 EXE 均实际打开过 Windows Qt 窗口，检查勾选、按钮、日志、正常关闭和启动不自动计算。

4. **两个 PY。** `药材烘干模型_GUI.py` 委托 `code/judge_gui.py`；`药材烘干模型_完整离线复算.py` 委托 `code/offline_recompute.py`。支持安装依赖后的源码运行。非 Windows 源码运行未在其他操作系统实测。

5. **两个 EXE。** GUI 使用 windowed，调用同目录 console 复算 EXE；复算 EXE 无参数默认全部任务，命令行可选项目。只在 Windows Explorer 独立双击、无参数运行结束时等待回车，显式命令行不强制暂停。

6. **完整流程。** 正式 Q1 → Q23 → Q4 → 二维轨迹和方向验证 → 正式图表 → 冻结本次隔离基线 → 一次 M00 基础研究（包括几何、环境）→ M10 → M01 → M11 → 补充图表 → 几何交叉 → 技术图 → 水质量守恒 → 二维辅助验收汇总 → 本次复算结果检查 → 已交付结果/事实检查。共 17 个实际阶段。调用原权威入口，不重写数值算法；匹配缓存由原入口核验，日志明确显示复用/重算。必要依赖也显示在计划中。

7. **复选项目。** Q1、Q2/Q3、Q4、二维辅助验收、水质量守恒、几何—物性交叉、环境延拓敏感性、M10、M01、M11、快速结果一致性验证，共 11 项。仅选一道正式题时只算该一维轨迹、验证与 Excel；综合图和研究会显式补齐所需基线。水质量与几何交叉的既有事实发布器需要四模式数据，会补齐三个热模式。

8. **选择按钮。** 全选、全不选、仅正式题目均已实现并实际测试。默认只勾选三个正式项目；空选开始会提示选择，不启动求解。

9. **进度和停止。** QProcess 接收统一 CLI 的 `DRYING_EVENT` JSON，按实际完成阶段计数。使用单一确定进度条，完成阶段后单调增加；长阶段内保持不变，不循环、不按运行时长估计百分比。失败或停止保持已完成进度，仅新一轮开始归零。滚动区、日志容器和窗口均显式采用白色调色板，不继承系统深色背景。UTF-8 分块日志保持完整。安全停止写入原有 STOP/BASELINE_STOP 检查点标记；关闭运行中窗口先等待安全退出，不强杀子进程。

10. **文件分离。** `code/data/results/dependencies` 分开；源码可审查。运行时将原源码与配置按原布局放入私有 `work/recompute/`，原 `__file__`、Numba 定位和数值源码指纹保持有效，重算输出在 `work/recompute/results/`。发布目录不预装历史 work、虚拟环境、Git 元数据或 pytest 临时目录。构建机回归证据单独置于 `code/release_evidence/`，明确不表示评委电脑运行过测试，也不代替数值验收。

11. **README/TXT。** 由 `Build_GetReadme` 同一个字符串生成，构建时逐字节检查完全一致。说明 EXE/PY 用法、目录、正式数字、依赖、隔离输出、完整计算耗时和安全停止。

12. **运行依赖。** numpy>=2.0、scipy>=1.13、numba>=0.61、matplotlib>=3.9、openpyxl>=3.1、pillow>=10、imageio>=2.35、PySide6>=6.7、pypdf>=5、psutil>=6、iapws==1.5.5。llvmlite 随 numba 安装。pytest 和 PyInstaller 位于单独的 requirements-build.txt，不属于运行依赖。

13. **BAT。** 实测无 Python 分支给出中文提示；实测 python 回退分支对完整 requirements 执行 pip 检查并成功（已有依赖、禁用索引）。`py -3` 优先探测存在，但本机限制环境下无可用注册解释器，未声称成功测试该分支安装。首次联网下载全部依赖未另建空环境重测。

14. **共享打包。** PyInstaller 6.22.2，自定义两个 Analysis、共享完整 PYZ、两个 EXE、单一 COLLECT；`contents_directory='dependencies'`，非 onefile。应用数值模块以物理源码放在 code/src，原生库、元数据和 Qt 插件放入公共依赖目录。清理构建缓存并限制构建工具 PATH，避免同名 DLL 污染。

15. **唯一依赖目录。** 最终只有一个顶层 dependencies，无两套 `_internal`。README/TXT、两个 PY、两个 EXE、安装 BAT、requirements 和 manifest 均由构建工具生成。

16. **外部 Python。** frozen 路由只启动同目录复算 EXE。已实际执行 EXE 内部工作进程、Numba 原物性调用、质量审计所需源码 AST 检查、内存 Excel 往返、Agg 绘图；GUI→CLI 的正式任务和全选 dry-run、已有结果实际校验均通过，未调用外部 Python。

17. **Windows 环境测试。** 使用本机 Windows 的受限进程环境，PATH 仅 System32，清空 PYTHONHOME/PYTHONPATH。两个 EXE 启动通过；Qt、NumPy、SciPy DLL、Numba JIT、llvmlite、Matplotlib 数据、openpyxl、Pillow、imageio、IAPWS、pypdf、psutil 全部通过。此为移除 Python PATH 的测试，不等同于全新 VM/Sandbox。源码自动回归 149 passed；真实窗口截图与日志保存在构建工作目录 `work/release/`。

18. **EXE SHA256。** 见文末精确哈希和 release_manifest.json。共享 GUI 应用源码位于 code/src，分发完整性应同时核对 manifest 文件清单，不能只比较 EXE 哈希。

19. **官方 Excel。** 四份逐字节保持不变，哈希见文末。没有打开并保存或重新格式化 Excel。

20. **paper_facts。** JSON/Markdown 逐字节保持不变。全部正式结果、数据、配置和十个数值核心文件共 88 项冻结检查通过；发布包数据/结果 69 项核对通过。已有二维辅助验收仍为 PASS，严格全场网格独立性仍保留 PARTIAL_2D，不修改结论。

21. **数值核心。** 未修改 Material_Evaluate、PDE、FV/RK4、边界、网格、阈值、热模型或水质量定义。compute.py 只添加选择性/二维入口编排；baseline.py 只在没有 Git 时给构建元数据提供回退。原入口保留原来的验证判定。

22. **WARNING / TODO。** 本轮启动、路由、运行库及回归检查没有剩余 FAIL。既有二维 PARTIAL_2D/局部边界诊断保留；不将其改写成严格网格独立 PASS。没有为 GUI 验证重新执行数小时至数天的完整冷缓存 PDE 流程，因此全流程冷启动数值完成和全新 Windows VM/其他操作系统测试仍未实测。构建静态分析中的平台可选模块提示不作为数值验收结论；实际必需库的运行检查已通过。

实际测试证据：`work/release/exe_gui_smoke.json/.png`、`runtime-check_exe.log`、`verify_exe.log`、`dry-run_exe.log`、`internal_worker_exe.log`、`bat_test/summary.json`、`work/validation/program_tests.json`。工作日志不打包成历史缓存。

## 精确 SHA256

| 文件 | SHA256 |
| --- | --- |
| 药材烘干模型_GUI.exe | `7c9dd153b96d7d0740f0ad147a8a477d15389b6f54761d6b9d810af95ce5e80c` |
| 药材烘干模型_完整离线复算.exe | `b0b1abbae0fbbee331fce18c092aaad8c9d5dab2fbfe0f2434b02b035c6a4247` |
| result1.xlsx | `76046ec81133ec1d48224718de3cd0ec4884211ebab8c5d75e5cddfb11c808c1` |
| result2.xlsx | `2c36d6dc4de5c45ae35ee3070611cb81a8b92feeddb84002584b15f49e9ac0bd` |
| result3.xlsx | `5e27bd51abd50f8e7866a6a79cc35fec248070e92f5b9a782eeb1d6c895b59ed` |
| result4.xlsx | `61176de3b2cc000e475bce418b1816d2e2eaae334ecd8ac29c88be3051dbab20` |
| paper_facts.json | `0bb11c055f35a7863e022f2387dc8f090dd68d47b9078dd06e16519584d9a3bd` |
| paper_facts.md | `c58014801a52a65f072b89a41d7ed6a555b34b8348a9e7a636d773bfea17a3dd` |

安全停止最终回归：156 passed（77.35 s），包括真实子进程运行时按钮启用、点击写停止标记，以及重开界面识别已有任务。

按钮交互追加修复：已验证本机仍有后台复算且已有停止标记，旧界面因此将所有操作禁用。现在选择按钮始终可用（用于下一轮），运行中的开始按钮用于查看状态、不重复启动；等待安全停止时可再次请求。此次 20 项 GUI/入口回归全部通过，覆盖已有进程时全选/清空/查看状态与停止请求。
