"""Thin Tk control panel. Commands and numerical work remain in existing CLIs."""
import json
import os
import queue
import subprocess
import sys
import threading
from enum import IntEnum
from pathlib import Path


class AppCommandResult(IntEnum):
    READY = 0
    INVALID_SELECTION = 1
    PYTHON_MISSING = 2


def App_BuildCommand(root,task,action,group='all',case='all',mode='all'):
    root=Path(root);python=root/'.venv/Scripts/python.exe'
    if not python.is_file():return AppCommandResult.PYTHON_MISSING,[]
    if task not in ['baseline','studies'] or action not in ['compute','resume','plot','payload','dry_run']:
        return AppCommandResult.INVALID_SELECTION,[]
    if task=='baseline':
        command=[str(python),str(root/('plot.py' if action=='plot' else 'compute.py'))]
        if action=='payload':command+=['--payload-only']
        if action=='dry_run':return AppCommandResult.INVALID_SELECTION,[]
    else:
        command=[str(python),str(root/('plot_studies.py' if action=='plot' else 'compute_studies.py'))]
        if action!='plot':
            if group not in ['all','verify','postprocess','geometry','environment','thermal']:return AppCommandResult.INVALID_SELECTION,[]
            if case not in ['all','q1','q23','q4'] or mode not in ['all','M00','M10','M01','M11']:return AppCommandResult.INVALID_SELECTION,[]
            if group not in ['all','thermal'] and mode not in ['all','M00']:return AppCommandResult.INVALID_SELECTION,[]
            command+=['--group',group]
            if action=='resume':command+=['--resume']
            if action=='payload':command+=['--resume','--payload-only']
            if action=='dry_run':command+=['--dry-run']
            if case!='all':command+=['--case',case]
            if mode!='all':command+=['--mode',mode]
    return AppCommandResult.READY,command


def App_Main():
    import tkinter as tk
    from tkinter import ttk
    root=Path(__file__).resolve().parent
    try:window=tk.Tk()
    except tk.TclError as exc:
        print(f'GUI_UNAVAILABLE: {exc}\nCLI remains available: .venv\\Scripts\\python.exe compute_studies.py --group all --resume',file=sys.stderr);return 1
    window.title('Drying_Model 计算与绘图');window.geometry('1050x760')
    events=queue.Queue();process=None;closing=False;active_task=None;busy=False
    task=tk.StringVar(value='studies');group=tk.StringVar(value='all');case=tk.StringVar(value='all');mode=tk.StringVar(value='all');status=tk.StringVar(value='空闲')
    choices=ttk.Frame(window,padding=12);choices.pack(fill='x')
    selectors=[]
    for col,(text,var,values) in enumerate([('任务',task,['studies','baseline']),('实验组',group,['all','verify','postprocess','geometry','environment','thermal']),
        ('轨迹',case,['all','q1','q23','q4']),('热模式',mode,['all','M00','M10','M01','M11'])]):
        ttk.Label(choices,text=text).grid(row=0,column=col*2,padx=5)
        selector=ttk.Combobox(choices,textvariable=var,values=values,state='readonly',width=17);selector.grid(row=0,column=col*2+1);selectors.append(selector)
    ttk.Label(window,text='M00 为官方主模型；M10 仅潜热；M01 仅携热；M11 两者均计。热模式只筛选热扩展任务，其余组固定为 M00；绘图使用完整布局。').pack(anchor='w',padx=12)
    buttons=ttk.Frame(window,padding=12);buttons.pack(fill='x');controls=[];action_buttons={}
    log=tk.Text(window,height=19,font=('Consolas',10),wrap='word');log.pack(side='bottom',fill='both',expand=True,padx=12,pady=8)
    ttk.Label(window,textvariable=status).pack(anchor='w',padx=12)
    config=tk.Text(window,height=12,font=('Consolas',9),wrap='word');config.pack(fill='x',padx=12)
    snapshot=root/'work/baseline_snapshot/baseline_manifest.json'
    if snapshot.exists():
        frozen=json.loads(snapshot.read_text(encoding='utf-8'))
        view=dict(source='frozen baseline '+frozen['baseline_id'],physics=frozen['config']['physics'],
            configured_numerical_defaults=frozen['config']['numerics'],actual_production_schedules={k:dict(id=v['case_id'],schedule=v.get('schedule'),actual_cap_s=v['cap']) for k,v in frozen['selected'].items() if k.endswith('1d')})
        view['supplemental_mesh_choices']=json.loads((root/'configs/studies_numerics.json').read_text(encoding='utf-8'))
        view['analysis_rules']=json.loads((root/'configs/studies_analysis.json').read_text(encoding='utf-8'))
        config.insert('end',json.dumps(view,ensure_ascii=False,indent=2))
    else:config.insert('end','首次运行 compute_studies.py 后显示冻结基线参数。')
    config.configure(state='disabled')
    def Append(text):
        log.insert('end',text+'\n');log.see('end')
    def Worker(command):
        nonlocal process
        env=dict(os.environ,PYTHONIOENCODING='utf-8',PYTHONUNBUFFERED='1')
        try:
            process=subprocess.Popen(command,cwd=root,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,
                encoding='utf-8',errors='replace',env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            for line in process.stdout:events.put(('line',line.rstrip()))
            events.put(('done',process.wait()))
        except Exception as exc:events.put(('error',str(exc)))
    def Launch(action):
        nonlocal active_task,busy
        if busy:return
        code,command=App_BuildCommand(root,task.get(),action,group.get(),case.get(),mode.get())
        if code!=AppCommandResult.READY:Append('无法执行：'+code.name);return
        if action in ['resume','compute','payload']:
            stop=root/('work/studies/STOP' if task.get()=='studies' else 'work/studies/BASELINE_STOP');stop.unlink(missing_ok=True)
        active_task=task.get();busy=True;status.set('启动中：'+action);Append(subprocess.list2cmdline(command))
        for control in controls:control.configure(state='disabled')
        for selector in selectors:selector.configure(state='disabled')
        threading.Thread(target=Worker,args=(command,),daemon=False).start()
    def Stop():
        if busy and active_task=='studies':
            folder=root/'work/studies';folder.mkdir(parents=True,exist_ok=True);(folder/'STOP').write_text('GUI requested checkpoint stop',encoding='utf-8')
            status.set('已请求停止，等待当前输出点保存检查点。')
        elif busy:
            folder=root/'work/studies';folder.mkdir(parents=True,exist_ok=True);(folder/'BASELINE_STOP').write_text('GUI requested phase-boundary stop',encoding='utf-8')
            status.set('主任务将在当前计算阶段完成并保存检查点后停止；不会中断正在执行的数值阶段。')
    for text,action in [('计算','compute'),('恢复','resume'),('仅重画','plot'),('刷新扩展汇总','payload'),('查看计划','dry_run')]:
        button=ttk.Button(buttons,text=text,command=lambda a=action:Launch(a));button.pack(side='left',padx=4);controls.append(button);action_buttons[action]=button
    ttk.Button(buttons,text='检查点停止',command=Stop).pack(side='left',padx=4)
    ttk.Button(buttons,text='打开结果',command=lambda:os.startfile(root/'results')).pack(side='left',padx=4)
    ttk.Button(buttons,text='打开诊断',command=lambda:os.startfile(root/'work/studies/diagnostics')).pack(side='left',padx=4)
    for text,name in [('热模型假设','thermal_assumptions.md'),('水物性来源','water_properties.json')]:
        path=root/'work/studies/diagnostics'/name
        ttk.Button(buttons,text=text,command=lambda p=path:os.startfile(p),state='normal' if path.is_file() else 'disabled').pack(side='left',padx=4)
    def UpdateSelections(*_):
        if busy:return
        selectors[0].configure(state='readonly')
        for selector in selectors[1:]:selector.configure(state='readonly' if task.get()=='studies' else 'disabled')
        action_buttons['dry_run'].configure(state='normal' if task.get()=='studies' else 'disabled')
        if task.get()=='baseline':
            mode.set('M00');case.set('all');return
        allowed_cases=['q4'] if group.get()=='geometry' else ['all','q23','q4'] if group.get()=='environment' else ['all','q1','q23','q4']
        selectors[2].configure(values=allowed_cases)
        if case.get() not in allowed_cases:case.set(allowed_cases[0])
        if group.get() not in ['all','thermal']:
            mode.set('M00');selectors[3].configure(state='disabled')
        else:
            selectors[3].configure(values=['all','M10','M01','M11'])
            if mode.get()=='M00':mode.set('all')
    task.trace_add('write',UpdateSelections);group.trace_add('write',UpdateSelections);UpdateSelections()
    def Poll():
        nonlocal process,busy
        while not events.empty():
            kind,value=events.get();Append(str(value))
            if kind=='line':status.set(str(value)[-150:])
            else:
                status.set('完成' if kind=='done' and value==0 else '失败，查看日志');process=None;busy=False
                for control in controls:control.configure(state='normal')
                UpdateSelections()
        if closing and not busy:window.destroy();return
        window.after(200,Poll)
    def Close():
        nonlocal closing
        if busy:
            closing=True;Stop();status.set('等待子进程安全结束后关闭。')
        else:window.destroy()
    window.protocol('WM_DELETE_WINDOW',Close);window.after(200,Poll);window.mainloop();return 0


if __name__=='__main__':raise SystemExit(App_Main())
