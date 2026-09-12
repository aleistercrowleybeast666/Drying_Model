"""Byte-preserving publication relocation with copy/hash/manifest/delete ordering."""
import os
import shutil
from pathlib import Path
from ..plot_contract import Payload_GetSeal
from ..storage import Storage_WriteJson
from .baseline import Baseline_ReadJson, Baseline_HashFile


def Migration_MoveAnimations(root):
    root=Path(root).resolve();baseline=Baseline_ReadJson(root/'work/baseline_snapshot/baseline_manifest.json')
    items=[r for r in baseline['images'] if r['path'].endswith('.gif')]
    mapping={r['path']:'results/animations/'+Path(r['path']).name for r in items}
    destination=root/'results/animations';destination.mkdir(parents=True,exist_ok=True)
    for item in items:
        old=root/item['path'];new=root/mapping[item['path']]
        if new.exists() and Baseline_HashFile(new)==item['sha256']:continue
        if not old.is_file() or Baseline_HashFile(old)!=item['sha256']:raise RuntimeError('BASELINE_OUTPUT_MODIFIED: '+str(old))
        temp=new.with_suffix('.gif.migrating');shutil.copy2(old,temp)
        if Baseline_HashFile(temp)!=item['sha256']:raise RuntimeError('GIF_MIGRATION_HASH_FAILED')
        os.replace(temp,new)
    def Replace(value):
        if isinstance(value,str):return mapping.get(value.replace('\\','/'),value)
        if isinstance(value,dict):return {k:Replace(v) for k,v in value.items()}
        if isinstance(value,list):return [Replace(v) for v in value]
        return value
    manifest_path=root/'work/plot_payload/plot_manifest.json';manifest=Replace(Baseline_ReadJson(manifest_path))
    manifest['manifest_hash']=Payload_GetSeal(manifest);Storage_WriteJson(manifest_path,manifest)
    animation_path=root/'work/diagnostics/animations_manifest.json';Storage_WriteJson(animation_path,Replace(Baseline_ReadJson(animation_path)))
    record=dict(paths=mapping,files=items,policy='copy, verify SHA-256, update manifest, then remove old copy; no rendering')
    Storage_WriteJson(root/'work/baseline_snapshot/gif_migration.json',record)
    for item in items:
        old=(root/item['path']).resolve();new=(root/mapping[item['path']]).resolve()
        if not old.is_relative_to(root/'results') or not new.is_relative_to(destination):raise RuntimeError('GIF_MIGRATION_SCOPE_FAILED')
        if old.exists():
            if Baseline_HashFile(new)!=item['sha256']:raise RuntimeError('GIF_MIGRATION_HASH_FAILED')
            old.unlink()
    print('GIF_MIGRATION_COMPLETE: five byte-identical animations',flush=True)
