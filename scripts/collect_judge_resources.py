"""Read existing same-science RSS/cost evidence; never start a numerical solve."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from drying.judge_progress import Progress_GetIdentity
from drying.cases import Case_GetSourceHash


def Resource_Collect(root=ROOT):
    identity=Progress_GetIdentity(root);peaks={};costs={};sources=[]
    # Archived successful table runs already measured their actual resident
    # memory. Read evidence only; no dependency on an installed old release.
    for path in (root/'work').glob('release_v*/progress_warm_benchmark.json'):
        value=json.loads(path.read_text(encoding='utf-8'));timing=value.get('timings',{})
        if value.get('returncode')!=0 or timing.get('progress_identity')!=identity:continue
        for row in timing.get('tasks',[]):
            if row.get('status')!='PASS' or not row['key'].startswith('A.'):continue
            peak=row.get('peak_rss_mb') or row.get('result',{}).get('production',{}).get('peak_rss_bytes',0)/2**20
            if peak:peaks['original']=max(peaks.get('original',0),peak)
        sources.append(path.relative_to(root).as_posix())
    for path in (root/'work/cache').glob('*/status.json'):
        row=json.loads(path.read_text(encoding='utf-8'))
        if not row.get('complete') or row.get('dim')!=2 or row.get('source_hash')!=Case_GetSourceHash(root):continue
        tag=row.get('tag') or '';case=row['case']
        part='base' if not tag else 'time_half' if tag=='half_steps' else 'radial' if 'radial' in tag else 'axial' if 'axial' in tag else None
        if part is None:continue
        kind='twod_'+part;peak=row.get('peak_rss_bytes',0)/2**20
        if peak:peaks[kind]=max(peaks.get(kind,0),peak)
        key='B.2d.'+case+'.'+part
        if row.get('wall_s',0)>costs.get(key,{}).get('wall_s',0):
            costs[key]=dict(wall_s=row['wall_s'],peak_rss_mb=peak,source=path.relative_to(root).as_posix(),confidence='rough',steps=row['steps'])
        sources.append(path.relative_to(root).as_posix())
    for path in (root/'work/validation').glob('*_2d_endpoint_*.json'):
        row=json.loads(path.read_text(encoding='utf-8'));case=path.name.split('_')[0]
        if not row.get('complete') or not row.get('wall_s'):continue
        base=root/'work/cache'/row['base_id']/'status.json'
        if not base.exists() or json.loads(base.read_text(encoding='utf-8')).get('fingerprint')!=row['base_fingerprint']:continue
        costs['B.2d.'+case+'.endpoint.'+row['direction']]=dict(wall_s=row['wall_s'],source=path.relative_to(root).as_posix(),confidence='rough',steps=row['steps'])
    # Unknown 2D purposes retain the conservative 2 GiB fallback. Measured
    # memories get a further 30% safety margin in the admission model.
    value=dict(identity=identity,peak_rss_mb=peaks,costs=costs,sources=sources,
        policy='Historical same-identity table RSS and complete same-source 2D evidence; timings are display-only and RSS is not a numerical parameter')
    (root/'configs/judge_resource_reference.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return value


if __name__=='__main__':
    result=Resource_Collect();print('cost records',len(result['costs']),'RSS kinds',result['peak_rss_mb'])
