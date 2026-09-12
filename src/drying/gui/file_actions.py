"""Centralized opening of local files and directories."""
import os
from pathlib import Path
import subprocess
import sys


def open_path(path: Path) -> None:
    path=Path(path)
    if not path.exists(): raise FileNotFoundError(f"结果文件缺失：{path}")
    if sys.platform == "win32": os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin": subprocess.Popen(["open", str(path)])
    else: subprocess.Popen(["xdg-open", str(path)])
