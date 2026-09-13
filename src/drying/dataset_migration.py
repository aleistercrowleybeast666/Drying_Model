"""Register compatible old datasets by reference; never rewrite legacy data."""
import copy
import json
from pathlib import Path
import shutil
import time
import numpy as np
from .artifact_contract import Artifact_HashFile,Artifact_GetStatus,Artifact_ReadbackOfficial
from .dataset_layer import Dataset_Read,Dataset_Register,Dataset_GetExperimentKey
from .storage import Storage_WriteJson


def LegacyArtifact_Import(root,sources=None):
    from .cases import Case_ReadStatus,Case_LoadConfig
    from .frozen_mesh import Frozen_ReadManifest
    from .runtime import Runtime_GetCode
    root=Path(root).resolve();code=Runtime_GetCode(root);config=Case_LoadConfig(code)
    frozen=Frozen_ReadManifest(code);result=dict(imported=[],rejected=[])
    for source in sources or [root/'work/recompute/runtime',root]:
        source=Path(source).resolve()
        if not source.is_relative_to(root):raise ValueError('LEGACY_SOURCE_MUST_BE_WITHIN_PORTABLE_ROOT')
        production=Dataset_Read(source/'work/recompute/production.json')
        for case,status in production.items():
            key='official.'+case
            if Artifact_GetStatus(root,key)['complete']:continue
            try:
                status=Case_ReadStatus(source,status['case_id'])
                if not status.get('complete') or status.get('purpose')!='table_production' or status['schedule']!=frozen['schedules'][case]:continue
                if status['physics']!=config['physics'] or status['numerics']!=config['numerics']:continue
                questions=dict(q1=[1],q23=[2,3],q4=[4])[case]
                reference=Dataset_Read(code/'configs/table_reference/manifest.json')
                for q in questions:
                    with np.load(source/f'work/cache/exports/result{q}_full_precision.npz') as actual,np.load(code/'configs/table_reference'/reference['questions'][str(q)]['file']) as expected:
                        for name in ['time_s','temperature_C','moisture','R_m','surface_C']:
                            if not np.array_equal(actual[name],expected[name],equal_nan=True):raise ValueError('TABLE_NUMERIC_REFERENCE_MISMATCH')
                # Readback before registration; failure must never leave a valid seal.
                Artifact_ReadbackOfficial(root,dict(runtime=source.relative_to(root).as_posix(),case=case))
                Dataset_Register(root,source,key,status,'LegacyArtifact_Import');result['imported'].append(key)
            except (KeyError,ValueError,RuntimeError,OSError) as error:result['rejected'].append(dict(key=key,reason=str(error)))
        for path in (source/'work/cache').glob('*/status.json'):
            status=Dataset_Read(path);case=status.get('case')
            if not status.get('complete') or case not in frozen['schedules']:continue
            is_full=status.get('execution_mode')=='stage_schedule' and status.get('schedule')==frozen['schedules'][case] and status.get('cap')==frozen['schedules'][case][-1]['t_end'] and status.get('purpose')!='table_production'
            is_two=status.get('dim')==2 and not status.get('tag') and status.get('nr')==config['mesh']['base_nr'] and status.get('nz')==config['mesh']['base_nz']
            if not (is_full or is_two):continue
            key='innovation.'+('full.' if is_full else '2d.')+case
            if Artifact_GetStatus(root,key)['complete']:continue
            try:
                checked=Case_ReadStatus(source,status['case_id'])
                if checked['physics']!=config['physics'] or checked['numerics']!=config['numerics']:continue
                Dataset_Register(root,source,key,checked,'LegacyArtifact_Import');result['imported'].append(key)
            except (KeyError,ValueError,RuntimeError,OSError) as error:result['rejected'].append(dict(key=key,reason=str(error)))
        for path in (source/'work/studies/experiments').glob('*/spec.json'):
            spec=Dataset_Read(path);key=Dataset_GetExperimentKey(spec)
            if not key or Artifact_GetStatus(root,key)['complete']:continue
            try:
                status=Dataset_Read(path.with_name('status.json'))
                if not status.get('complete') or status.get('fingerprint')!=spec['fingerprint']:continue
                if spec['physics']!=config['physics'] or spec['numerics']!=config['numerics']:continue
                if any(Artifact_HashFile(code/'src/drying/studies'/name)!=digest for name,digest in spec['source'].items()):continue
                if not status.get('data_files'):continue
                for name,row in status['data_files'].items():
                    target=(path.parent/name).resolve()
                    if not target.is_relative_to(path.parent.resolve()) or Artifact_HashFile(target)!=row['sha256']:raise ValueError('LEGACY_DATA_HASH_MISMATCH')
                # Preserve the old logical fingerprint only when every effective
                # numerical setting agrees; baseline IDs alone are bookkeeping.
                from .studies.selection import Selection_GetFactor
                factor=Selection_GetFactor(code,spec['case'],spec['mode'])
                expected=[dict(s,nr=s['nr']*factor) for s in frozen['schedules'][spec['case']]]
                if spec['kind']=='tail':expected=[dict(s,t_start=max(14400,s['t_start'])) for s in expected if s['t_end']>14400]
                if spec['kind']=='matched':expected=[dict(t_start=0.,t_end=expected[-1]['t_end'],nr=config['mesh']['base_nr'],nz=1)]
                if expected!=spec['schedule'] or spec['dt_max_s']!=.25:continue
                Dataset_Register(root,source,key,status,'LegacyArtifact_Import',spec);result['imported'].append(key)
            except (KeyError,ValueError,RuntimeError,OSError) as error:result['rejected'].append(dict(key=key,reason=str(error)))
    Storage_WriteJson(root/'work/datasets/migration_receipt.json',result)
    return result


def LegacyArtifact_InvalidateSelected(workspace,job):
    """Explicit force archives only selected writable caches, never V2/V4."""
    from .dataset_layer import Dataset_GetSpec
    root=Path(workspace).resolve()
    if any(p in root.parts for p in ['release_v2','release_v4']):raise RuntimeError('OLD_RELEASE_PROTECTED')
    case=job['case'];paths=[]
    if job['data_kind']=='experiment':paths=[root/'work/studies/experiments'/Dataset_GetSpec(root,job)['experiment_id']]
    else:
        paths=[p for p in (root/'work/cache').glob(case+'_*') if p.is_dir()]
        paths += [root/f'work/recompute/table_cache_{case}.json',root/f'work/recompute/table_reference_{case}.json']
    archive=root/'work/recompute/forced_data'/str(time.time_ns())
    for source in paths:
        if not source.exists():continue
        resolved=source.resolve()
        if not resolved.is_relative_to(root/'work'):raise ValueError('FORCE_DATA_PATH_OUTSIDE_WORKSPACE')
        target=archive/source.relative_to(root/'work');target.parent.mkdir(parents=True,exist_ok=True)
        shutil.move(str(resolved),str(target))
