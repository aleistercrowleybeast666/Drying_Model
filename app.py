"""Launch the judge-friendly desktop interface (numerical work stays in CLIs)."""
from pathlib import Path
import sys
from enum import IntEnum

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from drying.gui.main_window import main


class AppCommandResult(IntEnum):
    """Compatibility result retained for existing command-layer callers."""
    READY = 0
    INVALID_SELECTION = 1
    PYTHON_MISSING = 2


def App_BuildCommand(root, task, action, group="all", case="all", mode="all"):
    """Compatibility adapter for the former GUI API; new views use CommandBuilder."""
    root=Path(root);python=root/".venv/Scripts/python.exe"
    # The compatibility API remains usable in source checkouts without the old Windows venv.
    if not python.is_file(): python=Path(sys.executable)
    if task not in {"baseline","studies"} or action not in {"compute","resume","plot","payload","dry_run"}:
        return AppCommandResult.INVALID_SELECTION, []
    if task=="baseline":
        command=[str(python),str(root/("plot.py" if action=="plot" else "compute.py"))]
        if action=="payload":command.append("--payload-only")
        if action=="dry_run":return AppCommandResult.INVALID_SELECTION,[]
        return AppCommandResult.READY,command
    if group not in {"all","verify","postprocess","geometry","environment","thermal"} or case not in {"all","q1","q23","q4"} or mode not in {"all","M00","M10","M01","M11"}:
        return AppCommandResult.INVALID_SELECTION,[]
    if group not in {"all","thermal"} and mode not in {"all","M00"}:return AppCommandResult.INVALID_SELECTION,[]
    command=[str(python),str(root/("plot_studies.py" if action=="plot" else "compute_studies.py"))]
    if action!="plot":
        command += ["--group",group]
        if action=="resume":command.append("--resume")
        if action=="payload":command += ["--resume","--payload-only"]
        if action=="dry_run":command.append("--dry-run")
        if case!="all":command += ["--case",case]
        if mode!="all":command += ["--mode",mode]
    return AppCommandResult.READY,command


if __name__ == "__main__":
    raise SystemExit(main())
