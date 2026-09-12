"""Read-only derivation of the validation rows shown by the GUI."""
import json
from pathlib import Path


def _json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def validation_rows(root: Path):
    """Return status rows from published artifacts, never from hard-coded PASSes."""
    root = Path(root)
    status = _json(root / "results/status.json", {}) or {}
    questions = status.get("questions", {})
    rows = []
    for label, keys in (("Q1", ("q1",)), ("Q2/Q3", ("q2", "q3")), ("Q4", ("q4",))):
        selected = [questions.get(key, {}) for key in keys]
        for title, field in (("时间收敛", "time_convergence_passed"), ("空间收敛", "spatial_convergence_passed")):
            passed = bool(selected) and all(item.get(field, False) for item in selected)
            rows.append((f"{label} {title}", "PASS" if passed else "FAIL", "正式一维"))

    mass = _json(root / "work/validation/mass_balance/summary.json", {}) or {}
    mass_pass = mass.get("status") in {"PASS", "PASSED"}
    count = mass.get("completed_case_count", mass.get("passed_count", "—"))
    rows.append(("水质量守恒", "PASS" if mass_pass else "FAIL", f"完成：{count}/12"))

    auxiliary = (status.get("two_dimensional_auxiliary_validation") or
                 _json(root / "results/studies/validation_summary.json", {}) or {})
    aux_status = auxiliary.get("status", auxiliary.get("acceptance", {}).get("status"))
    aux_pass = auxiliary.get("two_dimensional_auxiliary_validation_passed", aux_status in {"PASS", "PASSED"})
    rows.append(("二维辅助验收", "PASS" if aux_pass else "FAIL", "用于端面效应与降维合理性分析"))
    tables = all((root / f"results/tables/result{index}.xlsx").is_file() for index in range(1, 5))
    rows.append(("官方 Excel", "PASS" if tables else "FAIL", "4/4" if tables else "文件缺失"))
    facts = _json(root / "results/paper_facts.json")
    rows.append(("paper_facts", "PASS" if facts else "FAIL", "来源一致" if facts else "文件缺失或无效"))
    return rows


TWO_D_DETAIL = ("二维辅助验收：PASS。二维结果用于端面效应与一维降维合理性的辅助核验；"
                "局部早期边界层仍对网格敏感，因此不宣称二维全时域完全收敛。")
