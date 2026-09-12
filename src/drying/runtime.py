"""Presentation/runtime paths only. Numerical sources keep their original layout."""
import os
import sys
from pathlib import Path


def Runtime_GetRoot():
    if os.environ.get('DRYING_MODEL_ROOT'):
        return Path(os.environ['DRYING_MODEL_ROOT']).resolve()
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def Runtime_GetCode(root=None):
    root = Path(root or Runtime_GetRoot())
    if (root/'dependencies/application/code/src').is_dir():return root/'dependencies/application/code'
    return root/'code' if (root/'code/src').is_dir() else root


def Runtime_GetData(root=None):
    root=Path(root or Runtime_GetRoot())
    return root/'data' if (root/'data').is_dir() else root/'dependencies/application/data'


def Runtime_BuildRecomputeCommand(arguments, root=None):
    root = Path(root or Runtime_GetRoot())
    if getattr(sys, 'frozen', False):
        return [str(root/'药材烘干模型_完整离线复算.exe'), *arguments]
    entry = root/'药材烘干模型_完整离线复算.py'
    if not entry.exists(): entry = Runtime_GetCode(root)/'offline_recompute.py'
    return [sys.executable, '-u', str(entry), *arguments]
