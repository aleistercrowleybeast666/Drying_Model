"""Release resources, independent of runtime pilot caches and solver results."""
import hashlib
import json
import logging
import os
import shutil
from pathlib import Path

import numpy as np

from .storage import Storage_WriteArray, Storage_WriteJson


def Frozen_HashFile(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def Frozen_HashValue(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def Frozen_GetIdentity(root):
    from .cases import Case_LoadConfig, Case_GetSourceHash
    root = Path(root)
    config = Case_LoadConfig(root)
    return dict(input_hash=json.loads((root/'data/input_manifest.json').read_text(encoding='utf-8'))['hash'],
        mesh_config_hash=Frozen_HashValue(dict(mesh=config['mesh'], numerics=config['numerics'])),
        schedule_config_hash=Frozen_HashFile(root/'configs/stage_schedule.json'),
        numerical_source_hash=Case_GetSourceHash(root))


def Frozen_ReadManifest(root):
    root = Path(root)
    try:
        manifest = json.loads((root/'configs/frozen_mesh/manifest.json').read_text(encoding='utf-8'))
        for key, value in Frozen_GetIdentity(root).items():
            if manifest[key] != value:
                raise ValueError(key)
        if manifest['schedule_hash'] != Frozen_HashValue(manifest['schedules']):
            raise ValueError('schedule_hash')
        return manifest
    except (OSError, ValueError, KeyError) as error:
        raise RuntimeError('FROZEN_MESH_CONFIGURATION_MISSING_OR_MISMATCH: 发布网格资源损坏或输入/配置已改变；不会运行 pilot。 '+str(error)) from error


def Frozen_PrepareCase(root, case):
    """Verify bytes AND continuous monitor/faces; only materialize resource copies."""
    from .mesh import Mesh_Equidistribute, Mesh_GetHash
    root = Path(root)
    manifest = Frozen_ReadManifest(root)
    destination = root/'work/validation/mesh_profiles'
    destination.mkdir(parents=True, exist_ok=True)
    try:
        record = manifest['cases'][case]
        summary = record['mesh_summary']
        for axis, resource in record['resources'].items():
            source = root/'configs/frozen_mesh'/resource['file']
            if Frozen_HashFile(source) != resource['sha256']:
                raise ValueError(resource['file']+' SHA256')
            with np.load(source, allow_pickle=False) as saved:
                if Mesh_GetHash(saved['x'], saved['monitor']) != resource['monitor_hash']:
                    raise ValueError(resource['file']+' monitor hash')
                for count, expected in resource['faces_hashes'].items():
                    faces = Mesh_Equidistribute(saved['x'], saved['monitor'], int(count))[0]
                    if Mesh_GetHash(faces) != expected:
                        raise ValueError(resource['file']+' faces '+count)
                    path = destination/f'{case}_{axis}_{count}.npz'
                    if not path.exists():
                        Storage_WriteArray(path, faces=faces, centers=(faces[:-1]+faces[1:])/2,
                            cell_widths=np.diff(faces), monitor=saved['monitor'],
                            cumulative_monitor=saved['cumulative_monitor'], monitor_hash=resource['monitor_hash'])
            target = destination/source.name
            if not target.exists() or Frozen_HashFile(target) != resource['sha256']:
                temporary = target.with_suffix('.resource.tmp')
                shutil.copyfile(source, temporary)
                os.replace(temporary, target)
        Storage_WriteJson(destination/f'{case}_mesh.json', summary)
    except (OSError, ValueError, KeyError) as error:
        raise RuntimeError('FROZEN_MESH_CONFIGURATION_MISSING_OR_MISMATCH: '+case+' '+str(error)) from error
    logging.getLogger('drying').info('FROZEN_MESH_REUSED %s', case)
    return summary


def Frozen_CreateResources(root, source, destination, schedules):
    """Developer explicit freeze, never called by the judge entry."""
    from .mesh import Mesh_Equidistribute, Mesh_GetHash
    root, source, destination = map(Path, (root, source, destination))
    destination.mkdir(parents=True, exist_ok=True)
    result = dict(schema_version=1, **Frozen_GetIdentity(root), schedules=schedules,
        schedule_hash=Frozen_HashValue(schedules), cases={})
    for case in ['q1', 'q23', 'q4']:
        record = dict(mesh_summary=json.loads((source/f'{case}_mesh.json').read_text(encoding='utf-8')), resources={})
        for axis, counts in [('radial', [40, 80, 160, 200, 320, 400]), ('axial', [1, 125, 250])]:
            name = f'{case}_{axis}_monitor.npz'
            shutil.copy2(source/name, destination/name)
            with np.load(destination/name) as saved:
                record['resources'][axis] = dict(file=name, sha256=Frozen_HashFile(destination/name),
                    monitor_hash=Mesh_GetHash(saved['x'], saved['monitor']),
                    faces_hashes={str(n): Mesh_GetHash(Mesh_Equidistribute(saved['x'], saved['monitor'], n)[0]) for n in counts})
        result['cases'][case] = record
    Storage_WriteJson(destination/'manifest.json', result)
    return result
