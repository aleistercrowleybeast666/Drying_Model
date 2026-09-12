from pathlib import Path
import sys,json
import numpy as np
root=Path(__file__).resolve().parents[3];sys.path.insert(0,str(root/'src'))
from drying.studies.trajectory import Trajectory_Iter,Trajectory_GetNodes,Trajectory_GetInputs,Trajectory_GetSpec
from drying.studies.baseline import Baseline_ReadJson
from drying.studies.selection import Selection_GetFactor
mode=sys.argv[1] if len(sys.argv)>1 else 'M10';factor=Selection_GetFactor(root,'q4',mode)
ids=[Trajectory_GetSpec(root,'q4',mode,kind=kind,factor=scale*factor)['experiment_id']
    for kind,scale in [('production',1),('full_reference',2)]]
rows=[]
for key in ids:
    spec=Baseline_ReadJson(root/'work/studies/experiments'/key/'spec.json');values={}
    for t,state,mesh in Trajectory_Iter(root,key):
        if t>=600:break
        if t==0:continue
        r,z,nodes=Trajectory_GetNodes(state,t,4,Trajectory_GetInputs(root,spec),mesh,spec)
        positions=np.r_[np.arange(21)*.001,r[-1]];positions=positions[positions<=r[-1]+1e-14]
        values[t]=np.array([np.interp(positions,r,nodes[i,:,0]) for i in [0,1]])
    rows.append(values)
common=sorted(set(rows[0])&set(rows[1]));delta=np.array([np.max(abs(rows[0][t]-rows[1][t]),axis=1) for t in common])
print(json.dumps(dict(mode=mode,scope='PRELIMINARY: common formal times 60..540 s only; full reference still running',
    times_s=common,max_abs_T_K=float(delta[:,0].max()),max_abs_C=float(delta[:,1].max())),indent=2))
