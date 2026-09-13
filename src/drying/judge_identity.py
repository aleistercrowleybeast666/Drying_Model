"""Effective trajectory spec for exact aliases; display roles are separate."""
import json
from pathlib import Path
from .judge_progress import Progress_GetIdentity
from .runtime import Runtime_GetCode


def Identity_Attach(root,jobs):
    from .cases import Case_LoadConfig
    code=Runtime_GetCode(Path(root))
    if not (code/'configs/default.toml').exists():return
    config=Case_LoadConfig(code)
    manifest=json.loads((code/'configs/frozen_mesh/manifest.json').read_text(encoding='utf-8'))
    schedules=manifest['schedules'];identity=Progress_GetIdentity(root)
    from .studies.selection import Selection_GetFactor
    for job in jobs:
        if not job['pde']:continue
        case=job['case'];kind=job['kind'];role=job.get('experiment_kind','production')
        factor=job.get('factor',Selection_GetFactor(code,case,job.get('mode','M00'))*(2 if role=='full_reference' else 1))
        effective=dict(scientific_sources=identity,case=case,mode=job.get('mode','M00'),physics=config['physics'],numerics=config['numerics'],
            schedule=[dict(s,nr=s['nr']*factor) for s in schedules[case]],initial_origin='uniform' if role!='tail' else 'M00_at_14400',
            shrink=case=='q4' and role!='fixed_radius',dt=.125 if role=='time_half' else .25,
            replay_partition='matching_production_accepted_steps' if role=='time_half' else None,
            tail_minutes=job.get('tail_minutes',60),geometry_cross=job.get('cross',False))
        if kind in ['experiment','reference_1d']:
            effective['execution_partition']='trajectory_original_schedule'
            if role=='matched':effective.update(schedule=[dict(t_start=0,t_end=schedules[case][-1]['t_end'],nr=config['mesh']['base_nr'],nz=1)],mesh_origin='base_2d_radial')
            if role=='tail':effective['schedule']=[dict(s,t_start=max(14400,s['t_start'])) for s in effective['schedule'] if s['t_end']>14400]
        else:
            # Composite evidence and different accepted/output partitions are
            # explicitly distinct until a byte-level equivalence is established.
            effective['execution_partition']=kind
            effective['horizon_policy']='real_report' if kind=='original' else 'full_horizon'
        job['numerical_spec']=effective


def Identity_CheckQ1Alias(root):
    from .cases import Case_ReadStatus,Case_LoadConfig
    from .frozen_mesh import Frozen_ReadManifest
    from .table_reference import Table_CheckReference
    root=Path(root);source=json.loads((root/'work/recompute/production.json').read_text(encoding='utf-8'))['q1']
    status=Case_ReadStatus(root,source['case_id']);config=Case_LoadConfig(root)
    expected=Frozen_ReadManifest(root)['schedules']['q1']
    if not (status['complete'] and status['case']=='q1' and status['dim']==1 and status['schedule']==expected
            and status['dt']==config['numerics']['dt_s']==.25 and status['actual_end_s']==status['cap']==1800
            and status.get('event') is None and status['physics']==config['physics'] and status['numerics']==config['numerics']):
        raise RuntimeError('Q1_FULL_ALIAS_SPEC_MISMATCH')
    Table_CheckReference(root,'q1',status)
    return status
