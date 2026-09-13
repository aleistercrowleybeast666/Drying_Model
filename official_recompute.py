"""Independent table-only entry, with no imports from the full GUI pipeline."""
import os
from pathlib import Path
import sys


def main():
    root=(Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else
          Path(os.environ.get('DRYING_OFFICIAL_ROOT',Path(__file__).resolve().parent)).resolve())
    os.environ['NUMBA_CACHE_DIR']=str(root/'work/numba_cache')
    os.environ['DRYING_JUDGE_FROZEN_MESH']='1'
    for name in ['OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS','NUMBA_NUM_THREADS']:os.environ[name]='1'
    code=root/'dependencies/application/code' if (root/'dependencies/application/code/src').is_dir() else root
    sys.path.insert(0,str(code/'src'))
    for stream in [sys.stdout,sys.stderr]:
        if stream is not None and hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')
    from drying.official_cli import Official_Main
    return Official_Main(root)


if __name__=='__main__':
    result=main()
    if getattr(sys,'frozen',False) and os.name=='nt' and not sys.argv[1:] and sys.stdin and sys.stdin.isatty():
        import ctypes
        pids=(ctypes.c_ulong*4)()
        if ctypes.windll.kernel32.GetConsoleProcessList(pids,4)==1:
            try:input('按回车键退出')
            except EOFError:pass
    raise SystemExit(result)
