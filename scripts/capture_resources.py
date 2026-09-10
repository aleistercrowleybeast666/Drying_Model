"""Capture OS-maintained peak working set of active project processes."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
import psutil

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'src'))
from drying.storage import Storage_WriteJson

path=root/'results/os_peak_memory.json'
previous=json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
for process in psutil.process_iter():
    try:
        if process.name()!='python.exe' or Path(process.cwd()).resolve()!=root:
            continue
        if not any('run.py' in arg for arg in process.cmdline()):
            continue
        memory=process.memory_info()
        previous.append(dict(utc=datetime.now(timezone.utc).isoformat(),pid=process.pid,
            rss_bytes=memory.rss,os_peak_working_set_bytes=getattr(memory,'peak_wset',memory.rss),
            private_bytes=getattr(memory,'private',None),cpu_user_s=process.cpu_times().user))
    except (psutil.NoSuchProcess,psutil.AccessDenied):
        pass
Storage_WriteJson(path,previous)
print(json.dumps(previous[-4:],indent=2))
