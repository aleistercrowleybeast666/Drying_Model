"""Render the sealed payload; missing data is an error and never triggers a solve."""
import sys
import argparse
from pathlib import Path

_ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(_ROOT/'src'))


def Plot_Main():
    parser=argparse.ArgumentParser(description='仅从独立 payload 绘图，不求解 PDE')
    parser.add_argument('--gif',choices=['all','cutaway'],default='all',help='cutaway 仅重画斜砍 GIF，保留其他四个 GIF；PNG 正常更新')
    args=parser.parse_args()
    from drying.diagnostics import Diagnostics_Open, Diagnostics_RecordException
    from drying.presentation import Presentation_Run
    Diagnostics_Open(_ROOT)
    try:
        Presentation_Run(_ROOT,gif_scope=args.gif)
        print('PLOT_COMPLETE: 14 PNG, 5 GIF; PDE solves=0',flush=True)
        return 0
    except Exception as error:
        Diagnostics_RecordException(_ROOT,str(error).split(':')[0],error,phase='plot')
        print(str(error),file=sys.stderr)
        return 1


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(Plot_Main())
