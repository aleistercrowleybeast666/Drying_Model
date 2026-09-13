"""One-page judge UI. All calculation requests use the unified console protocol."""
import json
import codecs
from pathlib import Path
from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (QApplication, QCheckBox, QGroupBox, QHBoxLayout, QLabel,
    QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout, QWidget, QScrollArea, QSplitter)
from ..runtime import Runtime_BuildRecomputeCommand
from ..judge_pipeline import TASKS, Judge_GetPlan
from ..runner_control import Runner_GetProcess, Runner_GetIdentity, Runner_Stop, RunnerStopResult
from ..judge_progress import PREFIX, Progress_ReadJson, Progress_FormatDuration
from .facts import load_facts


class JudgeWindow(QMainWindow):
    def __init__(self, root):
        super().__init__()
        self.root = Path(root); self.pending_close = False; self.buffer = ''; self.dry_run = False
        self.progress_total = None
        self.stop_requested=False;self.external_busy=False
        self.owns_run=False;self.external_run_detected=False;self.owned_identity=None
        self.external_identity=None
        self.progress_target=0;self.progress_terminal=False
        self.decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        self.setWindowTitle('2026 数学建模 A题 · 药材烘干模型'); self.resize(780, 740)
        palette=self.palette()
        for role in [QPalette.ColorRole.Window,QPalette.ColorRole.Base,QPalette.ColorRole.Button,
                     QPalette.ColorRole.AlternateBase,QPalette.ColorRole.ToolTipBase]:
            palette.setColor(role,QColor('#ffffff'))
        for role in [QPalette.ColorRole.WindowText,QPalette.ColorRole.Text,QPalette.ColorRole.ButtonText,
                     QPalette.ColorRole.ToolTipText]:palette.setColor(role,QColor('#243447'))
        self.setPalette(palette)
        # Explicit foreground/background pairs also remain legible under Windows dark mode.
        self.setStyleSheet('''
            QWidget {background:#ffffff;color:#243447; font-size:13px;}
            QMainWindow, QScrollArea, QSplitter {background:#ffffff;}
            QGroupBox {font-weight:bold; background:white; border:1px solid #d9e1ea;
                border-radius:7px; margin-top:10px; padding:12px;}
            QGroupBox::title {subcontrol-origin:margin;left:14px;}
            QPushButton {background:#ffffff;border:1px solid #b7c7d5;border-radius:5px;padding:8px 16px;}
            QPushButton:hover, QPushButton:checked {background:#e2f0f7;}
            QPushButton:disabled {background:#edf1f5;color:#738292;border-color:#d9e1ea;}
            QPushButton#safeStop:enabled {background:#fff0e7;color:#9a3412;border:1px solid #e79055;font-weight:bold;}
            QCheckBox {spacing:8px;padding:4px;}
            QCheckBox::indicator {width:16px;height:16px;border:1px solid #8ba0b2;border-radius:3px;background:white;}
            QCheckBox::indicator:checked {background:#176b91;border:3px solid #a6d2e7;}
            QPlainTextEdit {background:#ffffff;color:#17212b;border:1px solid #8ba0b2;
                font-family:Consolas,"Microsoft YaHei UI",monospace;font-size:16px;padding:8px;
                selection-background-color:#176b91;selection-color:white;}
            QSplitter::handle {background:#b7c7d5;height:7px;}
            QScrollBar:vertical {background:#ffffff;width:12px;margin:0;}
            QScrollBar:horizontal {background:#ffffff;height:12px;margin:0;}
            QScrollBar::handle {background:#b7c7d5;border-radius:4px;min-height:24px;min-width:24px;}
            QScrollBar::add-line, QScrollBar::sub-line {width:0;height:0;}
            QScrollBar::add-page, QScrollBar::sub-page {background:#ffffff;}
            QProgressBar {background:#e6ecf2;border:1px solid #c6d1dc;border-radius:3px;text-align:center;min-height:16px;}
            QProgressBar::chunk {background:#61b1d5;}
        ''')
        central = QWidget(); layout = QVBoxLayout(central); layout.setContentsMargins(24,18,24,18); layout.setSpacing(12)
        layout.addWidget(QLabel('<h2>2026 数学建模 A题 · 药材烘干模型</h2>'))
        facts = load_facts(self.root)
        box = QGroupBox('正式结果 / 冻结参考'); bl = QVBoxLayout(box)
        if facts.ready:
            official = facts.data['official']
            bl.addWidget(QLabel(f"<h2>Q3：{official['Q3']['drying_time_h']:.4f} h　　Q4：{official['Q4']['drying_time_h']:.4f} h</h2>"))
        else:
            from ..runtime import Runtime_GetCode
            path=Runtime_GetCode(self.root)/'configs/table_reference/manifest.json'
            reference=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
            if reference:
                bl.addWidget(QLabel('冻结参考（尚未在本机复算）：Q3 %.4f h　Q4 %.4f h' % tuple(
                    reference['questions'][str(q)]['event']['report_h'] for q in [3,4])))
            else:bl.addWidget(QLabel('暂无结果；开始复算后自动创建工作目录。'))
        bl.addWidget(QLabel('正式模型：M00 一维径向模型　｜　输出 results/；计算缓存 work/recompute/'))
        layout.addWidget(box)
        choices = QGroupBox('四类独立任务'); cl = QVBoxLayout(choices); self.checks = {}
        self.choices=choices
        for title, keys in [('A · 原题计算', ['q1','q23','q4']),
                ('B · 验证', ['one-dimensional','aux-2d','mass-balance','consistency']),
                ('C · 原题绘图', ['static','gif']), ('D · 拓展', ['extensions'])]:
            column = QVBoxLayout(); column.addWidget(QLabel('<b>'+title+'</b>'))
            for key in keys:
                check = QCheckBox(TASKS[key]); check.setChecked(key in ['q1','q23','q4'])
                self.checks[key] = check; column.addWidget(check)
            cl.addLayout(column)
        layout.addWidget(choices)
        row = QHBoxLayout(); self.select_buttons = []
        for text, selection in [('仅原题表格',['q1','q23','q4']), ('全选',list(TASKS)), ('全不选',[])]:
            button = QPushButton(text); button.clicked.connect(lambda checked=False, keys=selection:self.Selection_Set(keys))
            row.addWidget(button); self.select_buttons.append(button)
        row.addStretch(); layout.addLayout(row)
        self.start = QPushButton('开始离线复算'); self.start.setStyleSheet('background:#176b91;color:white;font-weight:bold;padding:12px;')
        self.start.clicked.connect(self.Task_Start); layout.addWidget(self.start)
        self.current = QLabel('就绪 · 启动界面不会自动计算'); layout.addWidget(self.current)
        self.outer = QProgressBar(); self.outer.setRange(0,10000); self.outer.setValue(0);self.outer.setFormat('0.0%'); layout.addWidget(self.outer)
        self.inner = QLabel('按实测工作量加权；进度与预计剩余时间仅用于显示');layout.addWidget(self.inner)
        self.stop = QPushButton('立即停止'); self.stop.setEnabled(False); self.stop.clicked.connect(self.Task_Stop); layout.addWidget(self.stop)
        self.stop.setObjectName('safeStop')
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QScrollArea.Shape.NoFrame);scroll.setWidget(central)
        self.controls_scroll=scroll
        log_panel=QWidget();log_layout=QVBoxLayout(log_panel);log_layout.setContentsMargins(8,0,8,8)
        self.log_toggle = QPushButton('▶ 详细日志'); self.log_toggle.setCheckable(True)
        self.log_toggle.toggled.connect(self.Log_Toggle); log_layout.addWidget(self.log_toggle)
        self.logs = QPlainTextEdit(); self.logs.setReadOnly(True); self.logs.setMaximumBlockCount(10000)
        self.logs.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap);self.logs.setMinimumHeight(220)
        self.logs.hide();log_layout.addWidget(self.logs)
        self.splitter=QSplitter(Qt.Orientation.Vertical);self.splitter.addWidget(scroll);self.splitter.addWidget(log_panel)
        self.splitter.setChildrenCollapsible(False);self.splitter.setStretchFactor(0,1)
        self.setCentralWidget(self.splitter)
        self.process = QProcess(self); self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.Log_Read)
        self.process.finished.connect(self.Task_Done); self.process.errorOccurred.connect(self.Task_Error)
        self.process.stateChanged.connect(self.Task_StateChanged)
        self.progress_timer=QTimer(self);self.progress_timer.setInterval(200)
        self.progress_timer.timeout.connect(self.Progress_Animate);self.progress_timer.start()
        self.external_timer=QTimer(self);self.external_timer.setInterval(1000)
        self.external_timer.timeout.connect(self.Task_CheckExternal);self.external_timer.start()
        self.Task_CheckExternal()

    def Selection_Set(self, keys):
        for key, check in self.checks.items(): check.setChecked(key in keys)

    def Log_Toggle(self, visible):
        self.logs.setVisible(visible); self.log_toggle.setText(('▼' if visible else '▶')+' 详细日志')
        self.splitter.setSizes([max(200,self.height()-300),300] if visible else [self.height(),48])
        if visible:QTimer.singleShot(0,lambda:self.controls_scroll.ensureWidgetVisible(self.stop,0,16))

    def Task_Start(self):
        self.Task_CheckExternal()
        if self.external_busy or self.process.state()!=QProcess.ProcessState.NotRunning:
            self.current.setText('已有复算正在运行，可立即停止；当前选择仅用于下一轮。')
            self.log_toggle.setChecked(True);return
        keys = [key for key, check in self.checks.items() if check.isChecked()]
        if not keys:
            self.current.setText('请至少勾选一个复算项目。'); return
        plan=Judge_GetPlan(self.root,keys)
        dependencies=list(plan['automatic_dependencies'])
        if set(keys)&{'static','gif'}:
            from ..judge_plots import Judge_GetPlotMissing
            missing=Judge_GetPlotMissing(self.root/'work/recompute/runtime')
            additions={row['required_task'] for row in missing}-set(keys)
            if additions:
                dependencies += ['绘图缺少数据，需要 '+TASKS[key] for key in sorted(additions)]
                keys += sorted(additions)
                plan=Judge_GetPlan(self.root,keys)
        self.logs.appendPlainText(json.dumps(plan,ensure_ascii=False,indent=2))
        if dependencies and not self.dry_run:
            answer=QMessageBox.question(self,'确认所选任务的必要依赖',
                '将补充以下计算：\n'+'\n'.join('• '+text for text in dependencies)+
                '\n\n最多两个计算进程并行。是否按上方计划开始？',
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
            if answer!=QMessageBox.StandardButton.Yes:return
        args = ['--tasks', *keys, '--gui-run'] + (['--dry-run'] if self.dry_run else [])
        if not self.dry_run:
            for name in ['STOP','BASELINE_STOP']:
                (self.root/'work/recompute/work/studies'/name).unlink(missing_ok=True)
        command = Runtime_BuildRecomputeCommand(args, self.root)
        self.buffer = ''; self.pending_close = False; self.decoder.reset();self.stop_requested=False
        self.process.setWorkingDirectory(str(self.root))
        env = QProcessEnvironment.systemEnvironment(); env.insert('DRYING_MODEL_ROOT', str(self.root)); env.insert('PYTHONIOENCODING','utf-8'); env.insert('PYTHONUNBUFFERED','1')
        self.process.setProcessEnvironment(env)
        self.progress_target=0;self.progress_terminal=False
        self.outer.setRange(0,10000);self.outer.setValue(0);self.outer.setFormat('0.0%')
        self.Controls_Set(True); self.current.setText('正在准备所选任务及必要依赖…')
        self.inner.setText('准备、JIT 和运行任务都计入总进度；预计剩余时间会随实际速度更新。')
        self.owns_run=True;self.external_run_detected=False
        self.process.start(command[0],command[1:])

    def Controls_Set(self, busy):
        for control in [self.start, *self.checks.values(), *self.select_buttons]: control.setEnabled(True)
        self.choices.setTitle('下一轮任务选择（当前计算继续）' if busy else '四类独立任务')
        self.start.setText('复算进行中 · 点击查看状态' if busy else '开始离线复算')
        self.stop.setEnabled(busy)
        self.stop.setText('停止外部复算' if busy and not self.owns_run else '立即停止')
        self.stop.setToolTip('结束本次复算进程树；未保存进度会丢失，部分输出可能需要重算' if busy else '没有正在运行的复算任务')

    def Task_StateChanged(self,state):
        if state!=QProcess.ProcessState.NotRunning:
            self.owns_run=True
            if int(self.process.processId()):
                import psutil
                try:self.owned_identity=Runner_GetIdentity(psutil.Process(int(self.process.processId())))
                except psutil.Error:pass
            self.Controls_Set(True)

    def Task_CheckExternal(self):
        if self.process.state()!=QProcess.ProcessState.NotRunning:return
        external=Runner_GetProcess(self.root);busy=external is not None
        self.external_run_detected=busy
        if busy:
            identity=Runner_GetIdentity(external)
            if identity!=self.external_identity:
                self.external_identity=identity;self.progress_target=0;self.progress_terminal=False
                self.outer.setValue(0);self.outer.setFormat('0.0%')
            event=Progress_ReadJson(self.root/'work/recompute/progress.json')
            if event.get('runner_pid')==external.pid and abs(event.get('runner_created_at',0)-external.create_time())<.01:
                self.Progress_ApplyEvent(event)
        elif self.external_identity:
            event=Progress_ReadJson(self.root/'work/recompute/progress.json')
            if (event.get('runner_pid')==self.external_identity['pid'] and
                abs(event.get('runner_created_at',0)-self.external_identity['created_at'])<.01 and
                event.get('event') in ['run_complete','run_failed','run_stopped']):self.Progress_ApplyEvent(event)
        requested=False
        if busy!=self.external_busy or (busy and requested!=self.stop_requested):
            self.external_busy=busy
            self.stop_requested=requested
            self.Controls_Set(busy)
            self.current.setText('检测到外部 CLI 复算；关闭本窗口不会停止它，停止外部复算需要确认。' if busy else
                '已有复算进程已结束；结果状态请查看日志。')

    def Task_Stop(self):
        identity=self.owned_identity if self.owns_run else None
        if not self.owns_run:
            process=Runner_GetProcess(self.root)
            if process is None:return RunnerStopResult.NO_TASK
            identity=Runner_GetIdentity(process)
            answer=QMessageBox.question(self,'停止外部复算',f'外部 CLI（PID {process.pid}）不是本窗口启动的。\n确定停止这一次复算及其子进程吗？\n未保存进度会丢失。',
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
            if answer!=QMessageBox.StandardButton.Yes:return RunnerStopResult.NO_TASK
        self.stop_requested=True
        result=Runner_Stop(self.root,int(self.process.processId()) if self.owns_run else 0,expected_identity=identity)
        self.external_busy=Runner_GetProcess(self.root) is not None
        if result==RunnerStopResult.NO_TASK:
            self.stop_requested=False
            self.current.setText('所确认的进程已结束或身份已变化；未停止其他复算。')
        else:self.current.setText('已立即停止；未保存进度可能丢失，下次将重新校验缓存。' if result!=RunnerStopResult.FAILED else
            '未能结束全部进程，请查看系统进程状态后重试。')
        self.logs.appendPlainText(self.current.text())
        if self.process.state()!=QProcess.ProcessState.NotRunning:self.process.waitForFinished(1000)
        self.Controls_Set(self.external_busy)
        return result

    def Log_Read(self):
        self.buffer += self.decoder.decode(bytes(self.process.readAllStandardOutput()))
        while '\n' in self.buffer:
            line,self.buffer = self.buffer.split('\n',1)
            line=line.replace(str(self.root),'.').replace(self.root.as_posix(),'.')
            if line.startswith(PREFIX):
                try:
                    self.Progress_ApplyEvent(json.loads(line[len(PREFIX):]))
                except (ValueError,KeyError): pass
            else:self.logs.appendPlainText(line)

    def Progress_ApplyEvent(self,event):
        import math
        value=float(event['overall_fraction'])
        if event.get('schema_version')!=1 or not math.isfinite(value):return
        complete=event.get('event')=='run_complete'
        target=10000 if complete else min(9990,max(0,int(value*10000)))
        self.progress_target=max(self.progress_target,target)
        if complete:self.progress_terminal=True
        if not self.isVisible() or complete:self.outer.setValue(self.progress_target)
        self.outer.setFormat(f'{self.outer.value()/100:.1f}%')
        self.current.setText(f"总进度 {self.progress_target/100:.1f}% · 已用 {Progress_FormatDuration(event['elapsed_s'])} · 预计剩余 {Progress_FormatDuration(event['eta_s'])}")
        tasks=event.get('running_tasks',[])
        self.inner.setText('　'.join(f"{r['task_label']}：{r['task_fraction']*100:.1f}%" for r in tasks) or event['message'])

    def Progress_Animate(self):
        current=self.outer.value()
        if current<self.progress_target:
            self.outer.setValue(min(self.progress_target,current+max(1,int((self.progress_target-current)*.45))))
            self.outer.setFormat(f'{self.outer.value()/100:.1f}%')

    def Task_Done(self, code, status):
        self.Log_Read()
        if self.buffer: self.logs.appendPlainText(self.buffer); self.buffer = ''
        self.Controls_Set(False)
        self.owns_run=False;self.owned_identity=None
        if self.stop_requested:
            self.current.setText('已立即停止；保留有效检查点，未完成阶段下次重新校验。')
            if self.pending_close:self.close()
            return
        if code==0 and not self.dry_run:
            self.progress_target=10000;self.progress_terminal=True
            self.outer.setValue(self.outer.maximum())
            self.outer.setFormat('100.0%')
        self.inner.setText('已完成；所有所选任务已成功返回。' if code==0 and not self.dry_run else
            '保留已完成进度；重新开始新一轮任务时归零。')
        self.current.setText(('计划检查完成 · 未执行求解' if self.dry_run else '任务完成 · PASS') if code==0 else '已安全停止，可再次开始恢复' if code==2 else f'任务失败（退出码 {code}），请展开详细日志')
        timing_path=self.root/'results/recompute_timing_summary.json'
        if code==0 and not self.dry_run and timing_path.exists():
            timing=json.loads(timing_path.read_text(encoding='utf-8'))
            groups=timing.get('group_wall_s',timing.get('group_worker_wall_s',{}))
            text='　'.join(label+' %.2f min'%(groups.get(key,0)/60) for key,label in
                [('original','原题'),('validation','验证'),('plot','绘图'),('extension','拓展')])
            self.inner.setText(text+'\n总耗时 %.2f min'%(timing.get('total_wall_s',timing['wall_s'])/60))
        if code not in (0,2):self.log_toggle.setChecked(True)
        if self.pending_close: self.close()

    def Task_Error(self, error):
        self.logs.appendPlainText(self.process.errorString())
        if error == QProcess.ProcessError.FailedToStart: self.Task_Done(1,None)

    def closeEvent(self, event):
        if self.owns_run and self.process.state()!=QProcess.ProcessState.NotRunning:
            answer=QMessageBox.question(self,'关闭并停止本次复算','关闭窗口将停止本窗口启动的复算及其子进程。确定关闭吗？',
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
            if answer!=QMessageBox.StandardButton.Yes:event.ignore();return
            if self.Task_Stop()==RunnerStopResult.FAILED:
                event.ignore();return
        event.accept()

    def Smoke_Check(self, path):
        assert self.isVisible() and self.process.state() == QProcess.ProcessState.NotRunning
        assert [k for k,v in self.checks.items() if v.isChecked()] == ['q1','q23','q4']
        self.select_buttons[1].click(); assert all(v.isChecked() for v in self.checks.values())
        self.select_buttons[2].click(); assert not any(v.isChecked() for v in self.checks.values())
        self.start.click(); assert ('已有复算' if self.external_busy else '至少') in self.current.text()
        self.select_buttons[0].click()
        if not self.external_busy:self.current.setText('就绪 · 启动界面不会自动计算')
        self.log_toggle.click(); self.logs.appendPlainText('GUI smoke: 勾选、按钮、日志正常；未开始计算。')
        QApplication.processEvents()
        output = Path(path); output.parent.mkdir(parents=True,exist_ok=True)
        self.grab().save(str(output.with_suffix('.png')))
        output.write_text(json.dumps(dict(visible=True,default_official=True,selection_buttons=True,logs=True,
            no_automatic_computation=True,platform=QApplication.platformName()),ensure_ascii=False,indent=2),encoding='utf-8')
