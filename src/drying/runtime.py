"""Presentation/runtime paths only. Numerical sources keep their original layout."""
import os
import sys
from pathlib import Path


def Runtime_GetRoot():
    if os.environ.get('DRYING_MODEL_ROOT'):
        return Path(os.environ['DRYING_MODEL_ROOT']).resolve()
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def Runtime_GetCode(root=None):
    root = Path(root or Runtime_GetRoot())
    if (root/'dependencies/src/drying').is_dir():return root/'dependencies'
    if (root/'dependencies/application/code/src').is_dir():return root/'dependencies/application/code'
    return root/'code' if (root/'code/src').is_dir() else root


def Runtime_GetData(root=None):
    root=Path(root or Runtime_GetRoot())
    if (root/'dependencies/data').is_dir():return root/'dependencies/data'
    return root/'data' if (root/'data').is_dir() else root/'dependencies/application/data'


def Runtime_GetRawData(root=None):
    root=Path(root or Runtime_GetRoot()).resolve()
    published=root/'原始题目数据'
    return published if published.is_dir() else Runtime_GetData(root)/'raw'


def Runtime_StageRaw(root,workspace,templates_only=False):
    """Restore the original relative layout so the established input hash is stable."""
    import hashlib
    import json
    import shutil
    root=Path(root);workspace=Path(workspace)
    source=Runtime_GetRawData(root).resolve();raw=(workspace/'data/raw').resolve()
    manifest=json.loads((Runtime_GetData(root)/'input_manifest.json').read_text(encoding='utf-8'))
    files=manifest.get('raw_files') or {p.relative_to(source).as_posix():dict(path=p.relative_to(source).as_posix())
        for p in source.rglob('*') if p.is_file() and p.suffix.lower() in ['.pdf','.xlsx'] and not p.name.startswith('~$')}
    for name,row in files.items():
        if templates_only and Path(name).name not in [f'result{q}.xlsx' for q in range(1,5)]:continue
        path=(source/row['path']).resolve();target=(raw/name).resolve()
        if not path.is_relative_to(source) or not target.is_relative_to(raw):raise ValueError('RAW_INPUT_PATH_OUTSIDE_PACKAGE')
        with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if row.get('sha256',digest)!=digest:raise ValueError('RAW_INPUT_HASH_MISMATCH: '+row['path'])
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():
            if target.read_bytes()!=path.read_bytes():raise ValueError('CACHE_MISMATCH: refusing to replace raw input')
        else:shutil.copy2(path,target)
    return raw


def Runtime_PrepareInputs(root,workspace):
    import json
    from .inputs import Input_Prepare
    from .storage import Storage_WriteJson
    raw=Runtime_StageRaw(root,workspace)
    manifest=Input_Prepare(workspace,raw)
    expected=json.loads((Runtime_GetData(root)/'input_manifest.json').read_text(encoding='utf-8'))
    if manifest['hash']!=expected['hash']:raise ValueError('RAW_INPUT_IDENTITY_MISMATCH')
    manifest['source']=Path(os.path.relpath(Runtime_GetRawData(root),workspace)).as_posix()
    Storage_WriteJson(Path(workspace)/'data/input_manifest.json',manifest)
    return manifest


def Runtime_GetTemplate(root,manifest,question):
    template=Path(manifest['templates'][str(question)]['path'])
    relative=template.relative_to('data') if template.parts[0]=='data' else Path('raw')/template.name
    mapped=manifest.get('raw_files',{}).get(relative.relative_to('raw').as_posix())
    return Runtime_GetRawData(root)/mapped['path'] if mapped else Runtime_GetData(root)/relative


def Runtime_BuildRecomputeCommand(arguments, root=None):
    root = Path(root or Runtime_GetRoot())
    backend=root/'dependencies/backend.py'
    if backend.is_file():return [sys.executable,'-u',str(backend),*arguments]
    entry = root/'药材烘干模型_原题表格复算.py'
    if not entry.exists(): entry = Runtime_GetCode(root)/'offline_recompute.py'
    return [sys.executable, '-u', str(entry), *arguments]
