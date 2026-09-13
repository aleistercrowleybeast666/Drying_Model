"""Terminal-only, read-only structural progress. Never imports a numerical solver."""
from datetime import datetime
import json
import math
from pathlib import Path
import platform
import sys
import time


def OfficialProgress_Read(path):
    try:
        value=json.loads(Path(path).read_text(encoding='utf-8'))
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError):return {}


def OfficialProgress_GetMachine():
    import psutil
    return dict(host=platform.node(),system=platform.system(),machine=platform.machine(),
        processor=platform.processor(),logical_cpus=psutil.cpu_count())


def OfficialProgress_GetWork(schedule,end,at=None):
    at=end if at is None else max(0.,min(end,float(at)))
    return sum(max(0.,min(at,end,float(s['t_end']) if s['t_end'] is not None else end)-float(s['t_start']))
        *float(s['nr'])**3 for s in schedule)


def OfficialProgress_GetCaseFraction(root,case,schedule,end,previous=None,since_ns=0):
    """Read only the current table parent and its fingerprint-matched stageparts."""
    previous=previous or dict(fraction=0.,simulated_time_s=0.)
    folder=Path(root)/'work/runtime'/case/'work/cache'
    candidates=[]
    for path in folder.glob(case+'_1d_stage_schedule_table_*/status.json'):
        try:
            stamp=path.stat().st_mtime_ns
            if stamp>=since_ns:candidates.append((stamp,path))
        except OSError:continue
    if not candidates:return dict(previous)
    parent=OfficialProgress_Read(max(candidates,key=lambda p:p[0])[1])
    if parent.get('case')!=case or parent.get('purpose')!='table_production':return dict(previous)
    fingerprint=parent.get('fingerprint','')[:12]
    if not fingerprint:return dict(previous)
    actual=parent.get('schedule') or schedule
    simulated=float(parent.get('simulated_time_s',0.));stage_index=0
    for i,stage in enumerate(actual):
        for path in folder.glob(f'*stagepart_{fingerprint}_{i}/status.json'):
            child=OfficialProgress_Read(path)
            if child.get('case')!=case or child.get('tag')!=f'stagepart_{fingerprint}_{i}':continue
            if child.get('nr')!=stage['nr'] or float(child.get('start_time',0))!=float(stage['t_start']):continue
            at=float(child.get('simulated_time_s',stage['t_start']))
            if math.isfinite(at) and at>simulated:simulated=at;stage_index=i
    if not math.isfinite(simulated):return dict(previous)
    total=OfficialProgress_GetWork(actual,end)
    fraction=OfficialProgress_GetWork(actual,end,simulated)/max(1.,total)
    return dict(fraction=min(.999,max(previous.get('fraction',0.),fraction)),
        simulated_time_s=max(previous.get('simulated_time_s',0.),simulated),stage_index=stage_index,
        parent_case_id=parent.get('case_id'),expected_work=total)


def OfficialProgress_GetHistory(previous,identity,cases,machine):
    if previous.get('status')!='PASS' or previous.get('scientific_identity')!=identity or previous.get('machine')!=machine:return {}
    if not set(cases)<=set(previous.get('selected_cases',[])):return {}
    rows={r['case']:r for r in previous.get('cases',[]) if r.get('status')=='PASS'}
    if not set(previous['selected_cases'])<=rows.keys():return {}
    return {case:float(rows[case]['wall_s']) for case in cases
        if not rows[case].get('cache_reused') and math.isfinite(float(rows[case].get('wall_s',0))) and rows[case]['wall_s']>0}


def OfficialProgress_FormatTime(seconds):
    seconds=max(0,int(math.ceil(seconds)))
    hours,seconds=divmod(seconds,3600);minutes,seconds=divmod(seconds,60)
    return f'{hours}:{minutes:02}:{seconds:02}' if hours else f'{minutes}:{seconds:02}'


class OfficialProgress:
    def __init__(self,root,code,cases,identity,previous,slots,clock=time.perf_counter,stream=None):
        self.root=Path(root);self.cases=list(cases);self.slots=slots;self.clock=clock
        self.started=clock();self.stream=sys.stdout if stream is None else stream
        self.tty=bool(self.stream and self.stream.isatty());self.last_output=None;self.width=0
        self.machine=OfficialProgress_GetMachine();self.history=OfficialProgress_GetHistory(previous,identity,cases,self.machine)
        self.schedule=OfficialProgress_Read(Path(code)/'configs/stage_schedule.json')
        reference=OfficialProgress_Read(Path(code)/'configs/table_reference/manifest.json')['questions']
        self.ends=dict(q1=1800.,q23=reference['3']['event']['report_s'],q4=reference['4']['event']['report_s'])
        self.states={c:dict(fraction=0.,simulated_time_s=0.,state='PENDING') for c in cases}
        self.starts={};self.since={};self.samples={};self.speeds={};self.last_fraction=0.

    def OfficialProgress_StartCase(self,case):
        self.starts[case]=self.clock();self.since[case]=time.time_ns()
        self.states[case]['state']='RUNNING'

    def OfficialProgress_CompleteCase(self,case,record):
        self.states[case].update(fraction=1.,simulated_time_s=record['production'].get('actual_end_s',self.ends[case]),
            state='CACHED' if record.get('cache_reused') else 'COMPLETE')

    def OfficialProgress_GetSnapshot(self,outcome='RUNNING'):
        now=self.clock();remaining={};confidence='calibrated';rates=[]
        for case,row in self.states.items():
            if row['state']=='RUNNING':
                try:row.update(OfficialProgress_GetCaseFraction(self.root,case,self.schedule[case],self.ends[case],row,self.since[case]))
                except (OSError,ValueError,TypeError,KeyError):pass
                fraction=row['fraction'];wall=now-self.starts[case]
                baseline=self.samples.setdefault(case,(now,fraction))
                span=now-baseline[0];advance=fraction-baseline[1]
                if span>=8 and advance>=.02:
                    self.speeds[case]=(advance/span,now,fraction);self.samples[case]=(now,fraction)
                speed=self.speeds.get(case)
                # No new state means no fictional countdown. Stale observations
                # revert to calibration while the last real fraction stays put.
                if speed and now-speed[1]<=15:
                    remaining[case]=(1-fraction)/speed[0];rates.append(speed[0]*OfficialProgress_GetWork(self.schedule[case],self.ends[case]))
                    confidence='observed'
                elif case in self.history:
                    remaining[case]=self.history[case]*(1-fraction)
                else:remaining[case]=None
            elif row['state'] in ['COMPLETE','CACHED']:remaining[case]=0.
        for case,row in self.states.items():
            if row['state']=='PENDING':
                remaining[case]=self.history.get(case)
                if remaining[case] is None and rates:
                    remaining[case]=OfficialProgress_GetWork(self.schedule[case],self.ends[case])/min(rates)
                    confidence='rough'
        unfinished=[c for c in self.cases if self.states[c]['state'] not in ['COMPLETE','CACHED']]
        eta=None
        if all(remaining.get(c) is not None for c in unfinished):
            # Pessimistic admission: running tasks finish, then pending tasks
            # run serially. This upper estimate also covers memory throttling.
            eta=max([remaining[c] for c in unfinished if self.states[c]['state']=='RUNNING'] or [0.])
            eta+=sum(remaining[c] for c in unfinished if self.states[c]['state']=='PENDING')
        else:confidence='calibrating'
        total=sum(OfficialProgress_GetWork(self.schedule[c],self.ends[c]) for c in self.cases)
        fraction=sum(OfficialProgress_GetWork(self.schedule[c],self.ends[c])*self.states[c]['fraction'] for c in self.cases)/max(1.,total)
        fraction=1. if outcome=='PASS' else min(.999,max(self.last_fraction,fraction));self.last_fraction=fraction
        if outcome in ['FAIL','STOPPED']:
            eta=None;confidence='unavailable'
            for row in self.states.values():
                if row['state'] not in ['COMPLETE','CACHED']:row['state']=outcome
        return dict(timestamp=datetime.now().astimezone().isoformat(timespec='seconds'),elapsed_s=now-self.started,
            overall_fraction=fraction,eta_s=0. if outcome=='PASS' else eta,
            eta_confidence='complete' if outcome=='PASS' else confidence,status=outcome,cases={c:dict(r) for c,r in self.states.items()})

    def OfficialProgress_Write(self,outcome='RUNNING',force=False):
        now=self.clock()
        if not force and self.last_output is not None and now-self.last_output<(2 if self.tty else 6):return
        self.last_output=now;event=self.OfficialProgress_GetSnapshot(outcome)
        eta='正在校准' if event['eta_s'] is None else ('粗略约 ' if event['eta_confidence']=='rough' else '约 ')+OfficialProgress_FormatTime(event['eta_s'])
        if outcome in ['FAIL','STOPPED']:eta='已停止估计'
        labels={'q1':'问题1','q23':'问题2/3','q4':'问题4'}
        parts=[f"[{event['overall_fraction']*100:5.1f}%] 已用 {OfficialProgress_FormatTime(event['elapsed_s'])}", '预计剩余 '+eta]
        parts += [labels[c]+f" {event['cases'][c]['fraction']*100:.1f}%" for c in self.cases]
        message=' | '.join(parts)
        if self.stream:
            if self.tty:
                width=sum(2 if ord(c)>255 else 1 for c in message)
                self.stream.write('\r'+message+' '*max(0,self.width-width));self.width=width
                if outcome!='RUNNING':self.stream.write('\n')
            else:self.stream.write(message+'\n')
            self.stream.flush()
        folder=self.root/'logs';folder.mkdir(parents=True,exist_ok=True)
        with (folder/'progress.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(event,ensure_ascii=False)+'\n')
        with (folder/'console.log').open('a',encoding='utf-8') as stream:stream.write(message+'\n')
        return event
