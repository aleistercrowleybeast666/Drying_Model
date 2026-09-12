"""Developer-only regeneration. A comparison is the default; --accept publishes."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))


def Frozen_RegenerateMain():
    from drying.frozen_mesh import Frozen_CreateResources, Frozen_ReadManifest
    from drying.mesh import Mesh_PrepareCase, Mesh_Equidistribute
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--accept', action='store_true')
    args = parser.parse_args()
    old = Frozen_ReadManifest(ROOT)
    os.environ.pop('DRYING_JUDGE_FROZEN_MESH', None)
    folder = ROOT/'work/frozen_mesh_regeneration'
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=folder, prefix='candidate_') as directory:
        candidate = Path(directory)
        for name in ['src', 'data', 'configs']:
            shutil.copytree(ROOT/name, candidate/name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        for case in ['q1', 'q23', 'q4']:
            Mesh_PrepareCase(candidate, case)
        result = Frozen_CreateResources(candidate, candidate/'work/validation/mesh_profiles', candidate/'candidate', old['schedules'])
        comparisons = []
        for case, record in result['cases'].items():
            for axis, resource in record['resources'].items():
                name = resource['file']
                with np.load(candidate/'candidate'/name) as new, np.load(ROOT/'configs/frozen_mesh'/name) as prior:
                    difference = max(float(np.max(np.abs(Mesh_Equidistribute(new['x'], new['monitor'], int(n))[0]-
                        Mesh_Equidistribute(prior['x'], prior['monitor'], int(n))[0]))) for n in resource['faces_hashes'])
                comparisons.append(dict(case=case, axis=axis, sha256=resource['sha256'],
                    previous_sha256=old['cases'][case]['resources'][axis]['sha256'], max_faces_difference=difference))
        print(json.dumps(dict(accepted=args.accept, comparisons=comparisons), ensure_ascii=False, indent=2))
        if args.accept:
            shutil.copytree(candidate/'candidate', ROOT/'configs/frozen_mesh', dirs_exist_ok=True)


if __name__ == '__main__':
    Frozen_RegenerateMain()
