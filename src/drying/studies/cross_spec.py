"""Independent appendix-3 properties with the existing prescribed shrinkage."""
import hashlib
import json
from pathlib import Path
from .baseline import Baseline_HashFile
from .trajectory import Trajectory_GetSpec


def Cross_GetSpec(root, kind='production', factor=1, replay=None):
    """Material selector remains 3; only the independent geometry flag is enabled."""
    spec = Trajectory_GetSpec(root, 'q23', kind=kind, factor=factor, replay=replay)
    spec.pop('experiment_id')
    spec.pop('fingerprint')
    spec.update(study_id='geometry_cross_p3_shrink', material_appendix=3, shrink=True,
                geometry_source='attachment_2_R(t); original Q4 material-coordinate geometry',
                monitor_source='frozen q23 continuous radial monitor', dimension=1)
    spec['source']['cross_spec.py'] = Baseline_HashFile(Path(__file__))
    digest = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    case_id = f'geometry_cross_p3_shrink_{kind}_x{factor}_{digest[:12]}'
    spec.update(fingerprint=digest, experiment_id=case_id, case_id=case_id)
    return spec


def Cross_GetPlan(root):
    production = Cross_GetSpec(root)
    return [production, Cross_GetSpec(root, 'full_reference', 2),
            Cross_GetSpec(root, 'time_half', replay=production['experiment_id'])]
