"""Calibrate display weights from a successful measured run; no solving."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from drying.judge_progress import Progress_GetIdentity,Progress_Hash,PREPARATION


def Progress_GenerateReference(source,output):
    record=json.loads(source.read_text(encoding='utf-8'))
    if record.get('returncode',0)!=0 or not record.get('tasks') or any(x['status']!='PASS' for x in record['tasks']):
        raise ValueError('REFERENCE_REQUIRES_SUCCESSFUL_RUN')
    tasks={}
    for row in record['tasks']:
        if row.get('cache_reused'):continue
        value=dict(wall_s=row['wall_s'])
        status=row.get('result',{}).get('production')
        if status:
            value.update(accepted_steps=status['steps'],actual_end_s=status['actual_end_s'],
                stages=[{key:s[key] for key in ['t_start','t_end','nr','nz','steps','wall_s','actual_dt_mean']} for s in status['stages']])
        tasks[row['key']]=value
    if not all('A.'+c in tasks for c in ['q1','q23','q4']):raise ValueError('REFERENCE_REQUIRES_COLD_A')
    total=record['preparation_and_jit_s']
    phases=record.get('progress',{}).get('preparation_phases_s',{})
    preparation=[(k,label,max(.01,phases.get(k,cost*total/sum(p[2] for p in PREPARATION)))) for k,label,cost in PREPARATION]
    value=dict(schema_version=1,generated_at=datetime.now(timezone.utc).isoformat(),source_run=source.relative_to(ROOT).as_posix(),
        identity=Progress_GetIdentity(ROOT),tasks=tasks,preparation=preparation,
        preparation_basis='measured phases' if phases else 'measured total; estimated subdivision until next instrumented cold run',
        policy='Display only. Stale/corrupt resources fall back without changing scientific fingerprints or results.')
    value['seal']=Progress_Hash(value);output.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,default=ROOT/'work/release_v2/cold_benchmark.json')
    parser.add_argument('--output',type=Path,default=ROOT/'configs/progress_reference.json')
    args=parser.parse_args();Progress_GenerateReference(args.source.resolve(),args.output.resolve())
