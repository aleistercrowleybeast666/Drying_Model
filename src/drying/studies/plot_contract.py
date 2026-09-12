"""Read-only, solver-free contract for every supplementary figure and animation."""
import hashlib
import json
from pathlib import Path
import numpy as np


def StudyPlot_GetHash(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def StudyPlot_ReadManifest(root, validate_technical=True):
    root=Path(root);path=root/'work/studies/plot_payload/study_manifest.json'
    if not path.is_file():raise FileNotFoundError(f'STUDY_PAYLOAD_MISSING: {path}; experiment=all; run .venv\\Scripts\\python.exe compute_studies.py --group all --resume')
    manifest=json.loads(path.read_text(encoding='utf-8'));seal=manifest.pop('seal',None)
    if manifest.get('schema_version')!=2 or seal!=hashlib.sha256(json.dumps(manifest,sort_keys=True,allow_nan=False).encode()).hexdigest():
        raise RuntimeError('STUDY_MANIFEST_VERSION_MISMATCH: '+str(path))
    manifest['seal']=seal
    entries=list(manifest['series'].values())+manifest.get('end_effects',[])+manifest.get('counterfactuals',[])+manifest.get('interactions',[])
    entries += [dict(path=c['series_path'],sha256=c['series_sha256'],experiment_id=c['reference_id']) for c in manifest.get('checks',[])]
    for entry in entries:
        target=(root/entry['path']).resolve()
        if not target.is_relative_to((root/'work/studies').resolve()):raise RuntimeError('STUDY_MANIFEST_VERSION_MISMATCH: escaped path')
        if not target.is_file():raise FileNotFoundError(f"STUDY_PAYLOAD_MISSING: {target}; experiment={entry.get('experiment_id',entry.get('case'))}; run compute_studies.py --group all --resume --payload-only")
        if StudyPlot_GetHash(target)!=entry['sha256']:raise RuntimeError('STUDY_MANIFEST_VERSION_MISMATCH: '+str(target))
    if validate_technical and manifest.get('technical_extension'):
        from .technical_contract import Technical_ReadPayload
        Technical_ReadPayload(root,manifest)
    return manifest


def StudyPlot_Load(root,entry):
    with np.load(Path(root)/entry['path']) as data:return {k:data[k].copy() for k in data.files}


def StudyPlot_Find(manifest,case,mode='M00'):
    if mode=='M00':key=manifest['baseline_keys'].get(case)
    else:key=next((k for k,v in manifest['series'].items() if v['case']==case and v['mode']==mode and v['kind']=='production'),None)
    if not key:raise FileNotFoundError(f'STUDY_PAYLOAD_MISSING: work/studies/experiments/{case}_{mode}_production; experiment={case}/{mode}; run compute_studies.py --group thermal --case {case} --mode {mode} --resume')
    return manifest['series'][key]
