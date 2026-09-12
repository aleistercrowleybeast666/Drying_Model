"""Measure fresh-process kernel compilation/loading without advancing physical time."""
import sys,time
from datetime import datetime
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from drying.studies.trajectory import Trajectory_GetSpec,Trajectory_GetMesh,Trajectory_GetAdvance
from drying.studies.selection import Selection_GetFactor
from drying.studies.baseline import Baseline_Check
from drying.storage import Storage_WriteJson


def Startup_Benchmark():
    records=[]
    for mode,cases in [('M00',['q1']),('M10',['q1','q23','q4']),('M01',['q1','q23','q4']),('M11',['q1','q23','q4'])]:
        for case in cases:
            spec=Trajectory_GetSpec(ROOT,case,mode,factor=Selection_GetFactor(ROOT,case,mode));mesh=Trajectory_GetMesh(ROOT,spec,spec['schedule'][0])
            state=np.empty((2,len(mesh[0])-1,1));state[0]=spec['physics']['T0_K'];state[1]=spec['physics']['C0'];before=state.copy()
            started=time.perf_counter();result=Trajectory_GetAdvance(ROOT,spec,mesh)(state,0.,0.);elapsed=time.perf_counter()-started
            assert result[1]==0 and len(result[2])==0 and np.array_equal(result[0],before) and np.array_equal(state,before)
            records.append(dict(mode=mode,case=case,experiment_id=spec['experiment_id'],compile_or_load_s=elapsed,physical_steps=0,
                source=spec['source'],interpretation='fresh process; compile/load plus wrapper setup; zero-duration call, no trajectory recomputation'))
            print(f'KERNEL_STARTUP {mode} {case}: {elapsed:.3f} s, 0 physical steps',flush=True)
    Storage_WriteJson(ROOT/'work/studies/diagnostics/kernel_startup.json',dict(measured_at=datetime.now().astimezone().isoformat(),records=records,
        historical_trajectory_timing='trajectory wall_s records actual solver time including any original JIT; this fresh benchmark is separate and is not subtracted retroactively',
        baseline=Baseline_Check(ROOT)))


if __name__=='__main__':Startup_Benchmark()
