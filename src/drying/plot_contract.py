"""Versioned, sealed plot payload contract; no solver imports or cache discovery."""
import hashlib
import json
from pathlib import Path
from .storage import Storage_HashFiles


def Payload_GetRenderHash(root):
    return Storage_HashFiles([Path(root)/'src/drying'/n for n in
        ['plots.py','animations.py','cutaway.py','presentation.py','plot_contract.py']])


def Payload_GetSeal(manifest):
    return hashlib.sha256(json.dumps({k:v for k,v in manifest.items() if k != 'manifest_hash'},
                                    sort_keys=True).encode()).hexdigest()


def Payload_ResolvePath(root, relative, output=False):
    path = (Path(root)/relative).resolve()
    scope = (Path(root)/('results' if output else 'work/plot_payload')).resolve()
    if not path.is_relative_to(scope):
        raise ValueError(f'PLOT_DATA_VERSION_MISMATCH: path outside declared payload/output scope: {relative}')
    return path


def Payload_ReadManifest(root):
    path = Path(root)/'work/plot_payload/plot_manifest.json'
    if not path.exists():
        raise FileNotFoundError(f'PLOT_MANIFEST_MISSING: {path}')
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if manifest.get('schema_version') != 1 or manifest.get('manifest_hash') != Payload_GetSeal(manifest):
        raise RuntimeError(f'PLOT_DATA_VERSION_MISMATCH: schema or manifest integrity: {path}')
    for entry in manifest['payload_files']:
        file = Payload_ResolvePath(root,entry['path'])
        if not file.is_file():
            raise FileNotFoundError(f'PLOT_PAYLOAD_MISSING: {file}')
        if Storage_HashFiles([file]) != entry['hash']:
            raise RuntimeError(f'PLOT_DATA_VERSION_MISMATCH: payload content changed: {file}')
    declared = {v['path'] for v in manifest['payload_files']}
    referenced = [manifest['overview_payload']]
    for question in manifest['questions'].values():
        referenced.append(question['data_path'])
        referenced.extend(v['data_path'] for v in question.get('animations',{}).values())
    if not set(referenced) <= declared:
        raise RuntimeError('PLOT_DATA_VERSION_MISMATCH: undeclared data reference')
    for output in manifest['outputs']:
        Payload_ResolvePath(root,output,True)
    return manifest
