"""Bounded integration check of the real cold-start router; zero trajectory solves.

Run only in a relocated disposable release copy WITHOUT results or work.
The worker prepares real raw inputs and checks libraries; the substituted task
plan is confined to this diagnostic process and does not alter production code.
"""
import json
import sys
from pathlib import Path


def Smoke_Run():
    from drying.runtime import Runtime_GetRoot
    root=Runtime_GetRoot()
    if '--worker' in sys.argv:
        from drying.inputs import Input_Prepare
        from drying.recompute import Recompute_RuntimeCheck
        Input_Prepare(root,root/'data/raw')
        Recompute_RuntimeCheck()
        (root/'results/startup_smoke.json').write_text(json.dumps(
            dict(status='PASS',scope='startup only; no production PDE solve')),encoding='utf-8')
        return 0
    assert getattr(sys,'frozen',False),'Run with the release EXE'
    assert not (root/'results').exists() and not (root/'work').exists(),'Requires a fresh disposable copy'
    import drying.recompute as router
    router.Recompute_GetPlan=lambda selected:[dict(key='startup-smoke',label='冷启动实际任务调用（零轨迹求解）',
        script='scripts/smoke_release_cold.py',args=['--worker'])]
    code=router.Recompute_Main(root,['--official','q1'])
    assert code==0,code
    assert (root/'results/startup_smoke.json').is_file()
    receipt=json.loads((root/'work/recompute/work/router_receipts.json').read_text(encoding='utf-8'))
    assert all(not Path(value).is_absolute() for value in receipt['startup-smoke']['command'])
    print(json.dumps(dict(status='PASS',missing_results_recreated=True,actual_worker_started=True,
        relative_receipt_paths=True,production_pde_solves=0),ensure_ascii=False),flush=True)
    return 0


if __name__=='__main__':raise SystemExit(Smoke_Run())
