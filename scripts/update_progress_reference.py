"""Import matching successful timings and historical 2D/thermal costs; never solve."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from drying.judge_progress import Progress_GetIdentity,Progress_Hash,Progress_ReadReference


def Progress_ImportTimings(source,root=ROOT):
    data=json.loads(Path(source).read_text(encoding='utf-8'));identity=Progress_GetIdentity(root)
    if data.get('progress_identity')!=identity:raise ValueError('PROGRESS_SCIENTIFIC_IDENTITY_MISMATCH')
    if not data.get('tasks') or any(t.get('status')!='PASS' for t in data['tasks']):raise ValueError('SUCCESSFUL_TIMINGS_REQUIRED')
    reference=Progress_ReadReference(root)
    if not reference:raise ValueError('VALID_BASE_REFERENCE_REQUIRED')
    reference.pop('seal',None)
    for row in data['tasks']:
        if data.get('progress_scope_version')!=4 and not row['key'].startswith(('A.','D.M10.','D.M01.','D.M11.','D.full.')):continue
        if row.get('cache_reused') or row.get('wall_s',0)<=0:continue
        entry=reference['tasks'].setdefault(row['key'],{});entry['wall_s']=row['wall_s']
        status=row.get('result',{}).get('production')
        if status and status.get('stages'):
            entry.update(accepted_steps=status['steps'],actual_end_s=status.get('actual_end_s',status['cap']),
                stages=[{k:s[k] for k in ['t_start','t_end','nr','nz','steps','wall_s','actual_dt_mean']} for s in status['stages']])
    reference.update(import_source=Path(source).name,generated_at=datetime.now(timezone.utc).isoformat())
    reference['seal']=Progress_Hash(reference)
    (root/'configs/progress_reference.json').write_text(json.dumps(reference,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def Progress_CollectHistory(root=ROOT):
    from drying.cases import Case_GetSourceHash
    identity=Progress_GetIdentity(root);records=[]
    for path in (root/'work/cache').glob('*/status.json'):
        row=json.loads(path.read_text(encoding='utf-8'))
        if row.get('dim')!=2 or not row.get('complete') or row.get('source_hash')!=Case_GetSourceHash(root):continue
        if row.get('wall_s',0)<=0 or row.get('steps',0)<=0:continue
        records.append(dict(case=row['case'],nr=row['nr'],nz=row['nz'],wall_s=row['wall_s'],steps=row['steps'],
            actual_dt_mean=row.get('actual_dt_mean'),time_range=[0,row['cap']],purpose=row.get('tag') or 'base',
            source=path.relative_to(root).as_posix(),fingerprint=row['fingerprint']))
    thermal=[]
    from drying.cases import Case_LoadConfig
    import hashlib
    config=Case_LoadConfig(root)
    for path in (root/'work/studies/experiments').glob('*/status.json'):
        row=json.loads(path.read_text(encoding='utf-8'))
        if not row.get('complete') or row.get('wall_s',0)<=0:continue
        spec_path=path.with_name('spec.json')
        if not spec_path.exists():continue
        spec=json.loads(spec_path.read_text(encoding='utf-8'))
        if spec.get('physics')!=config['physics'] or spec.get('numerics')!=config['numerics']:continue
        if any(not (root/'src/drying/studies'/name).is_file() or hashlib.sha256((root/'src/drying/studies'/name).read_bytes()).hexdigest()!=digest for name,digest in spec.get('source',{}).items()):continue
        if 'geometry_cross' in spec['experiment_id']:continue
        thermal.append(dict(case=spec['case'],mode=spec['mode'],kind=spec['kind'],tail_minutes=spec['tail_minutes'],
            schedule=spec['schedule'],steps=row['steps'],wall_s=row['wall_s'],source=path.relative_to(root).as_posix()))
    value=dict(schema_version=1,identity=identity,records=records,trajectory_records=thermal,generated_at=datetime.now(timezone.utc).isoformat(),
        policy='Measured 2D step-cell costs only; no 1D multiplier. Historic full results are read-only.')
    value['seal']=Progress_Hash(value)
    (root/'configs/progress_2d_reference.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return value


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('timings',type=Path,nargs='?');parser.add_argument('--collect-2d',action='store_true')
    args=parser.parse_args()
    if args.timings:Progress_ImportTimings(args.timings)
    if args.collect_2d:print(json.dumps(dict(records=len(Progress_CollectHistory()['records']))))
