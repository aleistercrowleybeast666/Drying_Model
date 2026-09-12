"""Render real study artifacts with solver imports forbidden and file hashes checked."""
import importlib.abc
import runpy
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from drying.studies.baseline import Baseline_Check,Baseline_HashFile,Baseline_ReadJson
from drying.studies.plot_contract import StudyPlot_ReadManifest
from drying.storage import Storage_WriteJson


class RenderSolverImportGuard(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        forbidden=['drying.rk4','drying.operators','drying.cases','drying.studies.trajectory','drying.studies.thermal','drying.studies.analysis','drying.studies.synthesis']
        if any(fullname==name or fullname.startswith(name+'.') for name in forbidden):
            raise RuntimeError('SOLVER_IMPORT_DURING_RENDER: '+fullname)
        return None


def Render_Check():
    manifest=StudyPlot_ReadManifest(ROOT);baseline_before=Baseline_Check(ROOT)
    frozen=Baseline_ReadJson(ROOT/'work/baseline_snapshot/baseline_manifest.json');files={};core={}
    for name,record in frozen['protected_files'].items():
        if name.startswith('work/cache/'):
            stat=(ROOT/name).stat();files[name]=dict(size=stat.st_size,mtime_ns=stat.st_mtime_ns,sha256=record['sha256'])
        elif name.startswith('src/drying/'):core[Path(name).name]=record['sha256']
    Storage_WriteJson(ROOT/'work/studies/validation/publication_cache_baseline.json',dict(files=files,core=core))
    paths={entry['path'] for entry in manifest['data_files']}
    paths.add('work/studies/plot_payload/study_manifest.json')
    for key,status in manifest['statuses'].items():
        if key in manifest['baseline_keys'].values():continue
        folder='work/studies/experiments/'+key+'/'
        paths.update(folder+name for name in status['data_files'])
        paths.update([folder+'spec.json',folder+'status.json'])
    before={name:Baseline_HashFile(ROOT/name) for name in sorted(paths)}
    sys.meta_path.insert(0,RenderSolverImportGuard())
    sys.argv=[str(ROOT/'plot_studies.py'),*sys.argv[1:]]
    runpy.run_path(str(ROOT/'plot_studies.py'),run_name='__main__')
    changed=[name for name,digest in before.items() if not (ROOT/name).is_file() or Baseline_HashFile(ROOT/name)!=digest]
    baseline_after=Baseline_Check(ROOT)
    report=dict(status='PASS' if not changed else 'FAIL',changed=changed,checked_study_files=len(before),
        frozen_baseline_before=baseline_before,frozen_baseline_after=baseline_after,solver_imports_forbidden=True)
    Storage_WriteJson(ROOT/'work/studies/validation/render_isolation.json',report)
    if changed:raise RuntimeError('NUMERICAL_DATA_CHANGED_DURING_RENDER: '+', '.join(changed))
    print(f"RENDER_ISOLATION_PASS {len(before)} study files and {baseline_after['protected_files']} frozen files",flush=True)


if __name__=='__main__':Render_Check()
