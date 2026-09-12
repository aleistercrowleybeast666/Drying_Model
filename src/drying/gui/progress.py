"""Truthful job-level progress and machine-readable official phase events."""
from dataclasses import dataclass
import json

PREFIX="GUI_PROGRESS "


@dataclass
class ProgressState:
    task: str="无"
    phase: str="空闲"
    completed: int=0
    total: int=0
    determinate: bool=True

    @property
    def percent(self):
        return round(100*self.completed/self.total) if self.determinate and self.total else 0

    def begin(self,task,total,determinate=True):
        self.task=task;self.phase="准备";self.completed=0;self.total=total;self.determinate=determinate

    def complete_step(self,phase):
        self.phase=phase;self.completed=min(self.total,self.completed+1)


def parse_progress(line):
    if not line.startswith(PREFIX):return None
    try:return json.loads(line[len(PREFIX):])
    except (ValueError,TypeError):return None
