"""Console entry. No arguments means the complete offline workflow."""
import os
import sys
from pathlib import Path


def main():
    root = Path(os.environ.get('DRYING_MODEL_ROOT') or
        (Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent)).resolve()
    os.environ['DRYING_MODEL_ROOT'] = str(root)
    code = root/'code' if (root/'code/src').is_dir() else root
    if (root/'dependencies/application/code/src').is_dir():code=root/'dependencies/application/code'
    sys.path.insert(0, str(code/'src'))
    if sys.stdout is not None and hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    if sys.stderr is not None and hasattr(sys.stderr, 'reconfigure'): sys.stderr.reconfigure(encoding='utf-8')
    from drying.recompute import Recompute_Main
    return Recompute_Main(root)


if __name__ == '__main__':
    result = main()
    # A console created solely for this EXE indicates Explorer/double-click launch.
    if getattr(sys, 'frozen', False) and os.name == 'nt' and not sys.argv[1:]:
        import ctypes
        processes = (ctypes.c_ulong*4)()
        if ctypes.windll.kernel32.GetConsoleProcessList(processes, 4) == 1:
            input('按回车键退出')
    raise SystemExit(result)
