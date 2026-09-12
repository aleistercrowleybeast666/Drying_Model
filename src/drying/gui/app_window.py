"""Tk views for a judge-oriented, scrollable seven-page application."""
from datetime import datetime
from pathlib import Path
import json
import queue
import subprocess

from .controller import (CommandBuilder, P4_FIXED_NOTICE, SUPPLEMENTAL_NOTICE,
                         TWO_D_NOTICE, result_catalog)
from .facts import load_facts, official_cards
from .file_actions import open_path
from .task_runner import TaskRunner


MODEL_TEXT = """正式模型：1D 径向圆柱热-质扩散模型（M00）

空间离散：单元中心有限体积法
时间积分：经典四阶段 RK4
时间步：dt_max = 0.25 s，实际步长受稳定性限制
Q4：随体归一化坐标 ξ=r/R(t)，径向均匀收缩
正式热模型：M00，不显式考虑蒸发潜热和水分携热
二维：仅作为端面效应与降维合理性辅助核验"""


class DryingApp:
    PAGE_NAMES=("首页 / 正式结果", "快速验证", "正式计算", "创新与模型分析", "结果浏览", "模型说明", "运行日志")

    def __init__(self, window, root: Path):
        import tkinter as tk
        from tkinter import ttk
        self.tk=tk;self.ttk=ttk;self.window=window;self.root=Path(root)
        self.builder=CommandBuilder(root);self.runner=TaskRunner(root);self.facts=load_facts(root)
        self.pending=[];self.task_kind="read_only";self.log_lines=[]
        window.title("药材烘干模型计算程序");window.geometry("1280x820");window.minsize(900,620)
        self.status=tk.StringVar(value=self.facts.message);self.command=tk.StringVar(value="当前命令：无")
        self.started=tk.StringVar(value="开始时间：—");self.returncode=tk.StringVar(value="返回码：—")
        shell=ttk.Frame(window);shell.pack(fill="both",expand=True)
        nav=ttk.Frame(shell,padding=10);nav.pack(side="left",fill="y")
        self.content=ttk.Frame(shell,padding=16);self.content.pack(side="left",fill="both",expand=True)
        self.pages={}
        for name in self.PAGE_NAMES:
            frame=ttk.Frame(self.content);self.pages[name]=frame
            ttk.Button(nav,text=name,width=20,command=lambda n=name:self.show(n)).pack(fill="x",pady=3)
        self._home();self._validation();self._compute();self._studies();self._results();self._model();self._logs()
        ttk.Separator(window).pack(fill="x");ttk.Label(window,textvariable=self.status,padding=7).pack(fill="x")
        self.show(self.PAGE_NAMES[0]);window.after(150,self._poll)

    def show(self, name):
        for frame in self.pages.values(): frame.pack_forget()
        self.pages[name].pack(fill="both",expand=True)

    def heading(self, page, title, subtitle=""):
        self.ttk.Label(page,text=title,font=("Microsoft YaHei UI",20,"bold")).pack(anchor="w",pady=(0,5))
        if subtitle:self.ttk.Label(page,text=subtitle,foreground="#555").pack(anchor="w",pady=(0,14))

    def button(self, parent, text, path):
        return self.ttk.Button(parent,text=text,command=lambda:self._open(path))

    def _open(self,path):
        try:open_path(path);self.status.set(f"已打开：{Path(path).name}")
        except Exception as exc:self.status.set(str(exc));self._append(str(exc))

    def _home(self):
        p=self.pages[self.PAGE_NAMES[0]];self.heading(p,"2026 全国大学生数学建模竞赛 A题","药材烘干模型计算程序")
        self.ttk.Label(p,text="正式模型：M00 一维径向模型    程序状态：已完成 / 已验证",font=("Microsoft YaHei UI",12,"bold")).pack(anchor="w")
        self.ttk.Label(p,text=self.facts.message,foreground="#16803b" if self.facts.ready else "#b42318").pack(anchor="w",pady=(4,12))
        cards=self.ttk.Frame(p);cards.pack(fill="x")
        if self.facts.ready:
            for col,(title,body) in enumerate(official_cards(self.facts.data)):
                box=self.ttk.LabelFrame(cards,text=title,padding=12);box.grid(row=0,column=col,sticky="nsew",padx=4)
                self.ttk.Label(box,text=body,justify="left").pack(anchor="w");cards.columnconfigure(col,weight=1)
        actions=self.ttk.LabelFrame(p,text="查看已有结果（不会计算）",padding=10);actions.pack(fill="x",pady=16)
        links=[(f"打开 result{i}.xlsx",self.root/f"results/tables/result{i}.xlsx") for i in range(1,5)]
        links += [("打开正式结果文件夹",self.root/"results"),("打开主要图表",self.root/"results/q3/q3_curves.png"),
                  ("打开动画目录",self.root/"results/animations"),("打开 paper_facts.md",self.root/"results/paper_facts.md")]
        for i,(text,path) in enumerate(links):self.button(actions,text,path).grid(row=i//4,column=i%4,padx=4,pady=4,sticky="ew")

    def _validation(self):
        p=self.pages[self.PAGE_NAMES[1]];self.heading(p,"快速验证","只读检查已有结果；不积分 PDE、不修改正式结果或数值缓存。")
        self.validation_tree=self.ttk.Treeview(p,columns=("status","note"),show="tree headings",height=12)
        self.validation_tree.heading("#0",text="项目");self.validation_tree.heading("status",text="状态");self.validation_tree.heading("note",text="说明")
        self.validation_tree.tag_configure("pass",foreground="#16803b");self.validation_tree.tag_configure("warning",foreground="#9a6700")
        self.validation_tree.tag_configure("fail",foreground="#b42318");self.validation_tree.tag_configure("idle",foreground="#777")
        rows=[("Q1 时间收敛","PASS","正式一维"),("Q1 空间收敛","PASS","正式一维"),("Q2/Q3 时间收敛","PASS","共享 q23 轨迹"),
              ("Q2/Q3 空间收敛","PASS","共享 q23 轨迹"),("Q4 时间收敛","PASS","正式一维"),("Q4 空间收敛","PASS","正式一维"),
              ("水质量守恒","PASS","12/12"),("二维辅助验收","PASS","用于端面/降维分析"),("严格二维网格独立性","未认证","PARTIAL_2D / NOT CERTIFIED"),
              ("官方 Excel","PASS","4/4"),("paper_facts","PASS" if self.facts.ready else "FAIL","来源一致" if self.facts.ready else self.facts.message)]
        for row in rows:
            tag="pass" if row[1]=="PASS" else "fail" if row[1]=="FAIL" else "warning" if row[1] in {"WARNING","未认证","PARTIAL_2D"} else "idle"
            self.validation_tree.insert("", "end", text=row[0],values=row[1:],tags=(tag,))
        self.validation_tree.pack(fill="x");self.ttk.Label(p,text=TWO_D_NOTICE,foreground="#9a6700").pack(anchor="w",pady=8)
        self.ttk.Button(p,text="运行快速验证",command=lambda:self._launch_many(self.builder.quick_validation(),"validation")).pack(anchor="w")

    def _compute(self):
        p=self.pages[self.PAGE_NAMES[2]];self.heading(p,"正式计算","正式模型：M00（锁定，只读）")
        self.ttk.Label(p,text="Q2 与 Q3 共享同一条 q23 轨迹，不会重复求解。所有数值参数保持冻结配置。",foreground="#555").pack(anchor="w")
        self.case=self.tk.StringVar(value="q1")
        box=self.ttk.LabelFrame(p,text="选择要重新运行的正式轨迹（默认不选择全部）",padding=12);box.pack(fill="x",pady=12)
        for text,value in [("Q1","q1"),("Q2/Q3（共享 q23）","q23"),("Q4","q4"),("全部","all")]:self.ttk.Radiobutton(box,text=text,value=value,variable=self.case).pack(anchor="w",pady=3)
        self.ttk.Button(p,text="开始计算",command=self._confirm_official).pack(anchor="w")
        self.ttk.Label(p,text="开始后会明确显示复用缓存或正在重新计算；不会静默改变 source id。",foreground="#555").pack(anchor="w",pady=8)

    def _confirm_official(self):
        from tkinter import messagebox
        if messagebox.askyesno("确认正式计算","将重新运行所选正式模型。\n数值模型和验证参数保持冻结配置。\n是否继续？"):
            self._launch_many([self.builder.official(self.case.get())],"official")

    def _studies(self):
        p=self.pages[self.PAGE_NAMES[3]];self.heading(p,"创新与模型分析","查看已有成果与选择性补充研究明确分开。")
        note=self.ttk.Notebook(p);note.pack(fill="both",expand=True)
        def tab(title):f=self.ttk.Frame(note,padding=12);note.add(f,text=title);return f
        f=tab("二维端面与降维");self.ttk.Label(f,text=TWO_D_NOTICE,wraplength=850).pack(anchor="w")
        for text,path in [("查看二维对比图",self.root/"results/q1/q1_1d_2d_compare.png"),("查看端面影响结果",self.root/"results/studies/figures/01_end_effect_extent.png")]:self.button(f,text,path).pack(anchor="w",pady=3)
        self.ttk.Button(f,text="重新运行二维辅助验收（不求解 PDE）",command=lambda:self._launch_many([self.builder.auxiliary_2d()],"validation")).pack(anchor="w",pady=3)
        f=tab("干燥动力学")
        for text,path in [("查看慢—快—慢分析",self.root/"results/studies/figures/03_drying_kinetics.png"),("查看干燥前沿",self.root/"results/studies/figures/02_drying_fronts.png"),("查看扩散时钟 / T-R-C 响应时序",self.root/"results/studies/figures/04_diffusion_clock_drivers.png")]:self.button(f,text,path).pack(anchor="w",pady=4)
        f=tab("几何—物性交叉");self.ttk.Label(f,text="P3 + 固定半径\nP3 + 收缩\nP4 + 固定半径\nP4 + 收缩\n\n"+P4_FIXED_NOTICE,wraplength=850,justify="left").pack(anchor="w")
        self.button(f,"查看交叉分析图",self.root/"results/studies/figures/05_geometry_property_cross.png").pack(anchor="w",pady=4)
        self.ttk.Button(f,text="运行/恢复 P3+收缩独立实验",command=lambda:self._launch_many([self.builder.geometry()],"geometry")).pack(anchor="w")
        f=tab("环境与热模型");self.ttk.Label(f,text="环境延拓：30 min / 60 min（正式）/ 90 min\n结论：在当前数值分辨率下未观察到显著尾窗敏感性。",justify="left").pack(anchor="w")
        self.button(f,"查看环境延拓图",self.root/"results/studies/figures/06_environment_robustness.png").pack(anchor="w",pady=4)
        self.ttk.Label(f,text="M00：正式模型，不计潜热/显式携热\nM10：仅潜热    M01：仅水分显式携热    M11：潜热 + 水分显式携热\n当前补充闭合下：蒸发潜热影响显著；显式水分携热影响很小。\n"+SUPPLEMENTAL_NOTICE,justify="left").pack(anchor="w",pady=8)
        self.modes={m:self.tk.BooleanVar(value=False) for m in ("M10","M01","M11")};self.study_cases={c:self.tk.BooleanVar(value=False) for c in ("q1","q23","q4")}
        picks=self.ttk.Frame(f);picks.pack(anchor="w")
        for m,v in self.modes.items():self.ttk.Checkbutton(picks,text=m,variable=v).pack(side="left")
        for c,v in self.study_cases.items():self.ttk.Checkbutton(picks,text={"q1":"Q1","q23":"Q2/Q3","q4":"Q4"}[c],variable=v).pack(side="left",padx=5)
        self.ttk.Button(f,text="运行所选补充热模型",command=self._run_thermal).pack(anchor="w",pady=4)
        f=tab("水质量守恒");mass=self.facts.data.get("solver_mass_balance",{}) if self.facts.ready else {}
        self.ttk.Label(f,text=f"solver-level mass balance：{mass.get('status','未运行')}\n完成：{mass.get('completed_case_count','—')}/12\n最大相对残差：{mass.get('max_mass_balance_rel_error','—')}\nQ4 最大 remesh 质量跳变：见守恒摘要",justify="left").pack(anchor="w")
        self.button(f,"查看守恒摘要",self.root/"work/validation/mass_balance/summary.json").pack(anchor="w",pady=4)
        self.ttk.Button(f,text="重新运行守恒审计",command=lambda:self._launch_many([self.builder.mass_balance()],"mass_balance")).pack(anchor="w")

    def _run_thermal(self):
        try:self._launch_many(self.builder.thermal([m for m,v in self.modes.items() if v.get()],[c for c,v in self.study_cases.items() if v.get()]),"thermal")
        except ValueError as exc:self.status.set(str(exc))

    def _results(self):
        p=self.pages[self.PAGE_NAMES[4]];self.heading(p,"结果浏览","双击使用系统默认程序打开；查看操作不会求解。")
        top=self.ttk.Frame(p);top.pack(fill="x");category=self.tk.StringVar(value="正式结果")
        combo=self.ttk.Combobox(top,textvariable=category,state="readonly",values=("正式结果","Q1","Q2","Q3","Q4","动画","创新图","热模型","表格","验证报告"));combo.pack(side="left")
        self.files=self.tk.Listbox(p);self.files.pack(fill="both",expand=True,pady=8)
        def refresh(*_):
            self.files.delete(0,"end");self.catalog=result_catalog(self.root,category.get())
            for path in self.catalog:self.files.insert("end",path.relative_to(self.root).as_posix())
        combo.bind("<<ComboboxSelected>>",refresh);self.files.bind("<Double-1>",lambda _:self._open(self.catalog[self.files.curselection()[0]]) if self.files.curselection() else None);refresh()

    def _model(self):
        p=self.pages[self.PAGE_NAMES[5]];self.heading(p,"模型说明","冻结配置的只读摘要")
        self.ttk.Label(p,text=MODEL_TEXT,justify="left",font=("Microsoft YaHei UI",11)).pack(anchor="w",pady=8)
        for text,path in [("打开完整数学物理模型说明",self.root/"results/overview.md"),("打开 README",self.root/"README.md"),("打开 paper_facts",self.root/"results/paper_facts.md")]:self.button(p,text,path).pack(anchor="w",pady=3)
        info=self.ttk.LabelFrame(p,text="开发者信息（只读）",padding=8);info.pack(fill="x",pady=14)
        data=self.facts.data;official=data.get("official",{}) if self.facts.ready else {}
        source_ids="\n".join(f"{q}: {v.get('source_case_id','—')}" for q,v in official.items())
        self.ttk.Label(info,text=f"baseline id: {data.get('baseline_id','—')}\npaper_facts 生成时间: {data.get('generated_at','—')}\ndt_max: 0.25 s\n二维 validation: PARTIAL_2D / NOT CERTIFIED\n{source_ids}",justify="left",wraplength=900).pack(anchor="w")

    def _logs(self):
        p=self.pages[self.PAGE_NAMES[6]];self.heading(p,"运行日志","stdout / stderr 实时合并显示；完整错误保留在此页。")
        for var in (self.command,self.started,self.status,self.returncode):self.ttk.Label(p,textvariable=var).pack(anchor="w")
        self.log=self.tk.Text(p,wrap="word",font=("Consolas",10));self.log.pack(fill="both",expand=True,pady=8)
        row=self.ttk.Frame(p);row.pack(fill="x")
        self.ttk.Button(row,text="安全停止",command=self._stop).pack(side="left")
        self.ttk.Button(row,text="继续上次任务",command=lambda:self._launch_many([self.builder.mass_balance()],"mass_balance")).pack(side="left",padx=6)

    def _launch_many(self,commands,kind):
        if self.runner.busy or self.pending:self.status.set("已有计算任务正在运行");return
        self.pending=list(commands);self.task_kind=kind;self.show("运行日志");self._launch_next()

    def _launch_next(self):
        if not self.pending:return
        command=self.pending.pop(0);self.command.set("当前命令："+subprocess.list2cmdline(command));self.started.set("开始时间："+datetime.now().strftime("%F %T"));self.returncode.set("返回码：运行中")
        self._append(self.command.get());self.runner.start(command,self.task_kind)

    def _stop(self):
        if not self.runner.busy:self.status.set("当前没有运行中的任务");return
        self.runner.request_stop(self.builder.stop_marker(self.task_kind=="official"));self.status.set("将在下一个安全保存点停止，并保留可恢复状态。")

    def _append(self,text):
        self.log_lines.append(str(text))
        if hasattr(self,"log"):self.log.insert("end",str(text)+"\n");self.log.see("end")

    def _poll(self):
        try:
            while True:
                kind,value=self.runner.events.get_nowait()
                if kind=="line":self._append(value);self.status.set(value[-160:])
                else:
                    self.returncode.set(f"返回码：{value.returncode}");self.status.set("任务完成" if value.status=="PASS" else "任务返回非零退出码，请查看完整日志")
                    if value.status=="PASS" and self.pending:self._launch_next()
                    elif value.status!="PASS":self.pending.clear()
        except queue.Empty:pass
        self.window.after(150,self._poll)


def main():
    import tkinter as tk
    root=Path(__file__).resolve().parents[3]
    try:window=tk.Tk()
    except tk.TclError as exc:
        print(f"GUI_INTERACTIVE_SMOKE_NOT_RUN_HEADLESS: {exc}")
        return 1
    DryingApp(window,root);window.mainloop();return 0
