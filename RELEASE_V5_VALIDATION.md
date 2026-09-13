# V5 最终源码交付记录

基线：`da351c0600f6aac5dd2f21318b7408be20797483`。交付目录：`release_v5_final/A题_药材烘干模型/`。

## 目录与运行

```text
A题_药材烘干模型/
├─ 请评委先看.md / 请评委先看.txt
├─ 01_四表正式数据_终端版/
│  ├─ main.py / README.md / 说明.txt
│  ├─ requirements.txt / 安装依赖.bat / package_manifest.json
│  ├─ 原始题目数据/（A题.pdf、附件1.xlsx、附件2.xlsx、附件3/result1~4.xlsx）
│  ├─ dependencies/（src/drying、configs、data/inputs.npz 与 input_manifest.json）
│  ├─ results/（tables 中四份已核验 Excel）
│  ├─ work/（空）
│  └─ logs/（空）
└─ 02_完整功能_GUI版/
   ├─ main.py / README.md / 说明.txt
   ├─ requirements.txt / 安装依赖.bat / package_manifest.json
   ├─ 原始题目数据/（同上，独立副本）
   ├─ dependencies/（src/drying、configs、预处理 data、backend.py）
   ├─ results/（核验有效成果）
   ├─ work/（核验有效科学缓存）
   └─ logs/（空）
```

推荐 Python 3.11（64 位）。每版先运行安装依赖.bat，再运行 `python main.py`。缺库提示不会自动安装。backend.py 经 Judge_Main 分发 worker/persistent/verify/runtime-check。两版均可单独复制使用；dependencies 不再存放原始附件。原始文件在运行时按原相对布局准备，以保持既有输入哈希排序，不修改 inputs.py。

终端 requirements：

```text
numpy>=2.0
numba>=0.61
openpyxl>=3.1
psutil>=6
```

GUI requirements：

```text
numpy>=2.0
scipy>=1.13
numba>=0.61
matplotlib>=3.9
openpyxl>=3.1
pillow>=10
imageio>=2.35
PySide6>=6.7
pypdf>=5
psutil>=6
iapws==1.5.5
```

## 修复与种子数据

- 终端仅适配外部入口和输入路径；official_progress.py 与基线逐字节一致。
- GUI ETA 未知时仍接收结构进度，移除界面二次置信度降级，补齐二维成本别名与 thermal 轨迹历史匹配。
- 顶部全选加入完整 A/B/C/D；普通逐项与模式内全选仍按缓存门控。
- 修正 axial/cutaway/radial 三个联合 GIF 依赖，静态覆盖全部 30 项 renderer。
- D 二维合并并封印全部自有原始证据，seed 与方向验证形成明确依赖；缺文件变 STALE，assess 拒绝，不隐式补算。
- thermal/cross 同 production 使用 analysis-source 锁，不同 source 可并行。
- 有效 artifact 迁移：A=0、B=24、D=0；已有 C 输出重新封印 12 项。最终目标 deep verify 全部通过。
- A 的 3 个源 manifest 已失效，按规则跳过：Q1 的 result1.xlsx 哈希失配，Q23/Q4 的旧 runtime input_manifest.json 哈希失配。四份当前 Excel 另经冻结全精度参考 readback 全部 PASS，预置 Excel 不冒充 A 缓存。
- Q3=57.6215 h，Q4=51.1824 h。旧版本目录及源数值结果保持。
- 用户当前 release_v5 README/TXT 作为修改基础，仅替换启动、路径、依赖及必要状态说明。

## 必要短检查

- 终端进度、GUI、目录/原始输入短测试：15 passed，含原终端进度 8 项。
- 先前相关选择性检查：21 passed；D 证据和成本补充回归 2 passed。
- 两版实际源码入口 6 个 smoke 均退出 0：终端 dry-run/runtime-check/verify，GUI backend verify/全选 dry-run，以及 GUI 启动扫描 122 项。
- 原始文件各 7 项 SHA256 一致；从独立发布布局重新解析后，输入 hash 和全部 NumPy 数组与仓库一致。
- 19 个受保护文件与改动前相同；数值核心在仓库、终端、GUI 三方 SHA256 一致。源码副本与当前仓库一致，package_manifest 逐文件核对通过。
- 两版 logs 为空，终端 work 为空；最终目录无 EXE、spec、PyInstaller、测试/构建工具或 pyc 缓存。
- 一条开发测试环境 warning：pytest 不能写已有 work/studies/pytest_cache，测试本身通过；不是发布包运行或数值失败。
- 本轮检查不求解 PDE、不重画 GIF。D 是按需数值复核；没有把缓存迁移视为 D 全量 PASS。

## 数值核心三方 SHA256

下列每项在仓库、终端版与 GUI 版一致：

| 模块 | SHA256 |
|---|---|
| materials.py | 83af1401abe6dc99073f619efa2a5406c8b8d56c34fb8043b72a369dad39cbdf |
| boundaries.py | 5b88490ad438f9831b84104cd53f983b8c6326c7bcdfbce3c884e9826b8d5905 |
| operators.py | 6c36fd3be577f379dde6aece12be7fce12a563c54cf5155c618dfd5b09b8ae43 |
| rk4.py | 71b9f6b50b0f6b6656a2e79920f8b77c8d65679a89e0b8419940e629262d8709 |
| sampling.py | b335f20108608c04b4ceb5510233e89d05718928d82c6712b204fa9e9cb8717b |
| inputs.py | a3d83290bd4d32a3e9ddaf74467d6215f9a0b3f030eca76a9dc96a9898c47a3a |
| events.py | d03bdfe9f32e669bd6d55cf9a4d095b5376e26004b9cd52ca3f05b89397743bb |
| geometry.py | 87abb0138f2fae6833e1455363f99da62398b72de924838e0bcd6c4d2a685519 |
| cases.py | 203d0c565a04798d623c3661dad7b5e76f6d6755b49185a1fe4f966ae87b31dd |
| stages.py | 69fe41afd196c95b26d76d5b669222991686ae6e65d106d12bd690487ac50b3f |
| table_solver.py | ecea4c9ac485f569b6a33491edf929377f4ca4def1d50ded70e0a23a0a2d7157 |

## 原始数据逐文件 SHA256

下列源文件与终端、GUI 各自副本一致：

| 发布版原始题目数据内路径 | SHA256 |
|---|---|
| A题.pdf | 052d8014bff5727c019b72e44fdffaf5c145ce04050dd938baaf3527db331736 |
| 附件1.xlsx | 7ef32870abeef420b89560b2530ff60dfe4255917805151d89988d0311af9dd7 |
| 附件2.xlsx | 5563acbfa4b4afb10cc6c03e2207e5369bf39da27576672aff14cc5c32e704af |
| 附件3/result1.xlsx | 23b261b295c1b787d000eebbca6521c37075107b6fcf78724f8d395ce1798ff4 |
| 附件3/result2.xlsx | 23b261b295c1b787d000eebbca6521c37075107b6fcf78724f8d395ce1798ff4 |
| 附件3/result3.xlsx | 07e4793d620a7f899804c0298d49a16a197960440fd47f8bb780c57ec27e2859 |
| 附件3/result4.xlsx | 86e9300ffa3d30c43de895ea6723da943e85b8740b137bcae5af7107f076eeac |

机器可读记录：`work/release_v5/final_source_audit/integrity.json`、`preparation.json`、`smoke.json`；发布包种子收据：GUI 的 `results/data/seed_manifest.json`。
