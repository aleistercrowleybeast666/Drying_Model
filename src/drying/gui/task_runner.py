"""Non-blocking subprocess queue with one-heavy-task locking and cooperative stop."""
from dataclasses import dataclass, field
from datetime import datetime
import os
from pathlib import Path
import queue
import subprocess
import threading


@dataclass
class TaskRecord:
    command: list[str]
    kind: str
    started_at: str = field(default_factory=lambda: datetime.now().astimezone().isoformat(timespec="seconds"))
    status: str = "RUNNING"
    returncode: int | None = None


class TaskRunner:
    def __init__(self, root: Path):
        self.root=Path(root); self.events=queue.Queue(); self.active: TaskRecord | None=None

    @property
    def busy(self): return self.active is not None and self.active.status == "RUNNING"

    def start(self, command, kind="read_only"):
        if self.busy: raise RuntimeError("已有计算任务正在运行")
        self.active=TaskRecord(list(command), kind)
        threading.Thread(target=self._work, args=(self.active,), daemon=True).start()
        return self.active

    def _work(self, record):
        env=dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        try:
            process=subprocess.Popen(record.command,cwd=self.root,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding="utf-8",errors="replace",env=env)
            for line in process.stdout or (): self.events.put(("line", line.rstrip()))
            record.returncode=process.wait();record.status="PASS" if record.returncode==0 else "FAIL"
        except Exception as exc:
            record.returncode=-1;record.status="FAIL";self.events.put(("line", f"任务启动失败：{exc}"))
        self.events.put(("done", record))

    def request_stop(self, marker: Path):
        marker=Path(marker);marker.parent.mkdir(parents=True,exist_ok=True)
        marker.write_text("GUI requested cooperative checkpoint stop\n",encoding="utf-8")
        self.events.put(("line", "将在下一个安全保存点停止，并保留可恢复状态。"))
