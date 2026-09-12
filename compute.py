"""Compute/validate/export and seal the plot payload. Never renders PNG or GIF."""
import argparse
import json
import sys
import time
from pathlib import Path

_ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(_ROOT/'src'))


class ComputeStopped(Exception):
    """Cooperative orchestration stop after the previous phase saved its cache."""


def Compute_Main():
    parser=argparse.ArgumentParser(description='计算、验证、导出并生成独立绘图数据；不生成 PNG/GIF')
    options=parser.add_mutually_exclusive_group()
    options.add_argument('--payload-only',action='store_true',help='仅从已有有效计算缓存刷新绘图数据，不解 PDE')
    options.add_argument('--resume-finalize',action='store_true',help='所有求解/验证/导出已完成时，从比较汇总与数据打包恢复')
    parser.add_argument('--case',choices=['q1','q23','q4'],help='只重新计算并导出所选正式 M00 轨迹；省略时保持原完整流程')
    parser.add_argument('--official-only',action='store_true',help='仅完成所选一维正式验证和 Excel；跨问二维/综合绘图由统一路由稍后执行')
    parser.add_argument('--two-dimensional-only',action='store_true',help='已有全部正式一维轨迹后，运行二维验证并生成综合绘图数据')
    args=parser.parse_args()
    if args.official_only and (not args.case or args.two_dimensional_only or args.payload_only):
        parser.error('--official-only requires --case and cannot combine with other modes')
    from drying.cases import Case_LoadConfig, Case_ReadStatus, Case_SolvePairEvents
    from drying.inputs import Input_Prepare
    from drying.mesh import Mesh_PrepareCase
    from drying.validation import Validation_Run
    from drying.stages import Stage_Validate
    from drying.export import Export_Run
    from drying.comparison import Comparison_EnsureQuestions
    from drying.outputs import Output_PrepareFolders, Output_UpdateStatus
    from drying.overview import Overview_Write
    from drying.plot_payload import Payload_Prepare
    from drying.storage import Storage_WriteJson
    from drying.diagnostics import Diagnostics_Open, Diagnostics_RecordException
    Output_PrepareFolders(_ROOT); Diagnostics_Open(_ROOT)
    start=time.perf_counter(); phase='prepare'
    path=_ROOT/'work/diagnostics'/('payload_status.json' if args.payload_only else 'compute_status.json')
    prior_wall=json.loads(path.read_text(encoding='utf-8')).get('wall_s',0.) if args.resume_finalize and path.exists() else 0.
    def Record(status,**extra):
        if status=='RUNNING' and (_ROOT/'work/studies/BASELINE_STOP').exists():
            raise ComputeStopped('STOPPED_AT_PHASE_BOUNDARY: completed numerical phases retain their checkpoints')
        Storage_WriteJson(path,dict(status=status,phase=phase,wall_s=prior_wall+time.perf_counter()-start,**extra))
    try:
        Record('RUNNING')
        cfg=Case_LoadConfig(_ROOT)
        if cfg['stage_mesh']['mode'] not in ('fixed','stage_schedule','early_refined_stage_schedule'):
            raise ValueError('INPUT_VALUE_INVALID: stage_mesh.mode')
        if cfg['stage_mesh'].get('two_dimensional_mode','fixed') != 'fixed':
            raise ValueError('INPUT_VALUE_INVALID: this implementation keeps 2D fixed')
        if not args.payload_only and not args.resume_finalize:
            Input_Prepare(_ROOT,_ROOT/'data/raw')
            selected_cases=[args.case] if args.case else ['q1','q23','q4']
            for case in ([] if args.two_dimensional_only else selected_cases):
                phase=case+': mesh / fixed validation'; Record('RUNNING')
                Mesh_PrepareCase(_ROOT,case)
                Validation_Run(_ROOT,'1d',case)
                fixed=json.loads((_ROOT/'work/validation/summary.json').read_text(encoding='utf-8'))[case+'_1d']
                Storage_WriteJson(_ROOT/f'work/validation/{case}_fixed_summary.json',fixed)
                if cfg['stage_mesh']['mode'] in ('stage_schedule','early_refined_stage_schedule'):
                    phase=case+': stage validation'; Record('RUNNING')
                    Stage_Validate(_ROOT,case,fixed)
                phase=case+': official export'; Record('RUNNING')
                Export_Run(_ROOT,case)
            if args.official_only:
                evidence=json.loads((_ROOT/'work/validation/summary.json').read_text(encoding='utf-8'))[args.case+'_1d']
                if not (evidence.get('time_passed') and evidence.get('spatial_convergence_passed',evidence.get('spatial_passed'))):
                    raise RuntimeError('OFFICIAL_VALIDATION_FAILED: selected case did not pass its unchanged criteria')
                phase='complete'; Record('COMPLETE')
                print('OFFICIAL_CASE_COMPLETE: isolated selected 1D trajectory and Excel; combined 2D figures require the auxiliary task',flush=True)
                return 0
            for case in selected_cases:
                phase=case+': 2D verification'; Record('RUNNING')
                Validation_Run(_ROOT,'2d',case)
        if args.resume_finalize:
            evidence=json.loads((_ROOT/'work/validation/summary.json').read_text(encoding='utf-8'))
            for case in ['q1','q23','q4']:
                for dim in [1,2]:
                    item=evidence[f'{case}_{dim}d']; source=Case_ReadStatus(_ROOT,item['selected_id'])
                    if not source['complete'] or source['fingerprint']!=item['selected_fingerprint']:
                        raise RuntimeError('SPATIAL_REFERENCE_INCOMPLETE: finalize requires completed matching evidence')
        if not args.payload_only and not args.case:
            phase='paired endpoints'; Record('RUNNING')
            Case_SolvePairEvents(_ROOT)
        phase='comparison data'; Record('RUNNING')
        # 2D validation already prepared paired endpoints and current comparisons.
        # Rebuild only missing/stale comparison data, without another PDE solve.
        Comparison_EnsureQuestions(_ROOT)
        phase='status / plot payload'; Record('RUNNING')
        Output_UpdateStatus(_ROOT)
        status=json.loads((_ROOT/'results/status.json').read_text(encoding='utf-8'))
        if not status['official_output_generated']:
            raise RuntimeError('EXPORT_FAILED: current source/Excel mismatch; run the full compute entry')
        Payload_Prepare(_ROOT)
        phase='complete'; Record('COMPLETE')
        # Refresh only the tiny overview evidence and seal, avoiding another data pass.
        from drying.overview import Overview_Gather
        from drying.plot_contract import Payload_GetSeal
        from drying.storage import Storage_HashFiles
        manifest_path=_ROOT/'work/plot_payload/plot_manifest.json'
        manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
        evidence=Overview_Gather(_ROOT); evidence_path=_ROOT/manifest['overview_payload']
        Storage_WriteJson(evidence_path,evidence); Overview_Write(_ROOT,evidence)
        for item in manifest['payload_files']:
            if item['path']==manifest['overview_payload']:
                item.update(hash=Storage_HashFiles([evidence_path]),size_bytes=evidence_path.stat().st_size)
        manifest['manifest_hash']=Payload_GetSeal(manifest); Storage_WriteJson(manifest_path,manifest)
        print('COMPUTE_COMPLETE: Excel and sealed plot payload ready; PNG/GIF rendering deferred to plot.py',flush=True)
        return 0
    except ComputeStopped as error:
        Record('STOPPED',reason=str(error))
        print(str(error),flush=True)
        return 2
    except Exception as error:
        Record('FAILED',error=str(error))
        Diagnostics_RecordException(_ROOT,str(error).split(':')[0],error,phase=phase)
        try: Overview_Write(_ROOT)
        except Exception:
            (_ROOT/'results/overview.md').write_text(f'# 计算失败\n\n阶段：{phase}\n\n{error}\n',encoding='utf-8')
        return 1


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(Compute_Main())
