import json
import sys
import threading
import time

import pytest

from drying.gui.controller import (CommandBuilder, P4_FIXED_NOTICE, SUPPLEMENTAL_NOTICE,
                                   TWO_D_NOTICE, classify_returncode, result_catalog)
from drying.gui.facts import load_facts, official_cards
from drying.gui.task_runner import TaskRunner


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
    assert "未认证" in TWO_D_NOTICE and "fully converged" not in TWO_D_NOTICE
    assert "72 h 未达标" in P4_FIXED_NOTICE and "未独立完成完整空间加密" in P4_FIXED_NOTICE
    assert "补充敏感性研究" in SUPPLEMENTAL_NOTICE and "不替代正式 M00" in SUPPLEMENTAL_NOTICE


def test_one_task_lock(monkeypatch,tmp_path):
    # The current runner is QProcess based; no obsolete Python worker thread.
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    runner=TaskRunner(tmp_path)
    runner.start([sys.executable,'-c','import time; time.sleep(0.3)'],'official')
    with pytest.raises(RuntimeError,match="已有计算任务正在运行"):runner.start(["two"],"thermal")
    assert runner.process.waitForFinished(5000)


def test_safe_stop_marker(tmp_path):
    builder=CommandBuilder(tmp_path,"python");runner=TaskRunner(tmp_path)
    runner.request_stop(builder.stop_marker(False));assert (tmp_path/"work/studies/STOP").is_file()
    runner.request_stop(builder.stop_marker(True));assert (tmp_path/"work/studies/BASELINE_STOP").is_file()


def test_failed_cli_status():
    assert classify_returncode(1)=="FAIL" and classify_returncode(0)=="PASS"
