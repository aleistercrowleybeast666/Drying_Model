"""Small, independently testable state machine for multi-command GUI jobs."""
from dataclasses import dataclass, field


@dataclass
class TaskProgress:
    pending: list[list[str]] = field(default_factory=list)
    kind: str = "read_only"
    last_commands: list[list[str]] = field(default_factory=list)
    last_kind: str = "read_only"

    def begin(self, commands, kind):
        commands = [list(command) for command in commands]
        if not commands:
            raise ValueError("没有可运行的任务")
        self.pending = commands
        self.kind = kind
        self.last_commands = [list(command) for command in commands]
        self.last_kind = kind

    def take_next(self):
        return self.pending.pop(0) if self.pending else None

    def cancel_remaining(self):
        self.pending.clear()

    def resume(self):
        if not self.last_commands:
            raise ValueError("没有可恢复的上次任务")
        self.pending = [list(command) for command in self.last_commands]
        self.kind = self.last_kind

