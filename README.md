# A题药材烘干求解工程

打开 `A_Drying.code-workspace` 即可在 VS Code 中使用已配置的 Python 环境和任务。当前源码、原始输入、缓存、图表、日志均在本目录内。

Windows PowerShell（在本目录执行）：

```powershell
# 本机已经安装好独立环境。换电脑时：
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 原始资料已提取。可重复检查，不覆盖原件：
.\.venv\Scripts\python.exe run.py prepare
# 首次导入也可指定 --source "C:\资料\CUMCM2026Problems.zip"
.\.venv\Scripts\python.exe run.py test
.\.venv\Scripts\python.exe run.py solve --case q1 --dim 1
.\.venv\Scripts\python.exe run.py solve --case q23 --dim 1
.\.venv\Scripts\python.exe run.py solve --case q4 --dim 1
.\.venv\Scripts\python.exe run.py validate --scope 1d
.\.venv\Scripts\python.exe run.py solve --case all --dim 2
.\.venv\Scripts\python.exe run.py validate --scope 2d
.\.venv\Scripts\python.exe run.py compare
.\.venv\Scripts\python.exe run.py export
.\.venv\Scripts\python.exe run.py plots
.\.venv\Scripts\python.exe run.py animate
# 顺序运行以上全部阶段，自动复用匹配的已完成缓存：
.\.venv\Scripts\python.exe run.py all
```

`solve` 支持 `--nr`、`--nz`、`--dt`、`--cap`（秒）、`--tag`。运行中每模拟一小时写检查点；重复同一命令可续算。输入、物性/离散核心或配置哈希不一致时拒绝复用；实验性改变请使用新 `--tag`，不要覆盖旧缓存。只修改图样后运行 `plots` / `animate`，不会重新解 PDE。

配置在 `configs/default.toml`，固定建模约定在 `configs/assumptions.json`。主模型为单元中心圆柱有限体积和经典四阶段 RK4；一维官方格式输出始终来自一维。第四问内部使用随体坐标，填表时转换到**当前空间中的固定 r**。域外点留空，表面独立重构。烘干事件经局部重新积分，保存不超过 0.1 s 的未达标/严格达标区间；报告时间向上取到 0.0001 h 并重新积分验证，另加在整分钟行之后。

输出入口：

- `results/status.json`：所有案例的积分状态、事件、步长、耗时与内存。
- `results/validation/`：18项程序测试、独立解析基准、通量残差、时间复算、空间对照数据。
- `results/candidate/`：四问官方结构 Excel 和关键数值 CSV。文件中的数值已实际计算并完整回读。**候选标识不是空间精度合格声明。**
- `results/final/`：只接收时间与明确空间验收要求均通过的一维结果。当前 prompt 没有给空间误差验收阈值，因此默认保留候选，避免把时间验证通过误写成网格独立。
- `results/partial/`：72 h 未烘干的真实时序，烘干时间为 null。
- `results/tables/`：全精度 NPZ（含有效域掩码）、简洁 CSV。
- `results/comparison/`：一维/二维同物理位置比较，含中截面、端面、分区和沿 z 数据。
- `results/figures/`、`results/animations/`：二维曲线、恰好两张三维分布图和两个 GIF。GIF 使用真实已保存二维场，非匀速物理时间映射。
- `logs/run.log`、`logs/events.jsonl`、`results/diagnostics.csv`：进度、可定位事件与数值诊断。

当前验证范围：一维做全程步长减半和 Nr=40/80 对照；二维主案例覆盖完整规定时段，额外时间复算、径向加密和轴向加密默认只覆盖前1800 s。长时二维空间/时间验证不宣称已完成。空间对照差值不是真实误差的严格上界；端面比较阈值不能借用为空间收敛阈值。

本工程不引入题面以外的材料参数，不外推72 h之后的半径，不生成论文或报告。原始 PDF 的辅助预览脚本仅用于本机查阅，不是求解依赖。
