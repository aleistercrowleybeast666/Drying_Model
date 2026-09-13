"""One-page judge UI. All calculation requests use the unified console protocol."""
import json
import codecs
import time
import math
from pathlib import Path
from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (QApplication, QCheckBox, QGroupBox, QHBoxLayout, QLabel,
    QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout, QWidget, QScrollArea, QSplitter)
from ..runtime import Runtime_BuildRecomputeCommand
from ..pipeline_plan import PipelinePlan_Build, Pipeline_CheckPrerequisites
from .catalog_panel import CatalogPanel
from ..runner_control import Runner_GetProcess, Runner_GetIdentity, Runner_Stop, RunnerStopResult
from ..judge_progress import PREFIX, Progress_ReadJson, Progress_FormatDuration, Progress_GetConfidenceText


class JudgeWindow(QMainWindow):
    def __init__(self, root):
        super().__init__()
        self.root = Path(root); self.pending_close = False; self.buffer = ''; self.dry_run = False
        self.progress_total = None
        self.stop_requested=False;self.external_busy=False
        self.owns_run=False;self.external_run_detected=False;self.owned_identity=None
        self.external_identity=None
        self.progress_target=0;self.progress_terminal=False;self.progress_confidence='calibrated';self.animation_time=time.monotonic()
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
            QCheckBox:disabled {color:#89949f;}
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
        box = QGroupBox('正式结果 / 冻结参考'); bl = QVBoxLayout(box)
        from ..runtime import Runtime_GetCode
        reference=Progress_ReadJson(Runtime_GetCode(self.root)/'configs/table_reference/manifest.json')
        self.reference_text=('冻结参考：Q3 %.4f h　Q4 %.4f h' % tuple(
            reference['questions'][str(q)]['event']['report_h'] for q in [3,4])) if reference else '暂无冻结参考'
        self.official_values=QLabel(self.reference_text+'；本机数据待扫描。');self.official_values.setWordWrap(True)
        bl.addWidget(self.official_values)
        bl.addWidget(QLabel('正式模型：M00 一维径向模型　｜　输出 results/；计算缓存 work/recompute/'))
        layout.addWidget(box)
        choices = QGroupBox('四类独立任务'); cl = QVBoxLayout(choices); self.checks = {}
        self.choices=choices
        self.catalog_panel=CatalogPanel(self.root);cl.addWidget(self.catalog_panel)
        self.catalog_panel.cache_updated.connect(self.Results_Refresh)
        self.checks=self.catalog_panel.checks;self.select_buttons=self.catalog_panel.select_buttons
        self.refresh_button=self.catalog_panel.refresh
        layout.addWidget(choices)
        self.start = QPushButton('开始离线复算'); self.start.setStyleSheet('background:#176b91;color:white;font-weight:bold;padding:12px;')
        self.start.clicked.connect(self.Task_Start); layout.addWidget(self.start)
        self.current = QLabel('就绪 · 启动界面不会自动计算'); layout.addWidget(self.current)
        self.current.setWordWrap(True)
        self.outer = QProgressBar(); self.outer.setRange(0,10000); self.outer.setValue(0);self.outer.setFormat('0.0%'); layout.addWidget(self.outer)
        self.inner = QLabel('总进度按已用时间与关键路径 ETA 估算；任务进度来自实际计算证据');layout.addWidget(self.inner)
        self.inner.setWordWrap(True)
        self.stop = QPushButton('立即停止'); self.stop.setEnabled(False); self.stop.clicked.connect(self.Task_Stop); layout.addWidget(self.stop)
        self.stop.setObjectName('safeStop')
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QScrollArea.Shape.NoFrame);scroll.setWidget(central)
        self.controls_scroll=scroll
        # Keep start/stop and progress visible while the catalog scrolls.
        upper=QWidget();upper_layout=QVBoxLayout(upper);upper_layout.setContentsMargins(8,0,8,0)
        upper_layout.addWidget(scroll,1)
        for widget in [self.start,self.current,self.outer,self.inner,self.stop]:
            layout.removeWidget(widget);upper_layout.addWidget(widget)
        log_panel=QWidget();log_layout=QVBoxLayout(log_panel);log_layout.setContentsMargins(8,0,8,8)
        self.log_toggle = QPushButton('▶ 详细日志'); self.log_toggle.setCheckable(True)
        self.log_toggle.toggled.connect(self.Log_Toggle); log_layout.addWidget(self.log_toggle)
        self.logs = QPlainTextEdit(); self.logs.setReadOnly(True); self.logs.setMaximumBlockCount(10000)
        self.logs.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap);self.logs.setMinimumHeight(220)
        self.logs.hide();log_layout.addWidget(self.logs)
        self.splitter=QSplitter(Qt.Orientation.Vertical);self.splitter.addWidget(upper);self.splitter.addWidget(log_panel)
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
        self.catalog_panel.Cache_Refresh()

    def Selection_Set(self, keys):
        self.catalog_panel.Selection_Set(keys)

    def Results_Refresh(self,snapshot):
        values=[]
        for question,case in [('Q3','q23'),('Q4','q4')]:
            hours=snapshot.get('official',{}).get(case,{}).get('drying_time_h')
            values.append(f'{question}：{hours:.4f} h（本机缓存已核验）' if hours is not None else question+'：暂无有效本机数据')
        self.official_values.setText('　'.join(values)+'\n'+self.reference_text)

    def Log_Toggle(self, visible):
        self.logs.setVisible(visible); self.log_toggle.setText(('▼' if visible else '▶')+' 详细日志')
        self.splitter.setSizes([max(200,self.height()-300),300] if visible else [self.height(),48])

    def Task_Start(self):
        self.Task_CheckExternal()
        if self.external_busy or self.process.state()!=QProcess.ProcessState.NotRunning:
            self.current.setText('已有复算正在运行，可立即停止；当前选择仅用于下一轮。')
            self.log_toggle.setChecked(True);return
        keys = [key for key, check in self.checks.items() if check.isChecked()]
        if not keys:
            self.current.setText('请至少勾选一个复算项目。'); return
        if self.catalog_panel.scan is not None and any(self.catalog_panel.catalog[k]['mode'] in ['C','D'] for k in keys):
            self.current.setText('请等待缓存刷新完成，再开始绘图或验证。');return
        try:
            plan=PipelinePlan_Build(self.root,keys,force_data=self.catalog_panel.force_data.isChecked(),
                force_validation=self.catalog_panel.force_validation.isChecked())
            Pipeline_CheckPrerequisites(plan)
        except (RuntimeError,OSError,ValueError,KeyError) as error:
            self.current.setText('缺少前置数据；请刷新缓存并先运行对应数据项。')
            self.logs.appendPlainText(str(error));self.log_toggle.setChecked(True);self.catalog_panel.Cache_Refresh();return
        self.logs.appendPlainText(json.dumps(plan,ensure_ascii=False,indent=2))
        if any(self.catalog_panel.catalog[k]['mode']=='D' for k in keys) and not self.dry_run:
            answer=QMessageBox.question(self,'确认耗时验证','已选择 D 验证，可能耗时很长。仅执行所选验证，是否继续？',
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
            if answer!=QMessageBox.StandardButton.Yes:return
        args=['--tasks',*keys,'--gui-run']
        if self.catalog_panel.force_data.isChecked():args.append('--force-data')
        if self.catalog_panel.force_validation.isChecked():args.append('--force-validation')
        if self.dry_run:args.append('--dry-run')
        if not self.dry_run:
            for name in ['STOP','BASELINE_STOP']:
                (self.root/'work/recompute/work/studies'/name).unlink(missing_ok=True)
        command = Runtime_BuildRecomputeCommand(args, self.root)
        self.buffer = ''; self.pending_close = False; self.decoder.reset();self.stop_requested=False
        self.process.setWorkingDirectory(str(self.root))
        env = QProcessEnvironment.systemEnvironment(); env.insert('DRYING_MODEL_ROOT', str(self.root)); env.insert('PYTHONIOENCODING','utf-8'); env.insert('PYTHONUNBUFFERED','1')
        self.process.setProcessEnvironment(env)
        self.progress_target=0;self.progress_terminal=False;self.progress_confidence='calibrated';self.animation_time=time.monotonic()
        self.outer.setRange(0,10000);self.outer.setValue(0);self.outer.setFormat('0.0%')
        self.Controls_Set(True); self.current.setText('正在准备所选任务及必要依赖…')
        self.inner.setText('准备、JIT 和运行任务都计入总进度；预计剩余时间会随实际速度更新。')
        self.owns_run=True;self.external_run_detected=False
        self.process.start(command[0],command[1:])

    def Controls_Set(self, busy):
        for control in [self.start, *self.select_buttons]: control.setEnabled(True)
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
                self.external_identity=identity;self.progress_target=0;self.progress_terminal=False;self.progress_confidence='calibrated';self.animation_time=time.monotonic()
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
        value=float(event['overall_fraction'])
        if event.get('schema_version')!=1 or not math.isfinite(value):return
        self.catalog_panel.Progress_Apply(event)
        complete=event.get('event')=='run_complete';elapsed=event['elapsed_s'];eta=event.get('eta_s')
        if event.get('event') in ['run_failed','run_stopped']:
            self.progress_terminal=True
            self.outer.setRange(0,10000);self.progress_target=min(9990,max(self.outer.value(),self.progress_target,0,int(value*10000)))
            self.outer.setValue(self.progress_target);self.outer.setFormat('失败' if event['event']=='run_failed' else '已停止')
            self.current.setText(event['message']);return
        confidence=event.get('progress_confidence','calibrated');eta_confidence=event.get('eta_confidence','calibrated')
        if eta is not None and elapsed+eta>0:
            implied=elapsed/(elapsed+eta)
            if (abs(value-implied)>.20 and eta_confidence!='measured') or (value>.7 and eta>elapsed and not event.get('all_critical_measured')):
                confidence='unknown'
        self.progress_confidence='measured' if complete else confidence
        tasks=event.get('running_tasks',[])
        self.outer.setRange(0,10000)
        if confidence=='unknown' and not complete:
            self.progress_target=max(self.progress_target,self.outer.value())
            self.outer.setFormat(f'{self.outer.value()/100:.1f}% · 校准中')
            self.current.setText('正在校准剩余时间，进度暂保持 · 已用 '+Progress_FormatDuration(elapsed)+' · 剩余时间：'+Progress_GetConfidenceText(event))
        else:
            target=10000 if complete else min(9990,max(0,int(value*10000)))
            self.progress_target=max(self.progress_target,self.outer.value(),target)
            if complete:self.progress_terminal=True;self.outer.setValue(10000)
            elif not self.isVisible():self.outer.setValue(self.progress_target)
            label=f'总进度约 {self.progress_target/100:.1f}%'
            self.current.setText(label+' · 已用 '+Progress_FormatDuration(elapsed)+' · 预计剩余 '+Progress_GetConfidenceText(event))
            self.outer.setFormat(f'约 {self.outer.value()/100:.0f}%' if confidence=='rough' else f'{self.outer.value()/100:.1f}%')
        groups='　'.join(f"{mode}：{row['completed']}/{row['total']} 项已完成" for mode,row in event.get('mode_progress',{}).items())
        self.inner.setText(event.get('pipeline_phase_label','')+'　'+groups+'\n'+('　'.join(r['task_label']+('：计算中（进度正在校准）' if r.get('estimated') else f"：{r['task_fraction']*100:.1f}%") for r in tasks) or event['message']))

    def Progress_Animate(self,dt=None):
        now=time.monotonic();dt=max(0.,min(.5,now-self.animation_time)) if dt is None else max(0.,dt);self.animation_time=now
        if self.progress_terminal:return
        current=self.outer.value();gap=self.progress_target-current
        if gap>0:
            change=min(gap*(1-math.exp(-dt/10.)),80*dt)
            self.outer.setValue(min(self.progress_target,current+max(1,int(change))))
        self.outer.setFormat(f'{self.outer.value()/100:.1f}% · 校准中' if self.progress_confidence=='unknown' else
            f'约 {self.outer.value()/100:.0f}%' if self.progress_confidence=='rough' else f'{self.outer.value()/100:.1f}%')

    def Task_Done(self, code, status):
        self.Log_Read()
        if self.buffer: self.logs.appendPlainText(self.buffer); self.buffer = ''
        self.Controls_Set(False)
        self.catalog_panel.running_keys.clear()
        self.catalog_panel.Cache_Refresh()
        self.owns_run=False;self.owned_identity=None
        if self.stop_requested:
            self.progress_terminal=True;self.outer.setFormat('已停止')
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
                [('original','A 四表'),('extension','B 创新数据'),('plot','C 绘图'),('validation','D 验证')])
            self.inner.setText(text+'\n总耗时 %.2f min'%(timing.get('total_wall_s',timing.get('wall_s',0))/60))
        if code not in (0,2):self.log_toggle.setChecked(True)
        if code!=0:
            self.progress_terminal=True
            self.outer.setRange(0,10000);self.outer.setValue(min(9990,self.progress_target));self.outer.setFormat('已停止' if code==2 else '失败')
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
        self.select_buttons[1].click(); assert {k for k,v in self.checks.items() if v.isChecked()}==set(self.catalog_panel.presets['paper'])
        self.select_buttons[3].click(); assert not any(v.isChecked() for v in self.checks.values())
        self.start.click(); assert ('已有复算' if self.external_busy else '至少') in self.current.text()
        self.select_buttons[0].click()
        if not self.external_busy:self.current.setText('就绪 · 启动界面不会自动计算')
        self.log_toggle.click(); self.logs.appendPlainText('GUI smoke: 勾选、按钮、日志正常；未开始计算。')
        QApplication.processEvents()
        output = Path(path); output.parent.mkdir(parents=True,exist_ok=True)
        self.grab().save(str(output.with_suffix('.png')))
        output.write_text(json.dumps(dict(visible=True,default_official=True,selection_buttons=True,logs=True,
            no_automatic_computation=True,platform=QApplication.platformName()),ensure_ascii=False,indent=2),encoding='utf-8')
