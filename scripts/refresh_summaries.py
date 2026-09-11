"""Refresh result metadata from existing evidence, without exporting or solving."""
import sys
from pathlib import Path

_ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(_ROOT/'src'))

from drying.outputs import Output_UpdateStatus
from drying.plot_contract import Payload_ReadManifest, Payload_GetSeal
from drying.storage import Storage_WriteJson, Storage_HashFiles


def Summary_Refresh(root):
    root=Path(root)
    # Check the existing seal before any metadata update. Numeric payloads are
    # deliberately neither repacked nor modified by this command.
    manifest=Payload_ReadManifest(root)
    evidence=Output_UpdateStatus(root)
    path=root/manifest['overview_payload']
    Storage_WriteJson(path,evidence)
    for entry in manifest['payload_files']:
        if entry['path']==manifest['overview_payload']:
            entry.update(hash=Storage_HashFiles([path]),size_bytes=path.stat().st_size)
    manifest['manifest_hash']=Payload_GetSeal(manifest)
    Storage_WriteJson(root/'work/plot_payload/plot_manifest.json',manifest)
    print('SUMMARIES_SYNCHRONIZED: status, Q1-Q4, overview, evidence snapshot; PDE solves=0')


if __name__=='__main__':
    Summary_Refresh(_ROOT)
