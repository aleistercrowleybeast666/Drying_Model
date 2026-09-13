"""CPU/memory admission, writer locks and bottom-level scheduling; no PDE math."""
import hashlib
import json
import math


def Schedule_GetSlots(request='auto',memory_gb=None,cpu_count=None):
    import psutil
    cores=(psutil.cpu_count(logical=False) or 1) if cpu_count is None else cpu_count
    return max(1,min(6,cores-1)) if str(request)=='auto' else max(1,min(6,int(request)))


def Schedule_GetResources(request='auto',available_mb=None,cpu_count=None):
    import psutil
    available=psutil.virtual_memory().available/2**20 if available_mb is None else available_mb
    return dict(cpu_tokens=Schedule_GetSlots(request,cpu_count=cpu_count),memory_budget_mb=.72*available,
                available_memory_at_start_mb=available,memory_floor_mb=2048.)


def Schedule_GetDemand(job,slots=None):return job.get('cpu_demand',1)


def Schedule_CanStart(job,running,slots,memory_budget_mb=float('inf'),available_mb=float('inf'),floor_mb=2048.):
    if available_mb<floor_mb:return False
    if sum(Schedule_GetDemand(j) for j in running)+Schedule_GetDemand(job)>slots:return False
    memory=job.get('memory_estimate_mb',1024.)
    if memory+sum(j.get('memory_estimate_mb',1024.) for j in running)>memory_budget_mb:return False
    if memory>available_mb-floor_mb:return False
    locks=set(job.get('locks',[]))
    return not any(locks.intersection(j.get('locks',[])) or
        (job.get('private') and job.get('private')==j.get('private')) for j in running)


def Schedule_GetIdentity(job):
    """Hash effective solve spec, never a display label. Unknowns are not aliases."""
    spec=job.get('numerical_spec')
    return hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest() if job.get('pde') and spec else None


def Schedule_Deduplicate(jobs):
    canonical={};aliases={};unique=[]
    for job in jobs:
        identity=Schedule_GetIdentity(job)
        if identity and identity in canonical:
            target=canonical[identity];aliases[job['key']]=target['key']
            target['dependencies']=list(dict.fromkeys(target['dependencies']+job['dependencies']))
        else:
            job['canonical_experiment_identity']=identity;unique.append(job)
            if identity:canonical[identity]=job
    for job in unique:
        job['dependencies']=list(dict.fromkeys(aliases.get(k,k) for k in job['dependencies'] if aliases.get(k,k)!=job['key']))
    return unique,aliases


def Schedule_GetPriorities(jobs,costs):
    children={j['key']:[] for j in jobs};memo={};visiting=set()
    for job in jobs:
        for key in job['dependencies']:
            if key in children:children[key].append(job['key'])
    def Task_GetLevel(key):
        if key in visiting:raise ValueError('TASK_DAG_CYCLE: '+key)
        if key not in memo:
            visiting.add(key);memo[key]=max(0.,costs.get(key) or 1.)+max((Task_GetLevel(k) for k in children[key]),default=0.);visiting.remove(key)
        return memo[key]
    for key in children:Task_GetLevel(key)
    return memo


def Schedule_GetDispatch(jobs,priorities,costs):
    return sorted(jobs,key=lambda j:(-priorities.get(j['key'],0),-sum(j['key'] in k['dependencies'] for k in jobs),-(costs.get(j['key']) or 0),j['key']))


def Schedule_Estimate(jobs,remaining,slots,memory_budget_mb=float('inf')):
    pending={j['key']:j for j in jobs};done={};active=[];now=0.;path={};last_completed=None
    priorities=Schedule_GetPriorities(jobs,remaining)
    while pending or active:
        for job in Schedule_GetDispatch(list(pending.values()),priorities,remaining):
            key=job['key']
            if not set(job.get('dependencies',[]))<=done.keys():continue
            if not Schedule_CanStart(job,[j for _,j in active],slots,memory_budget_mb):continue
            duration=remaining.get(key)
            if duration is None or not math.isfinite(duration):return None,[]
            parents=job.get('dependencies',[]);parent=max(parents,key=lambda k:done[k]) if parents else None
            if last_completed and (parent is None or done[parent]<now):parent=last_completed
            path[key]=(path[parent] if parent else [])+[key]
            active.append((now+max(0.,duration),job));del pending[key]
        if not active:return (None,[]) if pending else (now,[])
        now=min(t for t,_ in active)
        for end,job in list(active):
            if end<=now:done[job['key']]=end;last_completed=job['key'];active.remove((end,job))
    last=max(done,key=done.get) if done else None
    return now,path.get(last,[])
