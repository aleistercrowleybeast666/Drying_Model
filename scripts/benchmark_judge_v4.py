"""Bounded Q1 strict-task benchmarks; never run Developer Full Audit or touch V2."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import psutil
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from drying.judge_pipeline import Judge_CopyResources,Judge_GetPlan,DEVELOPER_TASKS
from drying.judge_tasks import Task_PrepareBaseline
from drying.judge_resources import Resource_CopyTree
from drying.judge_executor import Executor_Run
from drying.judge_schedule import Schedule_GetResources
from drying.storage import Storage_WriteJson


def Benchmark_Run(suite):
    folder=ROOT/'work/release_v4';root=folder/'benchmark';runtime=root/'work/recompute/runtime'
    source=ROOT/'work/release_v3/acceptance_output/work/recompute/runtime'
    root.mkdir(parents=True,exist_ok=True)
    Judge_CopyResources(ROOT,ROOT/'data',root)
    if not runtime.exists():Resource_CopyTree(source/'work',runtime/'work')
    Judge_CopyResources(ROOT,ROOT/'data',runtime)
    os.environ.update(DRYING_MODEL_ROOT=str(root),DRYING_JUDGE_FROZEN_MESH='1',NUMBA_CACHE_DIR=str(root/'work/recompute/numba_cache'))
    from drying.validation import Validation_SaveEntry
    for case,source in json.loads((runtime/'work/recompute/production.json').read_text(encoding='utf-8')).items():
        Validation_SaveEntry(runtime,case+'_1d',dict(selected_id=source['case_id'],selected_fingerprint=source['fingerprint'],numerical_status='NOT_RERUN_IN_TABLE_ONLY_MODE'))
    Task_PrepareBaseline(runtime)
    plan=Judge_GetPlan(root,DEVELOPER_TASKS);jobs={j['key']:j for j in plan['steps']}
    outcomes={};start=time.time()
    def Run_Case(name,keys,workers=1,persistent=True,force=True):
        selected=[copy.deepcopy(jobs[k]) for k in keys]
        for task in selected:
            task['dependencies']=[k for k in task['dependencies'] if k in keys]
            task['persistent']=persistent and task['kind'] in ['experiment','mass_measure']
            task['force_reference']=force
            # Use observed same-task RSS from the warmup, including 30% headroom.
            old=runtime/'work/recompute/receipts'/(task['key']+'.json')
            if old.exists():task['memory_estimate_mb']=max(512.,json.loads(old.read_text(encoding='utf-8'))['peak_rss_mb']*1.3)
        resources=Schedule_GetResources(str(workers))
        if resources['available_memory_at_start_mb']<3072:
            raise RuntimeError('BENCHMARK_MEMORY_PAUSE: fewer than 3 GiB available; retain partial receipts and resume later')
        active=dict(plan,steps=selected,worker_count=workers,resources=resources,developer_full_audit=False)
        print('BENCHMARK_START',name,'available_mb',resources['available_memory_at_start_mb'],flush=True)
        result=Executor_Run(root,runtime,active)
        result['name']=name;result['scope']='Q1 full 1800 s trajectory; unchanged selected mesh/factor/dt; not a Q23 full-audit speed claim'
        result['data_hashes']={}
        for row in result['tasks']:
            key=row['result'].get('experiment_id')
            if key:
                result['data_hashes'][key]={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (runtime/'work/studies/experiments'/key).glob('*.npz')}
        Storage_WriteJson(folder/(name+'.json'),result);outcomes[name]=result
        print('BENCHMARK_END',name,'wall',result['wall_s'],'max_workers',result['max_concurrent_workers'],'peak_rss',result['memory_high_water_mb'],flush=True)
        return result
    production=[f'D.{mode}.q1.production' for mode in ['M10','M01','M11']]
    if suite in ['all','persistent']:
        Run_Case('thermal_warmup_q1',production,persistent=True,force=False)
        five=production+[f'D.{mode}.q1.full_reference' for mode in ['M10','M01']]
        # First both reference specializations must also exist in the JIT cache.
        Run_Case('reference_warmup_q1',five[3:],force=False)
        one=Run_Case('persistent_comparison_oneshot',five,persistent=False)
        pooled=Run_Case('persistent_comparison_pool',five)
        assert one['data_hashes']==pooled['data_hashes'],'PERSISTENT_NUMERICAL_HASH_MISMATCH'
        Storage_WriteJson(folder/'persistent_equivalence.json',dict(status='PASS',tasks=5,data_hashes=pooled['data_hashes'],one_shot_wall_s=one['wall_s'],persistent_wall_s=pooled['wall_s']))
    if suite in ['all','parallel']:
        strict=[f'D.{mode}.q1.{kind}' for mode in ['M10','M01','M11'] for kind in ['full_reference','time_half']]
        for workers in [3,4,5]:Run_Case('parallel_'+str(workers),strict,workers=workers)
    if suite in ['all','mixed']:
        for count in [0,2,3]:
            keys=['B.2d.q1.base']+[f'D.{mode}.q1.full_reference' for mode in ['M10','M01','M11'][:count]]
            Run_Case('mixed_'+str(count),keys,workers=5)
    if suite=='mixed-control':Run_Case('mixed_warm_control',['B.2d.q1.base'],workers=5)
    if suite=='mass-pool':
        run=Run_Case('mass_pool_scope',['B.mass.M10.q1','D.M10.q1.production'],force=True)
        assert len({r['worker_pid'] for r in run['tasks']})==1
        assert all(r['status']=='PASS' for r in run['tasks'])
    if suite in ['all','twod']:
        keys=[j['key'] for j in plan['steps'] if j['key'].startswith('B.2d.q1')]
        Run_Case('twod_q1_split',keys,workers=3,force=False)
        from drying.judge_validation import Judge_Validate2d
        current=json.loads((runtime/'work/validation/summary.json').read_text(encoding='utf-8'))['q1_2d']
        # The old bundle expects its caller to have selected the official 1D
        # source; the split seed sets this only in its private workspace.
        from drying.validation import Validation_SaveEntry
        production=json.loads((runtime/'work/recompute/production.json').read_text(encoding='utf-8'))['q1']
        Validation_SaveEntry(runtime,'q1_1d',dict(selected_id=production['case_id'],selected_fingerprint=production['fingerprint'],numerical_status='NOT_RERUN_IN_TABLE_ONLY_MODE'))
        prior=Judge_Validate2d(runtime,'q1')['q1_2d']
        assert prior==current,'2D_BUNDLE_EQUIVALENCE_MISMATCH'
        Storage_WriteJson(folder/'twod_real_equivalence.json',dict(status='PASS',case='q1',scope='Full original Q1 2D evidence; same unchanged bundle functions and parameters'))
    print('BENCHMARK_SUITE_END',suite,'wall',time.time()-start,flush=True)


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser();parser.add_argument('--suite',choices=['all','persistent','parallel','mixed','mixed-control','mass-pool','twod'],default='all')
    Benchmark_Run(parser.parse_args().suite)
