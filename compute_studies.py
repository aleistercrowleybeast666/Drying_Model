"""Compute extension experiments without changing the frozen official production."""
import argparse
import json
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
from drying.studies.scheduler import Studies_Run


def Studies_Main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--group',choices=['verify','postprocess','geometry','environment','thermal','all','geometry_cross','refine2d','mass_balance'],default='all')
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--payload-only',action='store_true')
    parser.add_argument('--solve-only',action='store_true',help='final technical groups: compute independent trajectories without publishing tables')
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--refine-force-full',action='store_true',help='optional 60x188 group: explicitly bypass the measured 1 h per-case cost gate')
    parser.add_argument('--refine-probe-only',action='store_true',help='retain measured 2D probe and resumable partial cache while prioritizing mandatory work')
    parser.add_argument('--output-status-only',action='store_true',help='refresh human-readable overview from sealed data and render receipts; no solves or exports')
    parser.add_argument('--case',choices=['q1','q23','q4'])
    parser.add_argument('--mode',choices=['M00','M10','M01','M11'],help='filter thermal jobs in all/thermal; other groups use frozen M00')
    args=parser.parse_args()
    if args.solve_only and args.payload_only:parser.error('--solve-only and --payload-only are mutually exclusive')
    if args.refine_force_full and args.refine_probe_only:parser.error('choose either full refinement or probe only')
    root=Path(__file__).resolve().parent
    if args.mode not in [None,'M00'] and args.group not in ['all','thermal','mass_balance']:
        parser.error('--mode M10/M01/M11 applies only to --group all, thermal or mass_balance')
    if args.output_status_only:
        from drying.studies.synthesis import Synthesis_RefreshOverview
        return Synthesis_RefreshOverview(root)
    if args.dry_run:
        if args.group == 'mass_balance':
            from drying.studies.mass_balance import MassBalance_Run
            return MassBalance_Run(root,args)
        if args.group in ['geometry_cross','refine2d']:
            from drying.studies.technical_run import Technical_Run
            return Technical_Run(root,args)
        return Studies_Run(root,args)
    folder=root/'work/studies';folder.mkdir(parents=True,exist_ok=True);lock=folder/'compute.lock'
    try:
        descriptor=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:
        import psutil
        previous=json.loads(lock.read_text(encoding='utf-8'))
        if psutil.pid_exists(previous['pid']):
            raise SystemExit(f"STUDY_WORKER_ALREADY_RUNNING: PID {previous['pid']}; only one heavy study worker is allowed")
        lock.unlink();descriptor=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    try:
        os.write(descriptor,json.dumps(dict(pid=os.getpid())).encode());os.close(descriptor)
        if args.group == 'mass_balance':
            from drying.studies.mass_balance import MassBalance_Run
            if int(MassBalance_Run(root,args)) == 2:raise SystemExit(1)
        elif args.group in ['geometry_cross','refine2d']:
            from drying.studies.technical_run import Technical_Run
            result=Technical_Run(root,args)
            if int(result)==2:raise SystemExit(1)
        else:Studies_Run(root,args)
    finally:
        lock.unlink(missing_ok=True)


if __name__=='__main__':Studies_Main()
