"""Resource-aware DAG execution with same-runtime persistent numerical workers."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid
import psutil
from .runtime import Runtime_BuildRecomputeCommand
from .storage import Storage_WriteJson
from .judge_schedule import Schedule_CanStart,Schedule_GetDispatch,Schedule_GetPriorities,Schedule_Estimate
from .judge_worker import Worker_GetEnvironment


def Executor_Run(root,runtime,plan,progress=None):
    from .judge_pipeline import Judge_ReadJson,Judge_GetTime,Judge_PreparePrivate,Judge_MergeWorker,Judge_PublishOriginal
    from .judge_progress import Progress_GetCosts,Progress_ReadReference,Progress_GetIdentity
    root=Path(root);pending=list(plan['steps']);running={};done=set();records=[];pool=[]
    clock=time.perf_counter();started=Judge_GetTime();identity=Progress_GetIdentity(root)
    receipts=runtime/'work/recompute/receipts';taskdir=runtime/'work/recompute/tasks';logdir=root/'logs'
    for folder in [receipts,taskdir,logdir]:folder.mkdir(parents=True,exist_ok=True)
    costs={k:v['weight'] for k,v in Progress_GetCosts(root,plan,Progress_ReadReference(root)).items()}
    priorities=Schedule_GetPriorities(plan['steps'],costs);resources=plan['resources']
    env=Worker_GetEnvironment(root);flags=(subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS) if os.name=='nt' else 0
    max_workers=0;memory_peak=0.;idle=0.;memory_wait=0.;dependency_idle=0.;memory_idle=0.;last=time.perf_counter();launched=0;pooled_tasks=0
    def Process_Close(entry,force=False):
        process=entry['process']
        if process.poll() is None:
            if entry.get('persistent') and not force:
                try:process.stdin.write('{"command":"shutdown"}\n');process.stdin.flush();process.wait(timeout=5)
                except (OSError,subprocess.TimeoutExpired):process.kill();process.wait(timeout=5)
            else:
                try:
                    owned=psutil.Process(process.pid)
                    for child in owned.children(recursive=True):child.kill()
                    owned.kill();process.wait(timeout=5)
                except (psutil.NoSuchProcess,subprocess.TimeoutExpired):pass
        if process.stdin:process.stdin.close()
        if entry.get('pool_log'):entry['pool_log'].close()
    def Timings_Save():
        from datetime import datetime
        wall=time.perf_counter()-clock
        actual={j['key']:next((r['wall_s'] for r in records if r['key']==j['key']),costs[j['key']]) for j in plan['steps']}
        makespan,path=Schedule_Estimate(plan['steps'],actual,plan['worker_count'],resources['memory_budget_mb'])
        group_wall={}
        for group in ['original','validation','plot','extension']:
            merged=[]
            for left,right in sorted((datetime.fromisoformat(r['started_at']).timestamp(),datetime.fromisoformat(r['finished_at']).timestamp()) for r in records if r['group']==group):
                if merged and left<=merged[-1][1]:merged[-1][1]=max(merged[-1][1],right)
                else:merged.append([left,right])
            group_wall[group]=sum(b-a for a,b in merged)
        value=dict(started_at=started,finished_at=Judge_GetTime(),wall_s=wall,workers=plan['worker_count'],tasks=records,
            group_worker_wall_s={g:sum(r['wall_s'] for r in records if r['group']==g) for g in ['original','validation','plot','extension']},
            group_wall_s=group_wall,progress_identity=identity,progress_scope_version=4,resources=resources,
            critical_path=path,predicted_makespan_s=makespan,worker_processes_launched=launched,persistent_tasks=pooled_tasks,
            max_concurrent_workers=max_workers,memory_high_water_mb=memory_peak,
            startup_overhead_s=sum(r.get('startup_s',0) for r in records),
            cpu_utilization_proxy=sum(r.get('cpu_time_s',0) for r in records)/max(.001,wall*plan['worker_count']),
            idle_cpu_token_s=idle,memory_wait_s=memory_wait,dependency_or_lock_idle_cpu_token_s=dependency_idle,memory_idle_cpu_token_s=memory_idle,
            persistent_saved_startup_estimate_s=max(0,pooled_tasks-len({r['worker_pid'] for r in records if r.get('persistent')}))*
                (sum(r.get('startup_s',0) for r in records if r.get('startup_s',0)>0)/max(1,sum(r.get('startup_s',0)>0 for r in records))),
            timing_note='RSS and idle-cause attribution are scheduler snapshots; dependency/lock and memory idle are approximate. Saved startup is an estimate, not measured saved total wall.')
        Storage_WriteJson(root/'work/recompute/timings.json',value)
        Storage_WriteJson(runtime/'results/recompute_timing_summary.json',value)
        if plan.get('developer_full_audit'):Storage_WriteJson(runtime/'results/developer_full_audit_timing.json',value)
        return value
    try:
        while pending or running:
            now=time.perf_counter();interval=now-last;last=now
            idle+=max(0,plan['worker_count']-len(running))*interval
            ready=[j for j in pending if set(j['dependencies'])<=done]
            if any(Schedule_CanStart(j,[e['admission'] for e in running.values()],plan['worker_count']) for j in ready):
                memory_idle+=max(0,plan['worker_count']-len(running))*interval
            else:dependency_idle+=max(0,plan['worker_count']-len(running))*interval
            live={e['process'].pid:e['process'] for e in pool+list(running.values())}
            rss={}
            for pid,p in live.items():
                try:
                    parent=psutil.Process(pid)
                    rss[pid]=sum(child.memory_info().rss for child in [parent,*parent.children(recursive=True)])/2**20
                except psutil.NoSuchProcess:pass
            memory_peak=max(memory_peak,sum(rss.values()));available=psutil.virtual_memory().available/2**20
            for pid,entry in running.items():
                entry['admission']['memory_estimate_mb']=max(entry['admission']['memory_estimate_mb'],rss.get(pid,0))
            dispatched=False
            for job in Schedule_GetDispatch(pending,priorities,costs):
                if not set(job['dependencies'])<=done:continue
                idles=[e for e in pool if not e['busy'] and e['process'].poll() is None]
                reuse=idles[0] if job.get('persistent') and idles else None
                resident=sum(rss.get(e['process'].pid,0) for e in idles if e is not reuse)
                admission=dict(job,memory_estimate_mb=max(job['memory_estimate_mb'],rss.get(reuse['process'].pid,0)) if reuse else job['memory_estimate_mb'])
                free_with_reuse=available+(rss.get(reuse['process'].pid,0) if reuse else 0)
                if not Schedule_CanStart(admission,[e['admission'] for e in running.values()],plan['worker_count'],
                        resources['memory_budget_mb']-resident,free_with_reuse,resources['memory_floor_mb']):
                    if idles and reuse is None:
                        Process_Close(idles[-1]);pool.remove(idles[-1])
                    continue
                private=job.get('private')
                if private and job.get('force_reference'):private=private+'_force_'+str(time.time_ns())
                workspace=Judge_PreparePrivate(runtime,private,source_case=job.get('case'),include_twod=job['kind'].startswith('twod_') and job['kind']!='twod_base') if private else runtime
                token=uuid.uuid4().hex;logpath=logdir/(job['key']+'.log');logpath.write_text('',encoding='utf-8')
                task=dict(job,workspace=workspace.relative_to(root).as_posix(),runtime=runtime.relative_to(root).as_posix(),
                    receipt=(receipts/(job['key']+'.json')).relative_to(root).as_posix(),log_path=logpath.relative_to(root).as_posix(),
                    run_token=token,progress_identity=identity)
                taskpath=taskdir/(job['key']+'.json');Storage_WriteJson(taskpath,task)
                sent=time.time();log=None
                if job.get('persistent'):
                    if reuse is None:
                        plog=(logdir/('pool_'+uuid.uuid4().hex+'.log')).open('w',encoding='utf-8')
                        process=subprocess.Popen(Runtime_BuildRecomputeCommand(['--persistent-worker'],root),cwd=root,env=env,
                            stdin=subprocess.PIPE,stdout=plog,stderr=subprocess.STDOUT,text=True,encoding='utf-8',creationflags=flags)
                        reuse=dict(process=process,busy=False,persistent=True,pool_log=plog);pool.append(reuse);launched+=1
                    reuse['busy']=True;process=reuse['process'];process.stdin.write(json.dumps(dict(task_file=taskpath.relative_to(root).as_posix(),sent_at=sent))+'\n');process.stdin.flush();pooled_tasks+=1
                else:
                    log=logpath.open('w',encoding='utf-8')
                    process=subprocess.Popen(Runtime_BuildRecomputeCommand(['--worker-json',taskpath.relative_to(root).as_posix()],root),
                        cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=flags);launched+=1
                running[process.pid]=dict(process=process,job=job,admission=admission,workspace=workspace,log=log,
                    log_path=logpath,position=0,buffer='',persistent=bool(reuse),pool_entry=reuse,token=token,sent_at=sent)
                pending.remove(job);dispatched=True;available=psutil.virtual_memory().available/2**20
                if progress:
                    progress.tracker.memory_waiting=False
                    progress.tracker.Progress_Start(job['key']);progress.Progress_Emit()
            max_workers=max(max_workers,len(running))
            for pid,entry in list(running.items()):
                with entry['log_path'].open(encoding='utf-8',errors='replace') as stream:
                    stream.seek(entry['position']);text=stream.read();entry['position']=stream.tell()
                entry['buffer']+=text
                while '\n' in entry['buffer']:
                    line,entry['buffer']=entry['buffer'].split('\n',1)
                    if progress:progress.Progress_WorkerLine(entry['job']['key'],line)
                    else:print(line,flush=True)
                job=entry['job'];receipt=Judge_ReadJson(receipts/(job['key']+'.json'));valid=receipt.get('run_token')==entry['token']
                code=entry['process'].poll()
                if not valid and code is None:continue
                if not valid or receipt.get('status')!='PASS':raise RuntimeError('TASK_FAILED: '+job['key']+'; see '+str(entry['log_path']))
                entry['completed']=True
                # Parent index merges serialize with only the conflicting writers.
                if any(not e.get('completed') and set(e['job'].get('locks',[]))&{'validation_summary','study_index','results_publish'} for p,e in running.items() if p!=pid):continue
                if entry['log']:entry['log'].close()
                if entry['persistent']:entry['pool_entry']['busy']=False
                else:
                    entry['process'].wait(timeout=10)
                    from datetime import datetime
                    receipt['startup_s']=max(0.,datetime.fromisoformat(receipt['started_at']).timestamp()-entry['sent_at'])
                    Storage_WriteJson(receipts/(job['key']+'.json'),receipt)
                Judge_MergeWorker(runtime,job,entry['workspace'],receipt);records.append(receipt);done.add(job['key']);del running[pid]
                if job['group'] in ['original','validation']:Judge_PublishOriginal(runtime)
                Timings_Save()
                if not any(set(e['job'].get('locks',[]))&{'study_outputs','original_render','results_publish'} for e in running.values()):
                    shutil.copytree(runtime/'results',root/'results',dirs_exist_ok=True)
                if progress:progress.tracker.Progress_FinishTask(job['key'],receipt.get('cache_reused',False));progress.Progress_Emit()
            if pending and not running and not dispatched:
                if not any(set(j['dependencies'])<=done for j in pending):raise RuntimeError('TASK_DAG_UNRESOLVED')
                memory_wait+=interval
                if progress:
                    progress.tracker.memory_waiting=True
                    progress.tracker.message='等待可用内存（保留至少 2 GB），任务进度保持不变'
            if pending or running:time.sleep(.25)
        value=Timings_Save();shutil.copytree(runtime/'results',root/'results',dirs_exist_ok=True);return value
    finally:
        for entry in running.values():
            if not entry['persistent']:Process_Close(entry,True)
            if entry.get('log'):entry['log'].close()
        for entry in pool:Process_Close(entry,bool(running))
        Timings_Save()
