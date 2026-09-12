"""Qt QProcess orchestration: streaming output, serial queue and one-task lock."""
from pathlib import Path


class TaskRunner:
    def __init__(self,root,parent=None):
        from PySide6.QtCore import QProcess
        self.root=Path(root);self.process=QProcess(parent);self.queue=[];self.busy=False;self.current=None
        self.on_output=lambda stream,text:None;self.on_step=lambda command,code,remaining:None;self.on_done=lambda success:None
        self.process.readyReadStandardOutput.connect(lambda:self._read("stdout"))
        self.process.readyReadStandardError.connect(lambda:self._read("stderr"))
        self.process.finished.connect(self._finished);self.process.errorOccurred.connect(lambda error:self.on_output("stderr",self.process.errorString()))

    def start(self,commands):
        if self.busy:raise RuntimeError("已有计算任务正在运行")
        self.queue=[list(c) for c in commands];self.busy=True;self._next()

    def _next(self):
        if not self.queue:self.busy=False;self.on_done(True);return
        self.current=self.queue.pop(0);self.process.setWorkingDirectory(str(self.root));self.process.start(self.current[0],self.current[1:])

    def _read(self,stream):
        data=self.process.readAllStandardOutput() if stream=="stdout" else self.process.readAllStandardError()
        self.on_output(stream,bytes(data).decode("utf-8","replace"))

    def _finished(self,code,*_):
        self.on_step(self.current,code,len(self.queue))
        if code:self.queue.clear();self.busy=False;self.on_done(False)
        else:self._next()

    @staticmethod
    def request_stop(marker):
        marker=Path(marker);marker.parent.mkdir(parents=True,exist_ok=True);marker.write_text("GUI requested cooperative checkpoint stop\n",encoding="utf-8")
