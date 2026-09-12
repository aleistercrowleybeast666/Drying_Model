"""PySide6 judge interface; all computation remains in repository CLIs."""
from pathlib import Path
import subprocess
from types import MethodType

from .controller import CommandBuilder, P4_FIXED_NOTICE, SUPPLEMENTAL_NOTICE, result_catalog
from .facts import load_facts, official_cards
from .file_actions import open_path
from .progress import ProgressState, parse_progress
from .validation_status import TWO_D_DETAIL, apply_checker_result, auxiliary_text, evidence_rows

PAGE_NAMES=("首页 / 正式结果","快速验证","正式计算","创新与模型分析","结果浏览","模型说明","运行日志")


def _qt():
    from PySide6 import QtCore,QtWidgets
    return QtCore,QtWidgets


class MainWindow:
    def __new__(cls,*args,**kwargs):
        QtCore,QtWidgets=_qt()
        class Window(QtWidgets.QMainWindow):pass
        obj=Window()
        for name in dir(cls):
            if name.startswith("_") and callable(getattr(cls,name)) and name not in {"__new__"}:
                setattr(obj,name,MethodType(getattr(cls,name),obj))
        obj._init(*args,**kwargs);return obj

    @staticmethod
    def _init(self,root):
        QtCore,Q=_qt();from .task_runner import TaskRunner
        self.root=Path(root);self.builder=CommandBuilder(root);self.facts=load_facts(root);self.rows=evidence_rows(root);self.progress_state=ProgressState();self.task_kind=""
        self.setWindowTitle("药材烘干模型计算程序");self.resize(1280,820);self.setMinimumSize(900,620)
        central=Q.QWidget();self.setCentralWidget(central);outer=Q.QVBoxLayout(central);body=Q.QHBoxLayout();outer.addLayout(body,1)
        self.nav=Q.QListWidget();self.nav.addItems(PAGE_NAMES);self.nav.setFixedWidth(190);body.addWidget(self.nav)
        self.stack=Q.QStackedWidget();body.addWidget(self.stack,1);self.pages={}
        for name in PAGE_NAMES:self.pages[name]=Q.QWidget();self.stack.addWidget(self.pages[name])
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self._build_home(self,Q);self._build_validation(self,Q);self._build_compute(self,Q);self._build_studies(self,Q);self._build_results(self,Q);self._build_model(self,Q);self._build_logs(self,Q)
        bar=Q.QFrame();grid=Q.QGridLayout(bar);self.task_label=Q.QLabel("任务名称：无");self.phase_label=Q.QLabel("当前阶段：空闲");self.counter=Q.QLabel("0 / 0");self.progress=Q.QProgressBar();self.stop=Q.QPushButton("安全停止");self.show_log=Q.QPushButton("查看日志")
        grid.addWidget(self.task_label,0,0);grid.addWidget(self.phase_label,0,1);grid.addWidget(self.counter,0,2);grid.addWidget(self.progress,1,0,1,3);grid.addWidget(self.stop,0,3,2,1);grid.addWidget(self.show_log,0,4,2,1);outer.addWidget(bar)
        self.stop.clicked.connect(lambda:self._safe_stop(self));self.show_log.clicked.connect(lambda:self.nav.setCurrentRow(6))
        self.runner=TaskRunner(root,self);self.runner.on_output=lambda stream,text:self._output(self,stream,text);self.runner.on_step=lambda cmd,code,left:self._step(self,cmd,code,left);self.runner.on_done=lambda ok:self._done(self,ok)
        self.nav.setCurrentRow(0)

    @staticmethod
    def _layout(self,Q,name,title):
        layout=Q.QVBoxLayout(self.pages[name]);heading=Q.QLabel(title);heading.setStyleSheet("font-size:24px;font-weight:600");layout.addWidget(heading);return layout

    @staticmethod
    def _build_home(self,Q):
        layout=MainWindow._layout(self,Q,PAGE_NAMES[0],"2026 全国大学生数学建模竞赛 A题\n药材烘干模型计算程序")
        layout.addWidget(Q.QLabel("正式模型：M00 一维径向模型    程序状态：已完成 / 已验证\n"+self.facts.message))
        cards=Q.QHBoxLayout();layout.addLayout(cards)
        if self.facts.ready:
            for title,text in official_cards(self.facts.data):box=Q.QGroupBox(title);v=Q.QVBoxLayout(box);v.addWidget(Q.QLabel(text));cards.addWidget(box)
        links=Q.QGridLayout();layout.addLayout(links)
        paths=[(f"打开 result{i}.xlsx",self.root/f"results/tables/result{i}.xlsx") for i in range(1,5)]+[("打开正式结果文件夹",self.root/"results"),("打开主要图表",self.root/"results/q3/q3_curves.png"),("打开动画目录",self.root/"results/animations"),("打开 paper_facts.md",self.root/"results/paper_facts.md")]
        for i,(text,path) in enumerate(paths):button=Q.QPushButton(text);button.clicked.connect(lambda _,p=path:self._open(self,p));links.addWidget(button,i//4,i%4)
        layout.addStretch()

    @staticmethod
    def _build_validation(self,Q):
        layout=MainWindow._layout(self,Q,PAGE_NAMES[1],"快速验证")
        self.validation_run=Q.QLabel("尚未执行本次快速验证；下表为已有证据。") ;layout.addWidget(self.validation_run)
        self.validation_table=Q.QTableWidget(0,3);self.validation_table.setHorizontalHeaderLabels(["项目","状态","说明"]);self.validation_table.horizontalHeader().setStretchLastSection(True);layout.addWidget(self.validation_table);self._refresh_rows(self,Q)
        detail=Q.QGroupBox("详细技术说明");detail.setCheckable(True);detail.setChecked(False);dv=Q.QVBoxLayout(detail);dv.addWidget(Q.QLabel(auxiliary_text(self.rows)+"\n"+TWO_D_DETAIL));layout.addWidget(detail)
        button=Q.QPushButton("运行快速验证");button.clicked.connect(lambda:self._launch(self,self.builder.quick_validation(),"快速验证",True));layout.addWidget(button)

    @staticmethod
    def _refresh_rows(self,Q):
        from PySide6.QtGui import QColor
        self.validation_table.setRowCount(len(self.rows))
        colors={"PASS":"#16803b","FAIL":"#b42318","WARNING":"#9a6700","INFO":"#2563eb","NOT_RUN":"#777"}
        for r,row in enumerate(self.rows):
            for c,value in enumerate((row.label,row.status,row.detail)):
                item=Q.QTableWidgetItem(value);item.setForeground(QColor(colors.get(row.status,"#777")));self.validation_table.setItem(r,c,item)

    @staticmethod
    def _build_compute(self,Q):
        layout=MainWindow._layout(self,Q,PAGE_NAMES[2],"正式计算 · M00（锁定）");layout.addWidget(Q.QLabel("Q2 与 Q3 共享 q23 轨迹。无法可靠读取内部百分比时采用不定进度，不按耗时猜测。"))
        self.case_group=Q.QButtonGroup(self);box=Q.QGroupBox("选择正式轨迹");v=Q.QVBoxLayout(box)
        for text,value in (("Q1","q1"),("Q2/Q3","q23"),("Q4","q4"),("全部","all")):b=Q.QRadioButton(text);b.setProperty("case",value);self.case_group.addButton(b);v.addWidget(b)
        self.case_group.buttons()[0].setChecked(True);layout.addWidget(box);run=Q.QPushButton("开始计算");run.clicked.connect(lambda:self._official(self,Q));layout.addWidget(run);layout.addStretch()

    @staticmethod
    def _build_studies(self,Q):
        layout=MainWindow._layout(self,Q,PAGE_NAMES[3],"创新与模型分析");tabs=Q.QTabWidget();layout.addWidget(tabs)
        texts=[("二维辅助核验",auxiliary_text(self.rows)+"\n\n"+TWO_D_DETAIL),("干燥动力学","慢—快—慢分析 / 干燥前沿 / 扩散时钟 / T-R-C 响应时序"),("几何—物性交叉","P3/P4 + 固定半径/收缩\n"+P4_FIXED_NOTICE),("环境敏感性","30 min / 60 min（正式）/ 90 min\n在当前数值分辨率下未观察到显著尾窗敏感性。"),("热模型",SUPPLEMENTAL_NOTICE+"\nM10 仅潜热；M01 仅显式携热；M11 两者均计。"),("水质量守恒","solver-level mass balance；查看真实发布摘要。")]
        for title,text in texts:w=Q.QWidget();v=Q.QVBoxLayout(w);v.addWidget(Q.QLabel(text));v.addStretch();tabs.addTab(w,title)

    @staticmethod
    def _build_results(self,Q):
        layout=MainWindow._layout(self,Q,PAGE_NAMES[4],"结果浏览（只读）");self.category=Q.QComboBox();self.category.addItems(("正式结果","Q1","Q2","Q3","Q4","动画","创新图","热模型","表格","验证报告"));self.file_list=Q.QListWidget();layout.addWidget(self.category);layout.addWidget(self.file_list);self.category.currentTextChanged.connect(lambda _:self._files(self));self.file_list.itemDoubleClicked.connect(lambda item:self._open(self,self.root/item.text()));self._files(self)

    @staticmethod
    def _build_model(self,Q):
        layout=MainWindow._layout(self,Q,PAGE_NAMES[5],"模型说明");layout.addWidget(Q.QLabel("正式模型：1D 径向圆柱热-质扩散模型\n空间离散：单元中心有限体积法\n时间积分：经典四阶段 RK4\ndt_max = 0.25 s；实际步长受稳定性限制\nQ4：ξ=r/R(t)，径向均匀收缩\n二维仅用于端面效应与降维合理性辅助核验"));layout.addStretch()

    @staticmethod
    def _build_logs(self,Q):
        layout=MainWindow._layout(self,Q,PAGE_NAMES[6],"运行日志");self.log=Q.QPlainTextEdit();self.log.setReadOnly(True);layout.addWidget(self.log)

    @staticmethod
    def _official(self,Q):
        case=next(b.property("case") for b in self.case_group.buttons() if b.isChecked())
        if Q.QMessageBox.question(self,"确认","将重新运行所选正式模型。数值模型和验证参数保持冻结配置。是否继续？")==Q.QMessageBox.StandardButton.Yes:self._launch(self,[self.builder.official(case)],"正式 M00 计算",False)

    @staticmethod
    def _launch(self,commands,name,determinate):
        try:self.progress_state.begin(name,len(commands),determinate);self.task_kind=name;self._update_progress(self);self.runner.start(commands);self.nav.setCurrentRow(6)
        except RuntimeError as exc:self.log.appendPlainText(str(exc))

    @staticmethod
    def _output(self,stream,text):
        self.log.appendPlainText(f"[{stream}] {text.rstrip()}");event=parse_progress(text.strip())
        if event:self.phase_label.setText("当前阶段："+str(event.get("phase","运行中")))

    @staticmethod
    def _step(self,command,code,left):
        checker="results" if "check_results.py" in command[1] else "mass" if "check_mass_balance.py" in command[1] else "auxiliary" if "validate_auxiliary_2d.py" in command[1] else "status"
        if self.task_kind=="快速验证":apply_checker_result(self.rows,checker,code,self.log.toPlainText().splitlines()[-1] if code else "")
        self.progress_state.complete_step(Path(command[1]).name);self._update_progress(self)

    @staticmethod
    def _done(self,ok):
        _,Q=_qt();self.phase_label.setText("当前阶段：完成" if ok else "当前阶段：失败")
        if self.task_kind=="快速验证":self.validation_run.setText("本次快速验证：PASS" if ok else "本次快速验证：FAIL（展开日志查看原因）");self._refresh_rows(self,Q)

    @staticmethod
    def _update_progress(self):
        p=self.progress_state;self.task_label.setText("任务名称："+p.task);self.counter.setText(f"{p.completed} / {p.total}")
        if p.determinate:self.progress.setRange(0,p.total or 1);self.progress.setValue(p.completed)
        else:self.progress.setRange(0,0)

    @staticmethod
    def _safe_stop(self):
        self.runner.request_stop(self.builder.stop_marker("正式" in self.task_kind));self.log.appendPlainText("将在下一个安全保存点停止，并保留可恢复状态。")
    @staticmethod
    def _open(self,path):
        try:open_path(path)
        except Exception as exc:self.log.appendPlainText(str(exc))
    @staticmethod
    def _files(self):
        self.file_list.clear()
        for path in result_catalog(self.root,self.category.currentText()):self.file_list.addItem(path.relative_to(self.root).as_posix())


def main():
    try:
        _,Q=_qt()
    except ImportError as exc:
        print(f"GUI_UNAVAILABLE_PYSIDE6: {exc}");return 1
    app=Q.QApplication.instance() or Q.QApplication([]);window=MainWindow(Path(__file__).resolve().parents[3]);window.show();return app.exec()
