"""Render the sealed payload; missing data is an error and never triggers a solve."""
import sys
from pathlib import Path

_ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(_ROOT/'src'))


def Plot_Main():
    from drying.diagnostics import Diagnostics_Open, Diagnostics_RecordException
    from drying.presentation import Presentation_Run
    Diagnostics_Open(_ROOT)
    try:
        Presentation_Run(_ROOT)
        print('PLOT_COMPLETE: 14 PNG, 5 GIF; PDE solves=0',flush=True)
        return 0
    except Exception as error:
        Diagnostics_RecordException(_ROOT,str(error).split(':')[0],error,phase='plot')
        print(str(error),file=sys.stderr)
        return 1


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(Plot_Main())
