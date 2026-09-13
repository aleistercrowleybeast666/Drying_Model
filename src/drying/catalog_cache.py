"""Read-only per-item availability. A partial dataset never gates an entire mode."""
from datetime import datetime
from .artifact_contract import Artifact_GetStatus,Artifact_GetIdentity,Artifact_ReadManifest
from .pipeline_plan import Catalog_Read


def Catalog_ScanCache(root,catalog=None,deep=True):
    catalog=Catalog_Read(root) if catalog is None else catalog
    identity=Artifact_GetIdentity(root);hashes={};states={}
    manifests={f:Artifact_ReadManifest(root,f+'.scan') for f in ['official','innovation','plot','validation']}
    def Cache_Get(key):
        if key not in states:
            states[key]=Artifact_GetStatus(root,key,deep,hashes,identity,manifests)
        return states[key]
    def Cache_GetTargets(row):
        if row.get('data_kind')=='alias':
            return [a for k in row['targets'] for a in Cache_GetTargets(catalog[k])]
        return [row.get('artifact',row['selection_key'])]
    labels={r.get('artifact',k):r['display_name_zh'] for k,r in catalog.items()}
    items={}
    for key,row in catalog.items():
        own=[Cache_Get(k) for k in dict.fromkeys(Cache_GetTargets(row))]
        required=dict.fromkeys([*row.get('requires',[]),*row.get('validation_requires',[])])
        missing=[dict(key=k,label=labels.get(k,k),reason=Cache_Get(k).get('reason','缺少完整数据'))
                 for k in required if not Cache_Get(k)['complete']]
        complete=all(s['complete'] for s in own) and not missing
        enabled=row['mode'] in ['A','B'] or not missing
        items[key]=dict(enabled=enabled,complete=complete,missing=missing,
            status='缺少：'+ '、'.join(m['label'] for m in missing) if not enabled else
                ('已生成' if row['mode']=='C' else '已有验证缓存' if row['mode']=='D' else '已缓存') if complete else
                '缓存失效' if any(s['status']=='STALE' for s in own) else
                '可生成' if row['mode']=='C' else '可验证' if row['mode']=='D' else '需计算')
    official={case:Cache_Get('official.'+case).get('entry',{}).get('status',{})
              for case in ['q1','q23','q4'] if Cache_Get('official.'+case)['complete']}
    return dict(items=items,official=official,scanned_at=datetime.now().astimezone().isoformat(timespec='seconds'),
                checked_files=len(hashes),deep=deep)
