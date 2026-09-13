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
            if not row.get('cache_reused') and row.get('wall_s',0)>0:
                measured[row['key']]=dict(measured.get(row['key'],{}),wall_s=row['wall_s'])
    costs={}
    for job in plan['steps']:
        case=job.get('case','q23');base=measured.get('A.'+case,{}).get('wall_s',{'q1':10.,'q23':190.,'q4':55.}[case])
        kind=job['kind']
        factor={'original':1.,'full_production':1.3,'validation_1d':8.,'validation_2d':125.*4.,
            'experiment':3.,'mass_measure':1.5}.get(kind)
        if kind=='experiment':
            factor*=4 if job.get('experiment_kind')=='full_reference' else 2 if job.get('experiment_kind')=='time_half' else 1
        fallback=base*factor if factor else (600. if job.get('selection')=='gif' else 55. if kind=='plot' else 15.)
        costs[job['key']]=dict(weight=max(.01,float(measured.get(job['key'],{}).get('wall_s',fallback))),
            source='measured successful wall' if job['key'] in measured else 'conservative stage/cell/step cost model')
    return costs


def Progress_FormatDuration(seconds):
    if seconds is None or not math.isfinite(seconds):return '估算中'
    seconds=max(0,int(round(seconds)));hours,rest=divmod(seconds,3600);minutes,seconds=divmod(rest,60)
    return f'{hours}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes}:{seconds:02d}'


class ProgressConsole:
    def __init__(self, stream=None, machine=False, verbose=False, clock=time.monotonic):
        self.stream=stream or sys.stdout;self.machine=machine;self.verbose=verbose;self.clock=clock
        self.last=-1e30;self.line_open=False;self.width=0

    def Progress_Write(self, event):
        now=self.clock()
        terminal=event['event'] in ['run_complete','run_failed','run_stopped']
        if self.machine:
            self.stream.write(PREFIX+json.dumps(event,ensure_ascii=False)+'\n');self.stream.flush();return
        if not terminal and now-self.last<5:return
        self.last=now
        active=' | '.join(f"{r['task_label']} {r['task_fraction']*100:.1f}%" for r in event['running_tasks'])
        text=f"[{event['overall_fraction']*100:5.1f}%] "+(active or event['message'])
        text+=f" | 已用 {Progress_FormatDuration(event['elapsed_s'])} | 预计剩余 {Progress_FormatDuration(event['eta_s'])}"
        tty=bool(getattr(self.stream,'isatty',lambda:False)())
        self.stream.write(('\r'+text.ljust(self.width)) if tty else text+'\n')
        self.width=max(self.width,len(text));self.line_open=tty
        if terminal and tty:self.stream.write('\n');self.line_open=False
        self.stream.flush()

    def Progress_Log(self, line, force=False):
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
        self.jobs={j['key']:dict(j,label=j.get('label',j['key']),weight=costs[j['key']]['weight'],
            fraction=0.,status='pending',started=None,observed=False,cache_reused=False) for j in plan['steps']}
        previous=[]
        for key,label,weight in preparation if preparation is not None else PREPARATION:
            self.jobs[key]=dict(key=key,label=label,group='preparation',kind='preparation',weight=weight,
                fraction=0.,status='pending',started=None,dependencies=previous[-1:],observed=False,cache_reused=False)
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
        slots=[0.]*self.workers;finish={k:0. for k,r in self.jobs.items() if r['status']=='PASS'}
        pending={k:r for k,r in self.jobs.items() if r['status']!='PASS'}
        while pending:
            available=[(k,r) for k,r in pending.items() if set(r.get('dependencies',[]))<=finish.keys()]
            if not available:return None
            key,row=min(available,key=lambda item:(item[1]['status']!='running',item[0]))
            remaining=row['weight']*(1-row['fraction'])
            if row.get('expected_cache_hit'):remaining=min(remaining,2.)
            elapsed=now-row['started'] if row['started'] is not None else 0.
            if row['status']=='running' and not row.get('expected_cache_hit') and elapsed>10 and .05<row['fraction']<.99:
                remaining=.4*remaining+.6*elapsed*(1-row['fraction'])/row['fraction']
            ready=max([finish[k] for k in row.get('dependencies',[])]+[0.])
            if row.get('exclusive') or row['group']=='preparation':
                end=max(ready,max(slots))+remaining;slots=[end]*self.workers
            else:
                slot=min(range(self.workers),key=slots.__getitem__);end=max(ready,slots[slot])+remaining;slots[slot]=end
            finish[key]=end;del pending[key]
        return max(slots)

    def Progress_Snapshot(self):
        with self.lock:
            now=self.clock()
            for row in self.jobs.values():
                if row['status']!='running' or self.state!='running':continue
                # Exact observations hold between reports. Legacy work can use
                # a capped wall-time estimate, never an implicit PASS.
                upper=row.get('upper',.95)
                elapsed=max(0.,now-row.get('forecast_start',row['started']))
                origin=row.get('forecast_fraction',0.)
                duration=row.get('forecast_s',row['weight'])
                estimate=origin+(upper-origin)*min(.95,elapsed/max(.01,duration))
                row['fraction']=max(row['fraction'],min(upper,estimate))
            raw=sum(r['weight']*r['fraction'] for r in self.jobs.values())/max(.01,sum(r['weight'] for r in self.jobs.values()))
            self.overall=1. if self.state=='complete' else max(self.overall,min(.999,raw))
            estimate=self.Progress_GetEta(now) if self.state=='running' else 0. if self.state=='complete' else None
            if estimate is not None:
                self.eta=estimate if self.eta is None else .8*max(0.,self.eta-(now-self.last_time))+.2*estimate
            else:self.eta=None
            self.last_time=now
            active=[dict(task_key=k,task_label=r['label'],group=r['group'],task_fraction=r['fraction'],
                phase=r.get('phase',r['kind']),estimated=not r['observed']) for k,r in self.jobs.items() if r['status']=='running']
            current=self.jobs.get(self.current,{})
            return dict(schema_version=1,event={'running':'progress','complete':'run_complete','failed':'run_failed','stopped':'run_stopped'}[self.state],
                phase=current.get('phase',current.get('kind','preparation')),task_key=self.current,task_label=current.get('label','准备'),
                group=current.get('group','preparation'),task_fraction=current.get('fraction',0.),overall_fraction=self.overall,
                elapsed_s=now-self.started,eta_s=0. if self.state=='complete' else self.eta,message=self.message,running_tasks=active,
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
