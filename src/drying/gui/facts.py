"""Single-point access to the publication facts used by GUI views."""
from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class FactsResult:
    ready: bool
    data: dict
    message: str


def load_facts(root: Path) -> FactsResult:
    path = Path(root) / "results/paper_facts.json"
    if not path.is_file():
        return FactsResult(False, {}, f"结果文件缺失：{path.relative_to(root)}（不会自动重算）")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        official = data["official"]
        for question in ("Q1", "Q2", "Q3", "Q4"):
            official[question]["key_values"]
        return FactsResult(True, data, "结果数据已就绪")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return FactsResult(False, {}, f"无法读取 paper_facts：{exc}（不会自动重算）")


def official_cards(data: dict) -> list[tuple[str, str]]:
    o = data["official"]
    def values(q): return o[q]["key_values"]
    return [
        ("Q1 · 0.5 h", f"中心温度  {values('Q1')['Tcenter_C']:.4f} °C\n表面含水率  {values('Q1')['Csurface']:.4f}\n最大含水率  {values('Q1')['Cmax']:.4f}"),
        ("Q2 · 3 h", f"中心温度  {values('Q2')['Tcenter_C']:.4f} °C\n表面含水率  {values('Q2')['Csurface']:.4f}\n最大含水率  {values('Q2')['Cmax']:.4f}"),
        ("Q3", f"烘干时间  {o['Q3']['drying_time_h']:.4f} h\n最大含水率  {o['Q3']['endpoint_Cmax']:.2f}"),
        ("Q4", f"烘干时间  {o['Q4']['drying_time_h']:.4f} h\n终点半径  {o['Q4']['R_at_endpoint_m']*100:.4f} cm\n最大含水率  {o['Q4']['endpoint_Cmax']:.2f}"),
    ]
