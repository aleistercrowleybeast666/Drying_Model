"""Seal numerical files separately from rendering and reject mismatched reuse."""
from pathlib import Path
import shutil
import time
import numpy as np
from ..storage import Storage_WriteJson,Storage_WriteArray
from .baseline import Baseline_ReadJson,Baseline_HashFile


def Cache_SealExperiment(root,spec,status):
    root=Path(root);folder=root/'work/studies/experiments'/spec['experiment_id']
    saved=Baseline_ReadJson(folder/'spec.json')
    if saved!=spec or status['fingerprint']!=spec['fingerprint']:raise RuntimeError('STUDY_CACHE_MISMATCH: specification or status fingerprint')
    if not status.get('complete'):return status
    disk=Baseline_ReadJson(folder/'status.json')
    previous=disk.get('data_files')
    if previous:
        for name,record in previous.items():
            path=(folder/name).resolve()
            if not path.is_relative_to(folder.resolve()) or not path.is_file() or Baseline_HashFile(path)!=record['sha256']:
                raise RuntimeError('STUDY_CACHE_MISMATCH: '+name)
        return dict(status,data_files=previous)
    names=list(status['chunks'])+['checkpoint.npz']
    if status.get('event'):names+=['event.npz']
    names += [p.name for p in folder.glob('remesh_*.npz')]
    records={}
    for name in names:
        path=(folder/name).resolve()
        if not path.is_relative_to(folder.resolve()) or not path.is_file():raise RuntimeError('STUDY_REFERENCE_INCOMPLETE: '+name)
        records[name]=dict(sha256=Baseline_HashFile(path),size_bytes=path.stat().st_size)
    status=dict(status,data_files=records);Storage_WriteJson(folder/'status.json',status)
    return status


def Cache_ReuseEquivalent(root,spec,experiments):
    """Reuse a completed identical solve when only its study role changes.

    Full-reference and production roles share the same integration path. Every
    effective config field must match, including source hashes and full history.
    Numerical arrays are checked bit for bit; only the chunk identity is relabeled.
    """
    root=Path(root);target=root/'work/studies/experiments'/spec['experiment_id']
    if target.exists() or spec['kind'] not in ['production','full_reference']:return None
    ignored={'kind','experiment_id','fingerprint'}
    expected={k:v for k,v in spec.items() if k not in ignored}
    for key,result in experiments.items():
        if key==spec['experiment_id'] or not result.get('complete'):continue
        source=root/'work/studies/experiments'/key
        original=Baseline_ReadJson(source/'spec.json')
        if original['kind'] not in ['production','full_reference']:continue
        if {k:v for k,v in original.items() if k not in ignored}!=expected:continue
        saved=Cache_SealExperiment(root,original,Baseline_ReadJson(source/'status.json'))
        started=time.monotonic();target.mkdir(parents=True);Storage_WriteJson(target/'spec.json',spec)
        for name in saved['data_files']:
            if name in saved['chunks']:
                with np.load(source/name) as data:arrays={k:data[k].copy() for k in data.files}
                arrays['fingerprint']=np.asarray(spec['fingerprint']);Storage_WriteArray(target/name,**arrays)
                with np.load(source/name) as a,np.load(target/name) as b:
                    for variable in a.files:
                        if variable!='fingerprint' and (a[variable].dtype!=b[variable].dtype or a[variable].shape!=b[variable].shape or a[variable].tobytes()!=b[variable].tobytes()):
                            raise RuntimeError('STUDY_CACHE_MISMATCH: equivalent reuse changed '+variable)
            else:shutil.copy2(source/name,target/name)
        status={k:v for k,v in saved.items() if k!='data_files'}
        status.update(experiment_id=spec['experiment_id'],fingerprint=spec['fingerprint'],wall_s=0.,
            reuse=dict(source_experiment_id=key,source_solver_wall_s=saved.get('wall_s'),copy_wall_s=time.monotonic()-started,
                reason='only production/reference role differs; all physical, numerical and source settings identical',
                numerical_arrays_bitwise_equal=True,source_data_files=saved['data_files']))
        Storage_WriteJson(target/'status.json',status)
        print('REUSED_EQUIVALENT '+key+' -> '+spec['experiment_id'],flush=True)
        return Cache_SealExperiment(root,spec,status)
    return None
