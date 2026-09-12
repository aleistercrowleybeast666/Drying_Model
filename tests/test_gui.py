import json
import sys
import importlib.util
from pathlib import Path

import pytest

from drying.gui.controller import (CommandBuilder, P4_FIXED_NOTICE, SUPPLEMENTAL_NOTICE,
                                   TWO_D_NOTICE, classify_returncode, result_catalog)
from drying.gui.facts import load_facts, official_cards
from drying.gui.progress import ProgressState
from drying.gui.validation_status import TWO_D_DETAIL,TWO_D_MAIN,apply_checker_result,evidence_rows


def make_facts(root):
    path=root/"results";path.mkdir()
    data={"official":{}}
    for q in ("Q1","Q2","Q3","Q4"):
        data["official"][q]={"key_values":{"Tcenter_C":30,"Csurface":1,"Cmax":.15},"drying_time_h":1,"endpoint_Cmax":.15}
    data["official"]["Q4"]["R_at_endpoint_m"]=.012
    (path/"paper_facts.json").write_text(json.dumps(data),encoding="utf-8")
    return data


def test_facts_read_and_cards(tmp_path):
    make_facts(tmp_path);result=load_facts(tmp_path)
    assert result.ready and len(official_cards(result.data))==4


def test_facts_missing_is_explicit_and_does_not_compute(tmp_path):
    result=load_facts(tmp_path)
    assert not result.ready and "不会自动重算" in result.message


@pytest.mark.parametrize("case",["q1","q23","q4"])
def test_official_commands_are_selective_m00(tmp_path,case):
    command=CommandBuilder(tmp_path,"python").official(case)
    assert command[-2:]==["--case",case] and "compute.py" in command[1]
    assert "--mode" not in command


def test_default_official_command_remains_full_m00(tmp_path):
    command=CommandBuilder(tmp_path,"python").official("all")
    assert command==["python",str(tmp_path/"compute.py")]


def test_thermal_commands(tmp_path):
    commands=CommandBuilder(tmp_path,"python").thermal(["M10","M01","M11"],["q1","q23","q4"])
    assert len(commands)==9
    assert all("--group" in c and c[c.index("--group")+1]=="thermal" and "--resume" in c for c in commands)


def test_mass_balance_and_auxiliary_commands(tmp_path):
    builder=CommandBuilder(tmp_path,"python")
    assert builder.mass_balance()[-3:]==["--group","mass_balance","--resume"]
    assert builder.auxiliary_2d()[1].endswith("validate_auxiliary_2d.py")


def test_quick_validation_has_no_solver_entry(tmp_path):
    commands=CommandBuilder(tmp_path,"python").quick_validation()
    flattened=" ".join(" ".join(c) for c in commands)
    assert " compute.py" not in flattened and "--output-status-only" in flattened


def test_result_browser_is_read_only(tmp_path):
    (tmp_path/"results/q1").mkdir(parents=True);(tmp_path/"results/q1/a.png").touch()
    assert result_catalog(tmp_path,"Q1")==[tmp_path/"results/q1/a.png"]


def test_required_scoped_wording():
    combined=TWO_D_NOTICE+TWO_D_MAIN+TWO_D_DETAIL
    assert "严格二维未通过" not in combined and "二维全时域完全收敛" not in combined
    assert "72 h 未达标" in P4_FIXED_NOTICE and "未独立完成完整空间加密" in P4_FIXED_NOTICE
    assert "补充敏感性研究" in SUPPLEMENTAL_NOTICE and "不替代正式 M00" in SUPPLEMENTAL_NOTICE


def test_validation_initial_state_is_existing_evidence_not_current_run(tmp_path):
    (tmp_path/"results").mkdir();(tmp_path/"results/status.json").write_text('{"questions":{}}')
    rows=evidence_rows(tmp_path)
    assert all("本次快速检查通过" not in row.detail for row in rows)


def test_checker_failure_updates_rows_to_fail(tmp_path):
    (tmp_path/"results").mkdir();(tmp_path/"results/status.json").write_text('{"questions":{}}')
    rows=evidence_rows(tmp_path);apply_checker_result(rows,"mass",1,"boom")
    mass=next(row for row in rows if row.key=="mass")
    assert mass.status=="FAIL" and mass.detail=="boom"


def test_exact_progress_for_validation_and_thermal_jobs():
    progress=ProgressState();progress.begin("快速验证",4)
    for i in range(4):progress.complete_step(str(i))
    assert progress.percent==100 and progress.completed==progress.total
    progress.begin("热模型",9)
    for i in range(9):progress.complete_step(str(i))
    assert progress.percent==100


def test_official_progress_is_indeterminate():
    progress=ProgressState();progress.begin("正式计算",1,False)
    assert not progress.determinate and progress.percent==0


def test_safe_stop_marker(tmp_path):
    for official,name in [(False,"STOP"),(True,"BASELINE_STOP")]:
        marker=CommandBuilder(tmp_path,"python").stop_marker(official);marker.parent.mkdir(parents=True,exist_ok=True);marker.write_text("stop")
        assert marker.name==name and marker.is_file()


def test_result_layout_accepts_facts_and_rejects_unknown(tmp_path):
    spec=importlib.util.spec_from_file_location("check_results",Path(__file__).parents[1]/"scripts/check_results.py");module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    required={'tables','q1','q2','q3','q4','status.json','overview.md','animations','studies','paper_facts.json','paper_facts.md'}
    results=tmp_path/"results";results.mkdir()
    for name in required:
        path=results/name
        if '.' in name:path.write_text('{}' if name.endswith('.json') else '')
        else:path.mkdir()
    facts={"official":{"Q3":{"drying_time_s":3},"Q4":{"drying_time_s":4}}};(results/"paper_facts.json").write_text(json.dumps(facts))
    status={"questions":{"q3":{"drying_time":3},"q4":{"drying_time":4}}};(results/"status.json").write_text(json.dumps(status))
    for q,t in [("q3",3),("q4",4)]:(results/q/f"{q}_summary.json").write_text(json.dumps({"drying_time":t}))
    module.Check_ResultLayout(tmp_path)
    (results/"unknown.tmp").touch()
    with pytest.raises(RuntimeError,match="(?s)RESULT_LAYOUT_MISMATCH.*unexpected",):module.Check_ResultLayout(tmp_path)


def test_failed_cli_status():
    assert classify_returncode(1)=="FAIL" and classify_returncode(0)=="PASS"


def test_pyside_window_has_seven_switchable_pages(monkeypatch):
    pytest.importorskip("PySide6");monkeypatch.setenv("QT_QPA_PLATFORM","offscreen")
    from PySide6.QtWidgets import QApplication
    from drying.gui.main_window import MainWindow,PAGE_NAMES
    app=QApplication.instance() or QApplication([]);window=MainWindow(Path(__file__).parents[1])
    assert window.stack.count()==len(PAGE_NAMES)==7
    for index in range(7):window.nav.setCurrentRow(index);assert window.stack.currentIndex()==index
    window.close()
