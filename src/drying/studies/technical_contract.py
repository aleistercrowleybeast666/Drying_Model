"""Read-only sealed final-study metadata, without imports of numerical modules."""
from pathlib import Path
import hashlib
import json


def Technical_ReadPayload(root, manifest):
    root=Path(root)
    entry=manifest.get('technical_extension')
    if not entry:raise FileNotFoundError('TECHNICAL_PAYLOAD_MISSING: run compute_studies.py --group geometry_cross --resume')
    path=(root/entry['path']).resolve()
    if not path.is_relative_to((root/'work/studies').resolve()):raise RuntimeError('TECHNICAL_PAYLOAD_PATH_INVALID')
    if not path.is_file():raise FileNotFoundError('TECHNICAL_PAYLOAD_MISSING: '+str(path))
    def Digest(file):
        with file.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
    if Digest(path)!=entry['sha256']:raise RuntimeError('TECHNICAL_PAYLOAD_HASH_MISMATCH: '+str(path))
    result=json.loads(path.read_text(encoding='utf-8'));seal=result.pop('seal',None)
    if result.get('schema_version')!=1 or seal!=hashlib.sha256(json.dumps(result,sort_keys=True,allow_nan=False).encode()).hexdigest():
        raise RuntimeError('TECHNICAL_PAYLOAD_VERSION_MISMATCH')
    result['seal']=seal
    for item in result['payload_files']:
        target=(root/item['path']).resolve()
        if not any(target.is_relative_to((root/folder).resolve()) for folder in ['work/studies','work/cache']):raise RuntimeError('TECHNICAL_PAYLOAD_PATH_INVALID')
        if not target.is_file() or Digest(target)!=item['sha256']:raise RuntimeError('TECHNICAL_PAYLOAD_HASH_MISMATCH: '+str(target))
    return result
