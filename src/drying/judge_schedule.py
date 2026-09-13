"""Display cost / resource scheduling; no numerical decisions or cache aliases."""
import hashlib
import json
import math
from pathlib import Path


def Schedule_GetSlots(request='auto',memory_gb=None,cpu_count=None):
    if str(request)!='auto':return max(1,min(3,int(request)))
    import psutil
    memory_gb=math.ceil(psutil.virtual_memory().total/2**30) if memory_gb is None else memory_gb
    cpu_count=psutil.cpu_count(logical=False) or 1 if cpu_count is None else cpu_count
    return min(cpu_count,1 if memory_gb<8 else 2 if memory_gb<16 else 3)


def Schedule_GetDemand(job,slots):
    return slots if job.get('exclusive') else min(slots,job.get('slots',2 if job['kind']=='validation_2d' else 1))


def Schedule_CanStart(job,running,slots):
    demand=Schedule_GetDemand(job,slots)
    return demand+sum(Schedule_GetDemand(j,slots) for j in running)<=slots and not any(
        job.get('private') and job.get('private')==j.get('private') for j in running)


def Schedule_GetIdentity(job):
    """Logical identity only. Actual worker still verifies the full numerical spec."""
    if not job.get('pde'):return None
    keys=['case','mode','kind','experiment_kind','factor','horizon','replay','tail_minutes','cross','purpose']
    value={k:job.get(k) for k in keys};value['dt_max']=.125 if job.get('experiment_kind')=='time_half' else .25
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def Schedule_Deduplicate(jobs):
    canonical={};aliases={};unique=[]
    for job in jobs:
        identity=Schedule_GetIdentity(job)
        if identity and identity in canonical:
            aliases[job['key']]=canonical[identity]['key']
            canonical[identity]['dependencies']=list(dict.fromkeys(canonical[identity]['dependencies']+job['dependencies']))
        else:
            job['canonical_experiment_identity']=identity
            unique.append(job)
            if identity:canonical[identity]=job
    for job in unique:
        job['dependencies']=list(dict.fromkeys(aliases.get(k,k) for k in job['dependencies'] if aliases.get(k,k)!=job['key']))
    return unique,aliases


def Schedule_Estimate(jobs,remaining,slots):
    """Deterministic event simulation with resource capacity and dependency edges."""
    pending={j['key']:j for j in jobs};done={};active=[];now=0.;path={};last_completed=None
    while pending or active:
        ready_exclusive=next((j for j in pending.values() if j.get('exclusive') and set(j.get('dependencies',[]))<=done.keys()),None)
        dispatch=sorted(pending.items(),key=lambda item:(item[1] is not ready_exclusive,item[1]['kind']!='mass_measure'))
        for key,job in dispatch:
            if ready_exclusive is not None and job is not ready_exclusive:continue
            if not set(job.get('dependencies',[]))<=done.keys():continue
            if not Schedule_CanStart(job,[j for _,j in active],slots):continue
            duration=remaining.get(key)
            if duration is None or not math.isfinite(duration):return None,[]
            parents=job.get('dependencies',[])
            parent=max(parents,key=lambda k:done[k]) if parents else None
            if last_completed and (parent is None or done[parent]<now):parent=last_completed
            path[key]=(path[parent] if parent else [])+[key]
            active.append((now+max(0.,duration),job));del pending[key]
        if not active:return (None,[]) if pending else (now,[])
        now=min(t for t,_ in active)
        for end,job in list(active):
            if end<=now:
                done[job['key']]=end;last_completed=job['key'];active.remove((end,job))
    last=max(done,key=done.get) if done else None
    return now,path.get(last,[])
