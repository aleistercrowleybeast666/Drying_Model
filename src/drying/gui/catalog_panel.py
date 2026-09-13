"""Catalog-driven Chinese selectors; cache scanning never runs on the UI thread."""
from PySide6.QtCore import QObject,QRunnable,QThreadPool,Signal
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QCheckBox,QGroupBox
from ..pipeline_plan import Catalog_Read,Catalog_GetPresets
from ..catalog_cache import Catalog_ScanCache


class CacheSignals(QObject):
    finished=Signal(dict)
    failed=Signal(str)


class CacheScan(QRunnable):
    def __init__(self,root,catalog):
        super().__init__();self.root=root;self.catalog=catalog;self.signals=CacheSignals()

    def run(self):
        try:self.signals.finished.emit(Catalog_ScanCache(self.root,self.catalog))
        except Exception as error:self.signals.failed.emit(str(error))


class CatalogPanel(QWidget):
    cache_updated=Signal(dict)

    def __init__(self,root,parent=None):
        super().__init__(parent);self.root=root;self.catalog=Catalog_Read(root)
        self.checks={};self.status_labels={};self.mode_labels={};self.mode_buttons={};self.snapshot=None;self.scan=None
        self.running_keys=set();self.task_states={};self.run_id=None;self.refresh_pending=False
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        refresh_row=QHBoxLayout();self.refresh=QPushButton('刷新缓存');self.refresh.clicked.connect(self.Cache_Refresh)
        refresh_row.addWidget(self.refresh);self.cache_label=QLabel('正在核验跨运行缓存…');self.cache_label.setWordWrap(True)
        refresh_row.addWidget(self.cache_label,1);layout.addLayout(refresh_row)
        self.presets=Catalog_GetPresets(root);self.select_buttons=[];presets_row=QHBoxLayout()
        for text,keys in [('仅四表',self.presets['official']),('论文数据（A+B）',self.presets['paper']),
                          ('全选（A+B+C+D）',self.presets['all']),('全不选',[])]:
            button=QPushButton(text);button.clicked.connect(lambda checked=False,ks=keys:self.Selection_Set(ks))
            presets_row.addWidget(button);self.select_buttons.append(button)
        layout.addLayout(presets_row)
        for mode,title in [('A','四表正式数据'),('B','创新实验数据'),('C','绘图'),('D','验证（耗时最长，建议不做）')]:
            group=QGroupBox(mode+' · '+title);group_layout=QVBoxLayout(group);layout.addWidget(group)
            header=QHBoxLayout();count=QLabel();self.mode_labels[mode]=count;header.addWidget(count,1)
            keys=[k for k,r in self.catalog.items() if r['mode']==mode]
            all_button=QPushButton('全选本模式');none_button=QPushButton('全不选本模式')
            all_button.clicked.connect(lambda checked=False,ks=keys:self.Selection_Set(ks,ks))
            none_button.clicked.connect(lambda checked=False,ks=keys:self.Selection_Set([],ks))
            self.mode_buttons[mode]=(all_button,none_button);header.addWidget(all_button);header.addWidget(none_button)
            group_layout.addLayout(header);body=QWidget();body_layout=QVBoxLayout(body)
            if mode in ['C','D']:
                toggle=QPushButton('展开项目' if mode=='D' else '收起项目');toggle.setCheckable(True);toggle.setChecked(mode=='C')
                body.setVisible(mode=='C');toggle.toggled.connect(body.setVisible)
                toggle.toggled.connect(lambda value,b=toggle:b.setText('收起项目' if value else '展开项目'))
                group_layout.addWidget(toggle)
            group_layout.addWidget(body)
            groups=dict.fromkeys(self.catalog[k]['group'] for k in keys)
            for subgroup in groups:
                subkeys=[k for k in keys if self.catalog[k]['group']==subgroup]
                if mode!='A':
                    row=QHBoxLayout();row.addWidget(QLabel(subgroup),1)
                    for text,selection in [('全选',subkeys),('全不选',[])]:
                        button=QPushButton(text);button.clicked.connect(lambda checked=False,ks=selection,scope=subkeys:self.Selection_Set(ks,scope));row.addWidget(button)
                    body_layout.addLayout(row)
                for key in subkeys:
                    item=self.catalog[key];row=QHBoxLayout();check=QCheckBox(item['display_name_zh'])
                    check.setChecked(item.get('default_selected',False));check.setEnabled(mode in ['A','B'])
                    check.toggled.connect(self.Counts_Refresh);label=QLabel('待扫描')
                    label.setWordWrap(True);label.setMaximumWidth(270)
                    check.setToolTip(self.Tooltip_Get(key));self.checks[key]=check;self.status_labels[key]=label
                    row.addWidget(check,1);row.addWidget(label);body_layout.addLayout(row)
        force_row=QHBoxLayout();self.force_data=QCheckBox('强制重算所选 A/B 数据');self.force_validation=QCheckBox('强制重算所选 D 验证')
        force_row.addWidget(self.force_data);force_row.addWidget(self.force_validation);layout.addLayout(force_row)
        self.Counts_Refresh()

    def Tooltip_Get(self,key,missing=()):
        row=self.catalog[key]
        return '\n'.join([row['description_zh'],row.get('path',key)]+
            (['缺少前置数据：']+[m['label']+'：'+m['reason'] for m in missing] if missing else []))

    def Selection_Set(self,keys,scope=None):
        selected=set(keys)
        for key in self.checks if scope is None else scope:
            check=self.checks[key];check.setChecked(key in selected and check.isEnabled())
        self.Counts_Refresh()

    def Counts_Refresh(self):
        for mode,label in self.mode_labels.items():
            keys=[k for k,r in self.catalog.items() if r['mode']==mode]
            states=(self.snapshot or {}).get('items',{})
            label.setText(f'已选 {sum(self.checks[k].isChecked() for k in keys if k in self.checks)}/{len(keys)}'
                +f'　已缓存/完成 {sum(states.get(k,{}).get("complete",False) for k in keys)}'
                +(f'　缺前置 {sum(not states.get(k,{}).get("enabled",False) for k in keys)}' if mode in ['C','D'] else ''))

    def Progress_Apply(self,event):
        run_id=event.get('run_id')
        if run_id is not None and run_id!=self.run_id:
            self.task_states={};self.run_id=run_id
        self.running_keys=set()
        states=event.get('task_states',{})
        for task,state in states.items():
            key=self.Task_GetKey(task)
            if key in self.checks:self.task_states[key]=state
        for row in event.get('running_tasks',[]):
            key=self.Task_GetKey(row.get('task_key',''))
            if key in self.checks:self.running_keys.add(key)
        self.Status_Refresh()

    def Task_GetKey(self,task):
        return task[2:] if task.startswith('A.') else dict(B='innovation.',C='plot.',D='validation.').get(task[:1],'')+task[2:]

    def Status_Refresh(self):
        states=(self.snapshot or {}).get('items',{})
        for key,label in self.status_labels.items():
            status=states.get(key,{}).get('status','待扫描')
            if key in self.running_keys:
                status={'C':'正在绘图','D':'正在验证'}.get(self.catalog[key]['mode'],'正在计算')
            elif self.task_states.get(key)=='PASS':status='已完成（待刷新核验）'
            elif self.task_states.get(key) in ['FAIL','FAILED']:status='任务失败，请查看日志'
            label.setText(status)

    def Cache_Refresh(self):
        if self.scan is not None:
            self.refresh_pending=True;return
        self.refresh.setEnabled(False);self.cache_label.setText('正在扫描文件并核验缓存；扫描期间 C/D 暂不可选…')
        for key,check in self.checks.items():
            if self.catalog[key]['mode'] in ['C','D']:check.setEnabled(False)
        scan=CacheScan(self.root,self.catalog);scan.signals.finished.connect(self.Cache_Apply);scan.signals.failed.connect(self.Cache_Failed)
        self.scan=scan;QThreadPool.globalInstance().start(scan)

    def Cache_Apply(self,snapshot):
        self.snapshot=snapshot;removed=0
        for key,check in self.checks.items():
            state=snapshot['items'][key];check.setEnabled(state['enabled'])
            if not state['enabled']:
                removed+=check.isChecked();check.setChecked(False)
            if key not in self.running_keys:self.task_states.pop(key,None)
            check.setToolTip(self.Tooltip_Get(key,state['missing']))
        self.scan=None;self.refresh.setEnabled(True);self.Counts_Refresh()
        self.Status_Refresh();self.cache_updated.emit(snapshot)
        self.cache_label.setText('缓存已刷新 '+snapshot['scanned_at']+
            (f'；已取消 {removed} 个缺少前置数据的选项。' if removed else '；C/D 按每项依赖独立开放。'))
        if self.refresh_pending:self.refresh_pending=False;self.Cache_Refresh()

    def Cache_Failed(self,error):
        self.scan=None;self.snapshot=None;self.refresh.setEnabled(True);self.cache_label.setText('缓存扫描失败，可重试：'+error)
        for key,check in self.checks.items():
            if self.catalog[key]['mode'] in ['C','D']:check.setEnabled(False);check.setChecked(False)
        self.Counts_Refresh();self.Status_Refresh()
        self.cache_updated.emit({'official':{}})
        if self.refresh_pending:self.refresh_pending=False;self.Cache_Refresh()
