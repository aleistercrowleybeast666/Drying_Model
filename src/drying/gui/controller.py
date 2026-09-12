"""GUI command policy: views never compose CLI arguments themselves."""
from pathlib import Path
import sys

HEAVY_KINDS = frozenset({"official", "thermal", "mass_balance", "geometry"})
SUPPLEMENTAL_NOTICE = "M10/M01/M11 为补充敏感性研究，不替代正式 M00。"
TWO_D_NOTICE = "二维辅助验收：PASS；严格二维网格独立性：PARTIAL_2D / 未认证（NOT CERTIFIED）。"
P4_FIXED_NOTICE = "P4 + 固定半径：72 h 未达标；该分支未独立完成完整空间加密，交互项仅用于结构诊断。"


class CommandBuilder:
    def __init__(self, root: Path, python: str | None = None):
        self.root = Path(root)
        self.python = python or sys.executable

    def _script(self, name, *args):
        return [self.python, str(self.root / name), *args]

    def official(self, case: str):
        if case not in {"q1", "q23", "q4", "all"}: raise ValueError("未知正式计算选项")
        command = self._script("compute.py")
        return command if case == "all" else command + ["--case", case]

    def thermal(self, modes, cases):
        valid_modes={"M10", "M01", "M11"}; valid_cases={"q1", "q23", "q4"}
        if not modes or not cases or not set(modes)<=valid_modes or not set(cases)<=valid_cases: raise ValueError("请选择有效的补充模型与轨迹")
        return [self._script("compute_studies.py", "--group", "thermal", "--resume", "--mode", mode, "--case", case)
                for mode in modes for case in cases]

    def mass_balance(self): return self._script("compute_studies.py", "--group", "mass_balance", "--resume")
    def auxiliary_2d(self): return self._script("validate_auxiliary_2d.py")
    def geometry(self): return self._script("compute_studies.py", "--group", "geometry_cross", "--resume", "--case", "q4")
    def quick_validation(self):
        # Every command is an existing read-only checker/status refresh; compute.py is deliberately absent.
        return [self._script("scripts/check_results.py"), self._script("scripts/check_mass_balance.py"),
                self._script("validate_auxiliary_2d.py"), self._script("compute_studies.py", "--output-status-only")]

    def stop_marker(self, official=False):
        return self.root / "work/studies" / ("BASELINE_STOP" if official else "STOP")


def classify_returncode(code: int) -> str:
    return "PASS" if code == 0 else "FAIL"


def result_catalog(root: Path, category: str) -> list[Path]:
    root=Path(root); mappings={
        "正式结果": root/"results", "Q1": root/"results/q1", "Q2": root/"results/q2", "Q3": root/"results/q3", "Q4": root/"results/q4",
        "动画": root/"results/animations", "创新图": root/"results/studies/figures", "热模型": root/"results/studies/thermal",
        "表格": root/"results/tables", "验证报告": root/"results/studies",
    }
    folder=mappings[category]
    return sorted((p for p in folder.rglob("*") if p.is_file()), key=lambda p: p.as_posix()) if folder.exists() else []
