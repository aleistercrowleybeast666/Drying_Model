"""Qt subprocess runner used by the desktop application.

QProcess keeps all notifications on Qt's GUI thread.  This is important on
Windows, where updating widgets from the worker thread used by the old Tk
frontend was inherently racy.
"""
from dataclasses import dataclass, field
from datetime import datetime
import os
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal


@dataclass
class TaskRecord:
    command: list[str]
    kind: str
    started_at: str = field(default_factory=lambda: datetime.now().astimezone().isoformat(timespec="seconds"))
    status: str = "RUNNING"
    returncode: int | None = None


class TaskRunner(QObject):
    """Run at most one command and expose merged output through Qt signals."""

    line_ready = Signal(str)
    finished = Signal(object)

    def __init__(self, root: Path, parent=None):
        super().__init__(parent)
        self.root = Path(root)
        self.active: TaskRecord | None = None
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read_output)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)

    @property
    def busy(self):
        return self.active is not None and self.active.status == "RUNNING"

    def start(self, command, kind="read_only"):
        if self.busy:
            raise RuntimeError("已有计算任务正在运行")
        command = [str(part) for part in command]
        if not command:
            raise ValueError("任务命令不能为空")
        self.active = TaskRecord(command, kind)
        if kind in {"official", "thermal", "mass_balance", "geometry"}:
            marker = self.root / "work/studies" / ("BASELINE_STOP" if kind == "official" else "STOP")
            marker.unlink(missing_ok=True)
        self.process.setWorkingDirectory(str(self.root))
        env = self.process.processEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        env.insert("PYTHONIOENCODING", "utf-8")
        self.process.setProcessEnvironment(env)
        self.process.start(command[0], command[1:])
        return self.active

    def request_stop(self, marker: Path):
        marker = Path(marker)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("GUI requested cooperative checkpoint stop\n", encoding="utf-8")
        self.line_ready.emit("将在下一个安全保存点停止，并保留可恢复状态。")

    def _read_output(self):
        text = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        for line in text.splitlines():
            self.line_ready.emit(line)

    def _finished(self, code, _exit_status):
        self._read_output()
        if self.active is None:
            return
        self.active.returncode = int(code)
        self.active.status = "PASS" if code == 0 else "FAIL"
        record = self.active
        self.finished.emit(record)

    def _error(self, error):
        if self.process.state() == QProcess.ProcessState.NotRunning and self.active and self.active.returncode is None:
            self.line_ready.emit(f"任务启动失败：{self.process.errorString()}")
