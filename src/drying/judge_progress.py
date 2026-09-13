"""Display-only work accounting. Nothing in this module defines a solve identity."""
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import IntEnum
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import threading
import time
import shutil
import unicodedata

PREFIX = 'DRYING_PROGRESS '
WORKER_PREFIX = 'DRYING_TASK_PROGRESS '
PREPARATION = [('prepare.workspace','准备运行目录',.35),('prepare.inputs','读取输入',1.),
    ('prepare.mesh','校验冻结网格',.35),('prepare.jit','M00 JIT 预热',23.58)]


class ProgressRunResult(IntEnum):
    COMPLETE = 0
    FAILED = 1
    STOPPED = 2


def Progress_Hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False).encode()).hexdigest()


def Progress_ReadJson(path):
    try:
        value=json.loads(Path(path).read_text(encoding='utf-8'))
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError,TypeError):return {}


def Progress_GetIdentity(root):
    from .runtime import Runtime_GetCode, Runtime_GetData
    code=Runtime_GetCode(Path(root));data=Runtime_GetData(Path(root))
    frozen=Progress_ReadJson(code/'configs/frozen_mesh/manifest.json')
    names=['materials','boundaries','operators','rk4','sampling','inputs','events','geometry','cases','stages','table_solver']
    sources={name:hashlib.sha256((code/f'src/drying/{name}.py').read_bytes()).hexdigest() for name in names}
    mesh={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((code/'configs/frozen_mesh').glob('*')) if p.is_file()}
    return dict(numerical_sources=sources,numerical_source_hash=frozen['numerical_source_hash'],
        frozen_schedule_hash=frozen['schedule_hash'],frozen_mesh_hash=Progress_Hash(mesh),
        # Input_Prepare refreshes descriptive metadata; the solver's input hash
        # is stable for identical numerical inputs in every private workspace.
        input_hash=Progress_ReadJson(data/'input_manifest.json')['hash'],
        config_hash=hashlib.sha256((code/'configs/default.toml').read_bytes()+(code/'configs/stage_schedule.json').read_bytes()).hexdigest())


def Progress_ReadReference(root):
    """Malformed/stale display resources are always nonfatal and never touch caches."""
    from .runtime import Runtime_GetCode
    try:
        reference=Progress_ReadJson(Runtime_GetCode(Path(root))/'configs/progress_reference.json')
        seal=reference.pop('seal',None)
        if seal!=Progress_Hash(reference) or reference.get('identity')!=Progress_GetIdentity(root):return {}
        for row in reference['tasks'].values():
            if not math.isfinite(row['wall_s']) or row['wall_s']<=0:return {}
            for stage in row.get('stages',[]):
                if stage['steps']<=0 or not math.isfinite(stage['wall_s']) or stage['wall_s']<=0:return {}
        if len(reference.get('preparation',[]))!=4:return {}
        for entry,expected in zip(reference['preparation'],PREPARATION):
            if len(entry)!=3 or entry[0]!=expected[0] or not math.isfinite(entry[2]) or entry[2]<=0:return {}
        reference['seal']=seal
        return reference
    except (OSError,ValueError,TypeError,KeyError):return {}


def Progress_GetCosts(root, plan, reference):
    measured=dict(reference.get('tasks',{}))
    # Warm receipts never replace cold work estimates. Match scientific identity
    # before taking newer measured (non-cache) costs from a previous invocation.
    for path in [Path(root)/'results/recompute_timing_summary.json',Path(root)/'work/recompute/timings.json']:
        previous=Progress_ReadJson(path)
        if not reference or previous.get('progress_identity')!=reference['identity']:continue
        if not previous.get('tasks') or any(r.get('status')!='PASS' for r in previous['tasks']):continue
        for row in previous['tasks']:
            if previous.get('progress_scope_version')!=4 and not row['key'].startswith(('A.','D.M10.','D.M01.','D.M11.','D.full.')):continue
            if not row.get('cache_reused') and row.get('wall_s',0)>0:
                measured[row['key']]=dict(measured.get(row['key'],{}),wall_s=row['wall_s'])
    costs={}
    for job in plan['steps']:
        case=job.get('case','q23');base=measured.get('A.'+case,{}).get('wall_s',{'q1':10.,'q23':190.,'q4':55.}[case])
        kind=job['kind']
        factor={'original':1.,'full_production':1.3,'validation_1d':2.,'reference_1d':8.,
            'experiment':3.,'mass_measure':1.5}.get(kind)
        if kind=='experiment':
            factor*=4 if job.get('experiment_kind')=='full_reference' else 2 if job.get('experiment_kind')=='time_half' else 1
        fallback=base*factor if factor else (600. if job.get('selection')=='gif' else 55. if kind=='plot' else 15.)
        costs[job['key']]=dict(weight=max(.01,float(measured.get(job['key'],{}).get('wall_s',fallback))),
            source='measured successful wall' if job['key'] in measured else 'conservative stage/cell/step cost model',
            confidence='calibrated' if job['key'] in measured else 'rough')
        if kind.startswith('twod_'):
            from .runtime import Runtime_GetCode
            resources=Progress_ReadJson(Runtime_GetCode(Path(root))/'configs/judge_resource_reference.json')
            record=resources.get('costs',{}).get(job['key'],{}) if resources.get('identity')==reference.get('identity') else {}
            if job['key'] not in measured:
                costs[job['key']]=dict(weight=record.get('wall_s',15.),source=record.get('source','unmeasured 2D component'),
                    confidence='rough' if record or not job['pde'] else 'unknown')
        if kind=='developer_diagnostic':
            stages=reference.get('tasks',{}).get('A.'+case,{}).get('stages',[])
            units=sum(s['steps']*s['nr']*s['nz'] for s in stages)
            duration=1800 if case=='q1' else 259200
            work=duration/.25*(sum(n*(n/40)**2 for n in [40,80,160])+2*160*(160/40)**2)
            costs[job['key']]=dict(weight=base*work/max(1,units),source='fixed-grid + half-step accepted cell-work estimate',
                confidence='rough' if units else 'unknown')
        if kind in ['experiment','reference_1d'] and job['key'] not in measured and not job.get('cross'):
            from .runtime import Runtime_GetCode
            from .studies.selection import Selection_GetFactor
            code=Runtime_GetCode(Path(root));profile=Progress_ReadJson(code/'configs/progress_2d_reference.json')
            seal=profile.pop('seal',None)
            if reference and profile.get('identity')==reference['identity'] and seal==Progress_Hash(profile):
                factor=Selection_GetFactor(code,case,job.get('mode','M00'))*(2 if job.get('experiment_kind')=='full_reference' else 1)
                expected=[s['nr']*factor for s in reference['tasks']['A.'+case]['stages']]
                matches=[r for r in profile.get('trajectory_records',[]) if r['case']==case and r['mode']==job.get('mode','M00') and
                    r['kind']==job.get('experiment_kind') and r['tail_minutes']==job.get('tail_minutes',60) and [s['nr'] for s in r['schedule']]==expected]
                if matches:
                    sample=matches[-1];costs[job['key']]=dict(weight=sample['wall_s'],source=sample['source'],confidence='calibrated',accepted_steps=sample['steps'])
        if kind=='validation_2d' and job['key'] not in measured:
            from .runtime import Runtime_GetCode
            profile=Progress_ReadJson(Runtime_GetCode(Path(root))/'configs/progress_2d_reference.json')
            seal=profile.pop('seal',None)
            valid=bool(reference) and profile.get('identity')==reference['identity'] and seal==Progress_Hash(profile)
            rows=[r for r in profile.get('records',[]) if r['case']==case] if valid else []
            # Each grid/purpose contributes its measured accepted-step cell work;
            # never infer a 2D cost by multiplying a 1D wall time.
            choices={}
            for row in rows:
                key=(row['nr'],row['nz'],row['purpose'])
                if key not in choices or row['time_range'][-1]>choices[key]['time_range'][-1]:choices[key]=row
            cost=sum(r['steps']*r['nr']*r['nz']*(r['wall_s']/(r['steps']*r['nr']*r['nz'])) for r in choices.values())
            costs[job['key']]=dict(weight=max(.01,cost),source='measured 2D step-cell history' if rows else 'no matching 2D calibration',
                confidence='rough' if rows else 'unknown',samples=len(choices))
    return costs


def Progress_FormatDuration(seconds):
    if seconds is None or not math.isfinite(seconds):return '估算中'
    seconds=max(0,int(round(seconds)));hours,rest=divmod(seconds,3600);minutes,seconds=divmod(rest,60)
    return f'{hours}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes}:{seconds:02d}'


def Progress_GetConfidenceText(event):
    confidence=event.get('eta_confidence','calibrated');eta=event.get('eta_s')
    if confidence=='unknown' or eta is None:return '正在校准'
    if confidence=='rough':return f'粗略 {Progress_FormatDuration(eta*.6)}～{Progress_FormatDuration(eta*1.7)}'
    return '约 '+Progress_FormatDuration(eta)


def Progress_EnableAnsi(stream):
    if not getattr(stream,'isatty',lambda:False)():return False
    if os.name!='nt':return True
    try:
        import ctypes,msvcrt
        handle=msvcrt.get_osfhandle(stream.fileno());mode=ctypes.c_ulong()
        api=ctypes.windll.kernel32
        return bool(api.GetConsoleMode(ctypes.c_void_p(handle),ctypes.byref(mode)) and
            api.SetConsoleMode(ctypes.c_void_p(handle),mode.value|4))
    except (AttributeError,OSError,ValueError):return False


def Progress_FitLine(text,columns):
    result=[];width=0
    for char in text:
        size=0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in ['W','F'] else 1
        if width+size>max(1,columns-1):break
        result.append(char);width+=size
    return ''.join(result)


class ProgressConsole:
    def __init__(self, stream=None, machine=False, verbose=False, clock=time.monotonic,ansi=None):
        self.stream=stream or sys.stdout;self.machine=machine;self.verbose=verbose;self.clock=clock
        self.last=-1e30;self.line_open=False;self.ansi=Progress_EnableAnsi(self.stream) if ansi is None else ansi
        self.stability_seen=set()

    def Progress_Write(self, event):
        now=self.clock()
        terminal=event['event'] in ['run_complete','run_failed','run_stopped']
        if self.machine:
            self.stream.write(PREFIX+json.dumps(event,ensure_ascii=False)+'\n');self.stream.flush();return
        if not terminal and now-self.last<5:return
        self.last=now
        active=' | '.join(r['task_label']+('：计算中（进度正在校准）' if r.get('estimated') else f" {r['task_fraction']*100:.1f}%") for r in event['running_tasks'])
        confidence=event.get('progress_confidence','calibrated')
        label='正在校准' if confidence=='unknown' else f"约 {event['overall_fraction']*100:.0f}%" if confidence=='rough' else f"{event['overall_fraction']*100:5.1f}%"
        text='['+label+'] '+f"已用 {Progress_FormatDuration(event['elapsed_s'])} | 预计剩余 {Progress_GetConfidenceText(event)} | "+(active or event['message'])
        tty=bool(getattr(self.stream,'isatty',lambda:False)())
        clear='\r\x1b[2K' if self.ansi else '\r'+' '*shutil.get_terminal_size(fallback=(120,30)).columns+'\r'
        if tty:text=Progress_FitLine(text,shutil.get_terminal_size(fallback=(120,30)).columns)
        self.stream.write((clear+text) if tty else text+'\n')
        self.line_open=tty
        if terminal and tty:self.stream.write('\n');self.line_open=False
        self.stream.flush()

    def Progress_Log(self, line, force=False):
        if 'DT_LIMITED_BY_STABILITY' in line:
            dangerous=any(x in line for x in ['RK_FAILURE','REJECTION','MAX_STEPS','NONFINITE','FALLBACK','VALIDATION_FAIL'])
            try:
                payload=json.loads(line[line.index('{'):]);actual=payload.get('accepted_dt_s',payload.get('actual_dt_s'))
                dangerous|=actual is not None and actual<=10*payload.get('min_dt_s',1e-8)
            except (ValueError,TypeError):pass
            if not dangerous:
                key=line.split(']',1)[0] if line.startswith('[') else 'preparation'
                if not self.verbose and key in self.stability_seen:return
                self.stability_seen.add(key)
                line=(line.replace('WARNING','INFO')+' [NORMAL_STABILITY_LIMIT]') if self.verbose else key+'] INFO 稳定性约束已自动减小时间步（正常）'
                force=True
        if not (force or self.verbose or 'WARNING' in line or 'ERROR' in line or 'Traceback' in line):return
        if self.line_open:self.stream.write('\n');self.line_open=False
        self.stream.write(line.rstrip()+'\n');self.stream.flush()


class ProgressLogStream:
    """Keep router detail on disk while forwarding warnings on separate lines."""
    def __init__(self,detail,progress):self.detail=detail;self.progress=progress;self.buffer=''
    def write(self,text):
        self.detail.write(text);self.detail.flush();self.buffer+=text
        while '\n' in self.buffer:
            line,self.buffer=self.buffer.split('\n',1)
            with self.progress.output_lock:self.progress.console.Progress_Log(line)
        return len(text)
    def flush(self):self.detail.flush()


class ProgressTracker:
    def __init__(self, plan, costs, preparation=None, clock=time.monotonic):
        self.clock=clock;self.started=clock();self.workers=plan['worker_count'];self.state='running'
        self.memory_budget_mb=plan.get('resources',{}).get('memory_budget_mb',float('inf'))
        self.jobs={j['key']:dict(j,label=j.get('label',j['key']),weight=costs[j['key']]['weight'],
            confidence=costs[j['key']].get('confidence','calibrated'),fraction=0.,status='pending',started=None,observed=False,cache_reused=False) for j in plan['steps']}
        previous=[]
        for key,label,weight in preparation if preparation is not None else PREPARATION:
            self.jobs[key]=dict(key=key,label=label,group='preparation',kind='preparation',weight=weight,
                fraction=0.,status='pending',started=None,dependencies=previous[-1:],observed=False,cache_reused=False)
            self.jobs[key]['confidence']='calibrated'
            previous.append(key)
        self.preparation=previous;self.overall=0.;self.eta=None;self.last_time=self.started
        if previous:
            for row in self.jobs.values():
                if row['group']!='preparation' and not row.get('dependencies'):row['dependencies']=[previous[-1]]
        self.message='正在准备输入与冻结网格';self.current='';self.lock=threading.RLock()

    def Progress_Start(self,key):
        with self.lock:
            row=self.jobs[key];row.update(status='running',started=self.clock(),forecast_start=self.clock(),forecast_fraction=row['fraction'],upper=.95)
            self.current=key;self.message=row['label']

    def Progress_Update(self,key,fraction,phase=None,message=None,upper=None,expected_s=None):
        with self.lock:
            if key not in self.jobs or not math.isfinite(float(fraction)):return
            row=self.jobs[key]
            if row['status']!='running':return
            row['fraction']=max(row['fraction'],min(.99,max(0.,float(fraction))))
            row['observed']=True;row['phase']=phase or row['kind'];row['last_observation']=self.clock()
            if phase in ['accepted_steps','trajectory','mass_balance']:row['expected_cache_hit']=False
            row['upper']=row['fraction'] if upper is None else min(.99,max(row['fraction'],upper))
            row['forecast_start']=self.clock();row['forecast_fraction']=row['fraction']
            row['forecast_s']=expected_s or max(1.,row['weight']*(row['upper']-row['fraction']))
            self.current=key
            if message:self.message=message

    def Progress_FinishTask(self,key,cache_reused=False):
        with self.lock:
            row=self.jobs[key];row.update(status='PASS',fraction=1.,cache_reused=cache_reused,finished=self.clock())
            self.current=key;self.message='完成 '+row['label']

    def Progress_Terminate(self,result):
        with self.lock:
            if result==ProgressRunResult.COMPLETE and any(r['status']!='PASS' for r in self.jobs.values()):
                raise ValueError('PROGRESS_COMPLETION_REQUIRES_ALL_RECEIPTS')
            self.state={ProgressRunResult.COMPLETE:'complete',ProgressRunResult.FAILED:'failed',ProgressRunResult.STOPPED:'stopped'}[result]
            self.message={'complete':'所选任务已完成并通过检查','failed':'任务失败，请查看日志','stopped':'复算已停止，保留已完成进度'}[self.state]

    def Progress_GetEta(self,now):
        from .judge_schedule import Schedule_Estimate
        jobs=[];remaining={};unfinished={k for k,r in self.jobs.items() if r['status']!='PASS'}
        for key,row in self.jobs.items():
            if key not in unfinished:continue
            jobs.append(dict(row,dependencies=[d for d in row.get('dependencies',[]) if d in unfinished]))
            duration=row['weight']*(1-row['fraction'])
            elapsed=now-row['started'] if row['started'] is not None else 0.
            if row.get('expected_cache_hit'):duration=min(duration,2.)
            elif row['status']=='running' and row['observed'] and .01<row['fraction']<.99:
                duration=.25*duration+.75*elapsed*(1-row['fraction'])/row['fraction']
            elif row['status']=='running':duration=max(duration-elapsed,elapsed*.5,1.)
            remaining[key]=None if row.get('confidence')=='unknown' else duration
        jobs.sort(key=lambda r:r['status']!='running')
        return Schedule_Estimate(jobs,remaining,self.workers,self.memory_budget_mb)[0]

    def Progress_Snapshot(self):
        with self.lock:
            now=self.clock();elapsed=now-self.started
            # Task fractions are structural evidence only. Wall-time/ETA never
            # mutate them, including when a legacy task runs longer than expected.
            estimate=(None if getattr(self,'memory_waiting',False) else self.Progress_GetEta(now)) if self.state=='running' else 0. if self.state=='complete' else None
            if estimate is not None:
                self.eta=estimate if self.eta is None else .8*max(0.,self.eta-(now-self.last_time))+.2*estimate
            else:self.eta=None
            self.last_time=now
            ranks={'measured':0,'calibrated':1,'rough':2,'unknown':3}
            confidence=max((r.get('confidence','unknown') for r in self.jobs.values() if r['status']!='PASS'),key=ranks.get,default='measured')
            if self.eta is None:confidence='unknown'
            implied=elapsed/(elapsed+self.eta) if self.eta is not None and elapsed+self.eta>0 else 0.
            self.overall=1. if self.state=='complete' else max(self.overall,min(.999,implied))
            measured=all(r['observed'] and r.get('confidence') in ['measured','calibrated'] for r in self.jobs.values() if r['status']=='running')
            progress_confidence=confidence
            if confidence!='measured' and abs(self.overall-implied)>.20:progress_confidence='unknown'
            if self.overall>.7 and self.eta is not None and self.eta>elapsed and not measured:progress_confidence='unknown'
            active=[dict(task_key=k,task_label=r['label'],group=r['group'],task_fraction=r['fraction'],
                phase=r.get('phase',r['kind']),estimated=not r['observed'],status='RUNNING' if r['observed'] else 'CALIBRATING')
                for k,r in self.jobs.items() if r['status']=='running']
            current=self.jobs.get(self.current,{})
            return dict(schema_version=1,event={'running':'progress','complete':'run_complete','failed':'run_failed','stopped':'run_stopped'}[self.state],
                phase=current.get('phase',current.get('kind','preparation')),task_key=self.current,task_label=current.get('label','准备'),
                group=current.get('group','preparation'),task_fraction=current.get('fraction',0.),overall_fraction=self.overall,
                structural_fraction=sum(r['weight']*r['fraction'] for r in self.jobs.values())/max(.01,sum(r['weight'] for r in self.jobs.values())),
                progress_confidence='measured' if self.state=='complete' else progress_confidence,eta_confidence=confidence,
                ETA_raw=estimate,ETA_display=self.eta,all_critical_measured=measured,
                elapsed_s=elapsed,eta_s=0. if self.state=='complete' else self.eta,message=self.message,running_tasks=active,
                completed_tasks=sum(r['status']=='PASS' for r in self.jobs.values()),total_tasks=len(self.jobs),
                cache_reused=bool(current.get('cache_reused')))


class ProgressSession:
    """One heartbeat serves console, GUI and the external-run snapshot."""
    def __init__(self,root,plan,console):
        self.root=Path(root);self.reference=Progress_ReadReference(root);self.console=console
        self.costs=Progress_GetCosts(root,plan,self.reference)
        prep=self.reference.get('preparation',PREPARATION)
        previous=Progress_ReadJson(self.root/'work/recompute/timings.json')
        measured=previous.get('progress',{}).get('preparation_phases_s',{})
        if (self.reference and previous.get('progress_identity')==self.reference['identity'] and
            all(r.get('status')=='PASS' for r in previous.get('tasks',[])) and
            (self.root/'work/recompute/numba_cache').exists()):
            prep=[(key,label,max(.01,float(measured.get(key,cost)))) for key,label,cost in prep]
        self.tracker=ProgressTracker(plan,self.costs,prep);self.stop=threading.Event();self.thread=None
        self.events=[];self.output_lock=threading.RLock();self.phase_times={}
        self.reporting_wall_s=0.
        self.path=self.root/'work/recompute/progress.json';self.path.parent.mkdir(parents=True,exist_ok=True)
        (self.root/'logs').mkdir(exist_ok=True)
        self.log=(self.root/'logs/progress.jsonl').open('w',encoding='utf-8')
        self.pid=os.getpid();self.run_id=str(time.time_ns())
        import psutil
        self.created_at=psutil.Process().create_time()

    def Progress_Emit(self):
        with self.output_lock:
            started=time.perf_counter()
            event=self.tracker.Progress_Snapshot();event.update(run_id=self.run_id,runner_pid=self.pid,runner_created_at=self.created_at)
            self.events.append(dict(elapsed_s=event['elapsed_s'],overall_fraction=event['overall_fraction'],eta_s=event['eta_s']))
            text=json.dumps(event,ensure_ascii=False,allow_nan=False)
            self.log.write(text+'\n');self.log.flush()
            temporary=self.path.with_suffix('.json.tmp');temporary.write_text(text,encoding='utf-8');os.replace(temporary,self.path)
            self.console.Progress_Write(event)
            self.reporting_wall_s+=time.perf_counter()-started

    def Progress_Begin(self):
        self.Progress_Emit()
        def Heartbeat_Run():
            while not self.stop.wait(1.):
                try:self.Progress_Emit()
                except OSError:pass  # Display I/O cannot invalidate science.
        self.thread=threading.Thread(target=Heartbeat_Run,daemon=True);self.thread.start()

    @contextmanager
    def Progress_Phase(self,key):
        self.tracker.Progress_Start(key);started=time.monotonic();self.Progress_Emit()
        yield
        self.phase_times[key]=time.monotonic()-started;self.tracker.Progress_FinishTask(key);self.Progress_Emit()

    def Progress_WorkerLine(self,key,line):
        if line.startswith(WORKER_PREFIX):
            try:
                value=json.loads(line[len(WORKER_PREFIX):])
                self.tracker.Progress_Update(key,value['task_fraction'],value.get('phase'),value.get('message'),value.get('upper_fraction'),value.get('expected_phase_s'))
            except (ValueError,KeyError,TypeError):pass
        else:
            with self.output_lock:self.console.Progress_Log('['+key+'] '+line)

    def Progress_End(self,result):
        self.stop.set()
        if self.thread:self.thread.join(timeout=3)
        self.tracker.Progress_Terminate(result);self.Progress_Emit();self.log.close()
        events=self.events;last=events[-2] if len(events)>1 else events[-1]
        return dict(event_count=len(events),max_update_gap_s=max((b['elapsed_s']-a['elapsed_s'] for a,b in zip(events,events[1:])),default=0.),
            monotonic=all(a['overall_fraction']<=b['overall_fraction'] for a,b in zip(events,events[1:])),
            final_fraction=events[-1]['overall_fraction'],last_eta_error_s=None if last['eta_s'] is None else last['eta_s']-(events[-1]['elapsed_s']-last['elapsed_s']),
            costs=self.costs,preparation_phases_s=self.phase_times,reference_valid=bool(self.reference),
            reference_source=self.reference.get('source_run'),identity=self.reference.get('identity'),
            parent_reporting_wall_s=self.reporting_wall_s)
