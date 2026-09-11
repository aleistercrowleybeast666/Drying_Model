"""Record compute artifacts before plot.py to verify plotting cannot alter them."""
import hashlib
import json
from pathlib import Path


def Baseline_Capture(root):
    root=Path(root)
    files={}
    for directory in ['work/cache','work/checkpoints','work/plot_payload','results/tables']:
        for path in (root/directory).rglob('*'):
            if path.is_file():
                stat=path.stat()
                files[path.relative_to(root).as_posix()]=dict(size=stat.st_size,mtime_ns=stat.st_mtime_ns)
    core={name:hashlib.sha256((root/'src/drying'/name).read_bytes()).hexdigest() for name in
        ['materials.py','boundaries.py','operators.py','rk4.py','sampling.py','inputs.py','events.py','geometry.py',
         'cases.py','mesh.py','stages.py','validation.py']}
    destination=root/'work/validation/plot_decoupling_baseline.json'
    destination.write_text(json.dumps(dict(files=files,core=core,
        scope='All existing solver caches/checkpoints, Excel and plot payload; rendering must not modify any'),indent=2),encoding='utf-8')
    print(f'PLOT_BASELINE_CAPTURED: {len(files)} files')


if __name__=='__main__':
    Baseline_Capture(Path(__file__).resolve().parents[1])
