# V5 收尾开发验收记录

基线：`82dcd435a982a9fddd3ad24205be5ca9c72cdd94`。本记录用于开发验收，不是评委入口说明。

- 用户已实测终端完整 A，约 2.8 min；仅代表该次测试电脑，不是跨机器承诺。
- 读取原测试包成功记录：`[{"case": "q1", "status": "PASS", "drying_time_h": null}, {"case": "q4", "status": "PASS", "drying_time_h": 51.182399999999994}, {"case": "q23", "status": "PASS", "drying_time_h": 57.6215}]`。本轮未重新复算四表。
- 新终端进度只读取 table/stagepart status.json；以阶段时长 × nr³ 计算结构进度。求解未新增调用。
- ETA 只接受同机、同科学身份、兼容任务集合的成功历史；失败、停止、部分记录和缓存热跑耗时不作冷跑基准。首次运行用真实结构进展自校准；状态停更后保留百分比，观测过期回到校准。
- 并行剩余取运行任务最大剩余加待运行任务的保守串行成本；显示估计，不参与调度、事件或停止条件。
- TTY 每2秒原地刷新；重定向每6秒一行，无 ANSI/CR。
- 新进度单元测试：8 passed；包含单调/停更、stagepart匹配、成功缓存、首次校准、失败/停止、历史筛选和重定向。新增 ETA 未完整实测。
- 终端 EXE 在独立 smoke copy 执行 --verify、--runtime-check、--dry-run 均退出0；PDE solves=0。测试副本随后移除。
- GUI 延续上轮8项界面/缓存状态轻量检查记录；当前人工 A/B/C 测试仍由用户进行，本轮不追加完整验收结论。
- GUI ETA/progress calibration display has a known display-only limitation in the current V5 test build; it does not alter numerical computation or artifact completion. 本轮不修改。
- D 未全量运行，不声称 PASS；不跑 Developer Full Audit、thermal 18、mass 12 或完整二维验证。
- 正在测试的 release_v5 静态文件、GUI 源码/EXE/依赖和数值核心全部保持原字节；未启动或停止 GUI。
- 原始字节核对1012个受保护文件全部相同；数值核心与 HEAD 归一化换行后相同（Git LF/工作树 CRLF）。
- 洁净交付：`release_v5_submit/A题_药材烘干模型/`。两包及顶层 results/work/logs 均不存在；两套物理文件独立。最终目录没有运行测试。
- 提交副本 GUI 除 README.md/说明.txt/重新生成的包清单外，805个静态文件与原测试包相同。

## GUI / 数值源文件：修改前后 SHA256

| 文件 | 修改前 SHA256 | 修改后 SHA256 |
|---|---|---|
| judge_gui.py | 113836b249d5b514af104542ef8081433321c0e0fd7be046044d7100bd021989 | 113836b249d5b514af104542ef8081433321c0e0fd7be046044d7100bd021989 |
| src/drying/judge_progress.py | 8df08dd60878f0385bb053aa5130c219e9ce3e80b635a14dbd98fbbf24e32a34 | 8df08dd60878f0385bb053aa5130c219e9ce3e80b635a14dbd98fbbf24e32a34 |
| src/drying/gui/catalog_panel.py | 87e5bf49f080576bdc73e68bfadb31e1543b3b22d5280b0af53f2bd78afdcb28 | 87e5bf49f080576bdc73e68bfadb31e1543b3b22d5280b0af53f2bd78afdcb28 |
| src/drying/gui/controller.py | 276d6f7684a86c9dad164c2c09c376feecca812fcb4a34f3bbd138c65826859a | 276d6f7684a86c9dad164c2c09c376feecca812fcb4a34f3bbd138c65826859a |
| src/drying/gui/facts.py | 4f617e5d0741fc0eefe347a2cf580a65f114fc3c889a7500f3c386c36e738e53 | 4f617e5d0741fc0eefe347a2cf580a65f114fc3c889a7500f3c386c36e738e53 |
| src/drying/gui/file_actions.py | 615fdb3d5b6f3879b693bad94499e4bab8eb45124ae5df8dadcb3ee3084daa96 | 615fdb3d5b6f3879b693bad94499e4bab8eb45124ae5df8dadcb3ee3084daa96 |
| src/drying/gui/judge_window.py | 79f19fbc741e803297053baeca7e8c7bcb4ec028b65369cdd30d2e1ca6a636fc | 79f19fbc741e803297053baeca7e8c7bcb4ec028b65369cdd30d2e1ca6a636fc |
| src/drying/gui/main_window.py | e7c62fc5effb79bd50471759db2bdbfba2c0036ec3186ec84fec4e961a0f30c8 | e7c62fc5effb79bd50471759db2bdbfba2c0036ec3186ec84fec4e961a0f30c8 |
| src/drying/gui/progress.py | 99dcaf16e1e970df2c0d190f9c261f60358ba3d31e27e008c8d0b5c997ecd07f | 99dcaf16e1e970df2c0d190f9c261f60358ba3d31e27e008c8d0b5c997ecd07f |
| src/drying/gui/task_runner.py | 33ef53948da136a4210fd6472a2708eafb7de6f10694fa3dbb6044a508622f58 | 33ef53948da136a4210fd6472a2708eafb7de6f10694fa3dbb6044a508622f58 |
| src/drying/gui/validation_status.py | a65310e85fed6a71a306e73e22349e5b0af7dc5ab7351aded4147ccb29088c2f | a65310e85fed6a71a306e73e22349e5b0af7dc5ab7351aded4147ccb29088c2f |
| src/drying/gui/__init__.py | 27198179063a1daa989498ba55f23375f6bf7e76de85014c7d73843e8442b99a | 27198179063a1daa989498ba55f23375f6bf7e76de85014c7d73843e8442b99a |
| configs/task_catalog.json | e834df8e78c50f1ea2022cf4ea88fdfd3d73359b45edf20df53abe948e542177 | e834df8e78c50f1ea2022cf4ea88fdfd3d73359b45edf20df53abe948e542177 |
| configs/plot_catalog.json | 124fafc914eb0a3c8e587965a4d70f09089d49b8b0c3dd799b984ea69cfdefa1 | 124fafc914eb0a3c8e587965a4d70f09089d49b8b0c3dd799b984ea69cfdefa1 |
| configs/validation_catalog.json | fa44d6024e35e5c79d5d4a6da09256f0fc8a2e9977325cd84bf20cf45a3b2d55 | fa44d6024e35e5c79d5d4a6da09256f0fc8a2e9977325cd84bf20cf45a3b2d55 |
| release_v5/A题_药材烘干模型/02_完整功能_GUI版/药材烘干模型_GUI.exe | 1b0c7284cef53a341a2f463c664fb4df662abd5c72e12df0375c0154776d2acb | 1b0c7284cef53a341a2f463c664fb4df662abd5c72e12df0375c0154776d2acb |

## 提交包完整性

| 文件 | SHA256 |
|---|---|
| 01_四表正式数据_终端版\药材烘干模型_四表正式数据.exe | 1f16cc266d3dc85ba5665d1dbabb6869fcad745887924f807513f91b7b37e17a |
| 02_完整功能_GUI版\药材烘干模型_GUI.exe | 1b0c7284cef53a341a2f463c664fb4df662abd5c72e12df0375c0154776d2acb |
| 01_四表正式数据_终端版\package_manifest.json | e2a4088edadd167f3445f5ebf4785160d59017e8e92885ac478aa199ff44b09d |
| 02_完整功能_GUI版\package_manifest.json | a9988c91215b39345b5a5971a4bf9bf60b40c6550bc356e3800213ac9ddffa0c |
| release_manifest.json | 19c703198ad984d55fac352358679e8debbba4ec164f66fc340dfa48b9f89ad6 |

数值核心聚合 SHA256（按模块名排序的 SHA256 JSON）：`285aa8c29d07f8a9e92a685186b234791504f0a232215950dcf458baba102777`。

完整逐文件前后记录：`work/release_v5/finalize_audit/integrity.json`。只读 smoke 输出：`terminal_smoke.json`；洁净清单：`finalizer.json`。

本次文档更新：提交副本终端 README.md/说明.txt、GUI README.md/说明.txt（仅文字）、顶层请评委先看.md/.txt，以及仓库 README。评委文档按用户补充不写 D 未实测/未验收。
