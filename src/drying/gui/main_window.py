"""PySide6 judge-oriented desktop interface."""
from datetime import datetime
from pathlib import Path
import subprocess

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox,
    QFileSystemModel, QHBoxLayout, QLabel, QListWidget, QMainWindow, QMessageBox,
    QPushButton, QRadioButton, QSplitter, QStackedWidget, QTabWidget, QTableWidget,
    QTableWidgetItem, QTextEdit, QTreeView, QVBoxLayout, QWidget)

from .controller import CommandBuilder, P4_FIXED_NOTICE, SUPPLEMENTAL_NOTICE, result_catalog
from .facts import load_facts, official_cards
from .file_actions import open_path
from .progress import TaskProgress
from .task_runner import TaskRunner
from .validation_status import TWO_D_DETAIL, validation_rows


class MainWindow(QMainWindow):
    PAGE_NAMES = ("首页 / 正式结果", "快速验证", "正式计算", "创新与模型分析", "结果浏览", "模型说明", "运行日志")

    def __init__(self, root: Path):
        super().__init__(); self.root=Path(root); self.builder=CommandBuilder(root)
        self.runner=TaskRunner(root,self); self.progress=TaskProgress(); self.facts=load_facts(root)
        self.runner.line_ready.connect(self._log); self.runner.finished.connect(self._done)
        self.setWindowTitle("药材烘干模型计算程序 · PySide6"); self.resize(1280,820)
        shell=QWidget(); row=QHBoxLayout(shell); self.nav=QListWidget(); self.nav.addItems(self.PAGE_NAMES); self.nav.setMaximumWidth(210)
        self.pages=QStackedWidget(); row.addWidget(self.nav); row.addWidget(self.pages,1); self.setCentralWidget(shell)
        for factory in (self._home,self._validation,self._compute,self._studies,self._results,self._model,self._logs): self.pages.addWidget(factory())
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex); self.nav.setCurrentRow(0)
        self.statusBar().showMessage(self.facts.message)

    def _page(self,title,subtitle=""):
        page=QWidget(); layout=QVBoxLayout(page); heading=QLabel(f"<h1>{title}</h1>"); layout.addWidget(heading)
        if subtitle: label=QLabel(subtitle); label.setWordWrap(True); layout.addWidget(label)
        return page,layout

    def _open_button(self,text,path):
        button=QPushButton(text); button.clicked.connect(lambda: self._open(path)); return button

    def _open(self,path):
        try: open_path(path); self.statusBar().showMessage(f"已打开：{Path(path).name}")
        except Exception as exc: self.statusBar().showMessage(str(exc)); self._log(str(exc))

    def _home(self):
        p,l=self._page("2026 全国大学生数学建模竞赛 A题","正式模型：M00 一维径向模型　　二维辅助验收：PASS")
        l.addWidget(QLabel(self.facts.message))
        if self.facts.ready:
            for title,body in official_cards(self.facts.data): l.addWidget(QLabel(f"<b>{title}</b><br>{body.replace(chr(10),'<br>')}"))
        for text,path in [("打开正式结果文件夹",self.root/"results"),("打开创新图",self.root/"results/studies/figures"),("打开 paper_facts",self.root/"results/paper_facts.md")]: l.addWidget(self._open_button(text,path))
        l.addStretch(); return p

    def _validation(self):
        p,l=self._page("快速验证","只读检查已有状态；不积分 PDE、不修改正式结果或数值缓存。")
        self.validation_table=QTableWidget(0,3); self.validation_table.setHorizontalHeaderLabels(("项目","状态","说明")); self.validation_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        l.addWidget(self.validation_table); detail=QLabel(TWO_D_DETAIL); detail.setWordWrap(True); l.addWidget(detail)
        b=QPushButton("运行快速验证"); b.clicked.connect(lambda:self._launch(self.builder.quick_validation(),"validation")); l.addWidget(b); self.refresh_validation(); return p

    def refresh_validation(self):
        rows=validation_rows(self.root); self.validation_table.setRowCount(len(rows))
        for r,row in enumerate(rows):
            for c,value in enumerate(row): self.validation_table.setItem(r,c,QTableWidgetItem(str(value)))
        self.validation_table.resizeColumnsToContents()

    def _compute(self):
        p,l=self._page("正式计算","正式模型 M00；Q2 与 Q3 共享 q23 轨迹，数值配置保持冻结。")
        self.cases={}; group=QWidget(); gl=QVBoxLayout(group)
        for text,value in (("Q1","q1"),("Q2/Q3（共享 q23）","q23"),("Q4","q4"),("全部","all")):
            radio=QRadioButton(text); self.cases[value]=radio; gl.addWidget(radio)
        self.cases["q1"].setChecked(True); l.addWidget(group); b=QPushButton("开始计算"); b.clicked.connect(self._official); l.addWidget(b); l.addStretch(); return p

    def _official(self):
        case=next(key for key,value in self.cases.items() if value.isChecked())
        if QMessageBox.question(self,"确认正式计算","重新运行所选正式 M00 轨迹？数值参数保持冻结。") == QMessageBox.Yes: self._launch([self.builder.official(case)],"official")

    def _studies(self):
        p,l=self._page("创新与模型分析"); tabs=QTabWidget(); l.addWidget(tabs)
        def tab(name): w=QWidget(); w.setLayout(QVBoxLayout()); tabs.addTab(w,name); return w.layout()
        x=tab("二维端面与降维"); d=QLabel(TWO_D_DETAIL); d.setWordWrap(True); x.addWidget(d); x.addWidget(self._open_button("查看二维对比图",self.root/"results/q1/q1_1d_2d_compare.png"))
        x=tab("几何—物性交叉"); x.addWidget(QLabel("P3 + 收缩可独立运行或从缓存恢复。\n"+P4_FIXED_NOTICE)); x.addWidget(self._open_button("打开交叉分析图",self.root/"results/studies/figures/05_geometry_property_cross.png")); b=QPushButton("运行/恢复 P3+收缩"); b.clicked.connect(lambda:self._launch([self.builder.geometry()],"geometry")); x.addWidget(b)
        x=tab("补充热模型"); x.addWidget(QLabel(SUPPLEMENTAL_NOTICE)); self.modes={m:QCheckBox(m) for m in ("M10","M01","M11")}; self.study_cases={c:QCheckBox(t) for c,t in (("q1","Q1"),("q23","Q2/Q3"),("q4","Q4"))}
        for box in (*self.modes.values(),*self.study_cases.values()): x.addWidget(box)
        b=QPushButton("运行所选 M10/M01/M11"); b.clicked.connect(self._thermal); x.addWidget(b)
        x=tab("水质量守恒"); x.addWidget(self._open_button("查看守恒摘要",self.root/"work/validation/mass_balance/summary.json")); b=QPushButton("重新审计水质量守恒"); b.clicked.connect(lambda:self._launch([self.builder.mass_balance()],"mass_balance")); x.addWidget(b)
        return p

    def _thermal(self):
        try: commands=self.builder.thermal([k for k,v in self.modes.items() if v.isChecked()],[k for k,v in self.study_cases.items() if v.isChecked()]); self._launch(commands,"thermal")
        except ValueError as exc: self.statusBar().showMessage(str(exc))

    def _results(self):
        p,l=self._page("结果浏览","双击用系统默认程序打开；浏览不会触发求解。")
        self.category=QComboBox(); self.category.addItems(("正式结果","Q1","Q2","Q3","Q4","动画","创新图","热模型","表格","验证报告")); self.result_list=QListWidget(); l.addWidget(self.category); l.addWidget(self.result_list)
        self.category.currentTextChanged.connect(self._refresh_results); self.result_list.itemDoubleClicked.connect(lambda item:self._open(self.root/item.text())); self._refresh_results(); return p

    def _refresh_results(self,*_):
        self.result_list.clear(); self.result_list.addItems([p.relative_to(self.root).as_posix() for p in result_catalog(self.root,self.category.currentText())])

    def _model(self):
        p,l=self._page("模型说明","一维径向有限体积 + RK4；Q4 采用随体归一化坐标与均匀收缩。")
        for text,path in (("打开完整模型说明",self.root/"results/overview.md"),("打开 README",self.root/"README.md"),("打开 paper_facts",self.root/"results/paper_facts.md")): l.addWidget(self._open_button(text,path))
        d=QLabel(TWO_D_DETAIL); d.setWordWrap(True); l.addWidget(d); l.addStretch(); return p

    def _logs(self):
        p,l=self._page("运行日志","stdout / stderr 实时合并显示。安全停止会在保存点留下可恢复状态。")
        self.command_label=QLabel("当前命令：无"); self.return_label=QLabel("返回码：—"); self.log=QTextEdit(); self.log.setReadOnly(True); l.addWidget(self.command_label); l.addWidget(self.return_label); l.addWidget(self.log)
        row=QHBoxLayout(); stop=QPushButton("安全停止"); stop.clicked.connect(self._stop); resume=QPushButton("恢复上次任务"); resume.clicked.connect(self._resume); row.addWidget(stop); row.addWidget(resume); l.addLayout(row); return p

    def _launch(self,commands,kind):
        if self.runner.busy or self.progress.pending: self.statusBar().showMessage("已有计算任务正在运行"); return
        self.progress.begin(commands,kind); self.nav.setCurrentRow(6); self._next()

    def _next(self):
        command=self.progress.take_next()
        if command is None: return
        shown=subprocess.list2cmdline(command); self.command_label.setText("当前命令："+shown); self.return_label.setText("返回码：运行中"); self._log(f"[{datetime.now():%F %T}] {shown}"); self.runner.start(command,self.progress.kind)

    def _done(self,record):
        self.return_label.setText(f"返回码：{record.returncode}"); self.statusBar().showMessage("任务完成" if record.status=="PASS" else "任务失败，请查看日志")
        if record.status=="PASS": self.refresh_validation(); self._next()
        else: self.progress.cancel_remaining()

    def _stop(self):
        if not self.runner.busy: self.statusBar().showMessage("当前没有运行中的任务"); return
        self.runner.request_stop(self.builder.stop_marker(self.progress.kind=="official")); self.progress.cancel_remaining()

    def _resume(self):
        if self.runner.busy: return
        try: self.progress.resume(); self._next()
        except ValueError as exc: self.statusBar().showMessage(str(exc))

    def _log(self,line):
        self.log.append(str(line))


def main():
    app=QApplication.instance() or QApplication([]); window=MainWindow(Path(__file__).resolve().parents[3]); window.show(); return app.exec()
