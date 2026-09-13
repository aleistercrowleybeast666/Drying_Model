"""Scoped, read-only observers around existing completed calculation blocks.

The original callable is invoked exactly once with untouched arguments. Numerical
modules, RK4 loops, output partitions and their source fingerprints stay unchanged.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import json
import sys
import time

from .judge_progress import Progress_ReadReference, WORKER_PREFIX

_CURRENT = ContextVar('judge_display_observer',default=None)


def Progress_Substep(fraction, message, phase='publish', upper=None, expected_s=None):
    observer=_CURRENT.get()
    if observer is not None:observer.Progress_Report(fraction,message,phase,upper,expected_s,force=True)


def Progress_PlotStep(completed,total,message):
    observer=_CURRENT.get()
    if observer is not None:observer.Progress_Report(.05+.9*completed/max(1,total),message,'render',force=True)


class TaskObserver:
    def __init__(self,root,task):
        started=time.perf_counter()
        self.task=task;self.reference=Progress_ReadReference(root);self.last=-1e30;self.fraction=0.
        self.profile=self.reference.get('tasks',{}).get('A.'+task.get('case',''),{})
        self.lower=0.;self.upper=.95;self.gif_completed=0
        self.kernel_calls=0;self.reporting_wall_s=time.perf_counter()-started

    def Progress_Report(self,fraction,message,phase='solve',upper=None,expected_s=None,force=False,**detail):
        now=time.monotonic()
        if not force and now-self.last<1.5:return
        started=time.perf_counter()
        self.last=now;self.fraction=max(self.fraction,min(.99,max(0.,fraction)))
        value=dict(schema_version=1,event='task_progress',task_key=self.task['key'],task_fraction=self.fraction,
            phase=phase,message=message,upper_fraction=upper,expected_phase_s=expected_s,
            reference_valid=bool(self.reference),**detail)
        try:print(WORKER_PREFIX+json.dumps(value,ensure_ascii=False,allow_nan=False),flush=True)
        except (OSError,ValueError):pass
        self.reporting_wall_s+=time.perf_counter()-started

    def Progress_ObserveBlock(self,frame,result):
        self.kernel_calls+=1
        if time.monotonic()-self.last<1.5:return
        try:
            if frame.f_code.co_name=='Advance':frame=frame.f_back
            name=frame.f_code.co_name;values=frame.f_locals
            if name=='Table_SolveSegment' and len(result[2]) and result[4]==0:
                rows=self.profile.get('stages',[])
                start=values['start_time'];steps=values['steps']+len(result[2]);t=float(result[1])
                match=next((i for i,r in enumerate(rows) if abs(r['t_start']-start)<1e-8 and r['nr']==values['nr']),None)
                if match is not None:
                    scale=2 if values.get('replay_id') else 1
                    within=min(1.,steps/(rows[match]['steps']*scale))
                    weight=sum(r['wall_s'] for r in rows)
                    fraction=(sum(r['wall_s'] for r in rows[:match])+rows[match]['wall_s']*within)/weight
                else:
                    # Expected horizon is a display estimate, never a stop test.
                    horizon=self.profile.get('actual_end_s',{'q1':1800.,'q23':207437.4,'q4':184256.64}[values['case']])
                    dt=(t-start)/max(1,steps)
                    stage_expected=max(1.,(min(values['cap'],horizon)-start)/max(dt,1e-12))
                    within=min(1.,steps/stage_expected)
                    fraction=(start+within*(min(values['cap'],horizon)-start))/horizon
                self.Progress_Report(self.lower+(self.upper-self.lower)*min(.999,fraction),
                    f"{values['case']} Nr={values['nr']}，已接受 {steps} 步，t={t/3600:.3f} h",'accepted_steps',
                    accepted_steps=steps,stage_start_s=start,simulated_time_s=t)
            elif name=='Trajectory_Solve' and len(result[2]) and result[4]==0:
                stages=values['spec']['schedule'];t=float(result[1])
                total=sum((s['t_end']-s['t_start'])*s['nr']**3 for s in stages)
                work=sum(max(0.,min(t,s['t_end'])-s['t_start'])*s['nr']**3 for s in stages)
                self.Progress_Report(self.lower+(self.upper-self.lower)*min(.999,work/max(total,1.)),
                    f"{values['spec']['case']} 阶段 {values['index']+1}/{len(stages)}，t={t/3600:.3f} h",'trajectory',
                    accepted_steps=values['status']['steps']+len(result[2]),simulated_time_s=t)
            elif name=='MassBalance_MeasureCase':
                steps=int(values['audit'][8]);expected=values['manifest']['statuses'][values['key']]['steps']
                self.Progress_Report(.95*min(1.,steps/max(1,expected)),f'已审计 {steps}/{expected} 个接受步','mass_balance',accepted_steps=steps)
        except (KeyError,TypeError,ValueError,AttributeError,ZeroDivisionError):pass


@contextmanager
def Progress_ObserveTask(root,task):
    observer=TaskObserver(root,task);token=_CURRENT.set(observer);patches=[]
    def Replace(module,name,value):
        patches.append((module,name,getattr(module,name)));setattr(module,name,value)
    def Observe_Kernel(original):
        @wraps(original)
        def Kernel_Run(*args,**kwargs):
            result=original(*args,**kwargs)
            observer.Progress_ObserveBlock(sys._getframe(1),result)
            return result
        return Kernel_Run
    try:
        from . import table_solver
        original=table_solver.Table_SolveSchedule
        @wraps(original)
        def Schedule_Run(*args,**kwargs):
            half=kwargs.get('label')=='time_half'
            stage_wall=sum(r['wall_s'] for r in observer.profile.get('stages',[]))
            share=min(.93,max(.5,stage_wall/max(.01,observer.profile.get('wall_s',stage_wall or 1.))))
            observer.lower=.8 if half else 0.;observer.upper=.97 if half else share
            observer.Progress_Report(observer.lower,'读取/复用正式轨迹' if not half else '正式接受分区半步重放','solve',
                upper=observer.upper,expected_s=stage_wall or None,force=True)
            result=original(*args,**kwargs)
            observer.Progress_Report(observer.upper,'轨迹就绪，开始导出与回读','export',upper=.96,
                expected_s=max(1.,observer.profile.get('wall_s',20.)-stage_wall),force=True)
            return result
        Replace(table_solver,'Rk4_Advance',Observe_Kernel(table_solver.Rk4_Advance))
        Replace(table_solver,'Table_SolveSchedule',Schedule_Run)
        if task['kind'] in ['validation_1d','experiment','full_production']:
            from .studies import trajectory
            factory=trajectory.Trajectory_GetAdvance
            @wraps(factory)
            def Advance_Get(*args,**kwargs):return Observe_Kernel(factory(*args,**kwargs))
            Replace(trajectory,'Trajectory_GetAdvance',Advance_Get)
            observer.upper=.79 if task['kind']=='validation_1d' else .95
        if task['kind']=='mass_measure':
            from .studies import mass_balance
            builder=mass_balance.MassBalance_BuildKernel
            @wraps(builder)
            def Mass_Get(*args,**kwargs):return Observe_Kernel(builder(*args,**kwargs))
            Replace(mass_balance,'MassBalance_BuildKernel',Mass_Get)
        if task['kind']=='plot' and task.get('selection')=='gif':
            from . import animations
            writer=animations.Animation_WriteGif
            @wraps(writer)
            def Gif_Write(root,path,frame_count,fps,draw,metadata,*args,**kwargs):
                def Frame_Draw(index):
                    fig=draw(index)
                    observer.Progress_Report(.05+.9*(observer.gif_completed+(index+1)/frame_count)/5,
                        f'{path.name}：{index+1}/{frame_count} 帧','gif')
                    return fig
                result=writer(root,path,frame_count,fps,Frame_Draw,metadata,*args,**kwargs)
                observer.gif_completed+=1;return result
            Replace(animations,'Animation_WriteGif',Gif_Write)
        yield observer
    finally:
        for module,name,original in reversed(patches):setattr(module,name,original)
        _CURRENT.reset(token)
