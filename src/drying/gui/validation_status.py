"""Build validation view data exclusively from published evidence and checker results."""
from dataclasses import dataclass
import json
from pathlib import Path

TWO_D_MAIN=("现有径向/轴向加密及终点稳定性检查支持二维模型用于端面效应和降维合理性分析。"
            "二维结果不作为官方 Excel 或正式烘干时间来源。")
TWO_D_DETAIL=("当前二维验证采用按用途设计的辅助验收；未把全时域径向+轴向联合系统加密作为本模型的正式结果认证要求。"
              "局部早期边界层仍存在网格敏感性。")

@dataclass
class ValidationRow:
    key:str; label:str; status:str; detail:str


def _read(path,default=None):
    try:return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError,ValueError):return default


def evidence_rows(root):
    root=Path(root);status=_read(root/"results/status.json",{});questions=status.get("questions",{})
    def passed(keys,field):return bool(keys) and all(questions.get(k,{}).get(field) for k in keys)
    mass=_read(root/"work/validation/mass_balance/summary.json",{})
    auxiliary=_read(root/"work/validation/auxiliary_2d/summary.json",{})
    exports=_read(root/"work/diagnostics/export_manifest.json",{}).get("outputs",[])
    return [
      ValidationRow("q1_time","Q1 时间收敛","PASS" if passed(["q1"],"time_convergence_passed") else "WARNING","已有证据"),
      ValidationRow("q1_space","Q1 空间收敛","PASS" if passed(["q1"],"spatial_convergence_passed") else "WARNING","已有证据"),
      ValidationRow("q23_time","Q2/Q3 时间收敛","PASS" if passed(["q2","q3"],"time_convergence_passed") else "WARNING","共享 q23 轨迹"),
      ValidationRow("q23_space","Q2/Q3 空间收敛","PASS" if passed(["q2","q3"],"spatial_convergence_passed") else "WARNING","共享 q23 轨迹"),
      ValidationRow("q4_time","Q4 时间收敛","PASS" if passed(["q4"],"time_convergence_passed") else "WARNING","已有证据"),
      ValidationRow("q4_space","Q4 空间收敛","PASS" if passed(["q4"],"spatial_convergence_passed") else "WARNING","已有证据"),
      ValidationRow("mass","水质量守恒","PASS" if mass.get("status")=="PASS" else "WARNING",f"{mass.get('completed_case_count',0)}/12；已有证据"),
      ValidationRow("auxiliary","二维辅助验收","PASS" if auxiliary.get("two_dimensional_auxiliary_validation_passed") else "WARNING","端面效应 / 降维核验；已有证据"),
      ValidationRow("excel","官方 Excel","PASS" if len(exports)==4 and all(x.get("readback","").startswith("PASSED") for x in exports) else "WARNING",f"{len(exports)}/4；已有证据"),
      ValidationRow("facts","paper_facts","PASS" if (root/"results/paper_facts.json").is_file() and (root/"results/paper_facts.md").is_file() else "FAIL","已有证据"),
    ]


def apply_checker_result(rows,checker,returncode,error=""):
    status="PASS" if returncode==0 else "FAIL";detail="本次快速检查通过" if returncode==0 else (error or "检查命令返回非零退出码")
    targets={"results":{"q1_time","q1_space","q23_time","q23_space","q4_time","q4_space","excel","facts"},"mass":{"mass"},"auxiliary":{"auxiliary"}}
    for row in rows:
        if row.key in targets.get(checker,set()):row.status=status;row.detail=detail
    return rows


def auxiliary_text(rows):
    status=next((row.status for row in rows if row.key=="auxiliary"),"NOT_RUN")
    return ("二维辅助验收：PASS。" if status=="PASS" else "二维辅助验收：尚无通过证据。")+TWO_D_MAIN
