"""Hidden GUI -> real read-only CLI -> GUI log integration; never starts a solve."""
import hashlib,json,sys,time
from pathlib import Path
import tkinter as tk
from tkinter import ttk
root=Path(__file__).resolve().parents[3];sys.path.insert(0,str(root))
import app
original_tk=tk.Tk;original_popen=app.subprocess.Popen;children=[];errors=[];report={}
stop=root/'work/studies/STOP';before_stop=stop.read_bytes() if stop.exists() else None
def LaunchReadonly(command,**kwargs):
    assert '--dry-run' in command and Path(command[1]).name=='compute_studies.py'
    child=original_popen(command,**kwargs);children.append(child);report['command']=command;return child
app.subprocess.Popen=LaunchReadonly
def Create():
    window=original_tk();window.withdraw();start=time.monotonic()
    def Check():
        try:
            selectors=[w for frame in window.winfo_children() for w in frame.winfo_children() if isinstance(w,ttk.Combobox)]
            if not children:
                selectors[1].set('thermal');selectors[2].set('q4');selectors[3].set('M11')
                buttons=[w for frame in window.winfo_children() for w in frame.winfo_children() if isinstance(w,ttk.Button)]
                next(w for w in buttons if w.cget('text')=='查看计划').invoke()
            elif children[0].poll() is not None and str(selectors[0]['state'])=='readonly':
                log=next(w for w in window.winfo_children() if isinstance(w,tk.Text) and str(w['state'])=='normal').get('1.0','end')
                assert children[0].returncode==0 and '"read_only": true' in log and 'q4_M11' in log
                assert '--group thermal --case q4 --mode M11' in log.replace('--dry-run ','')
                assert (stop.read_bytes() if stop.exists() else None)==before_stop
                report.update(status='PASS',hidden_window=True,actual_readonly_child=True,exit_code=0,manual_interaction=False,
                    app_sha256=hashlib.sha256((root/'app.py').read_bytes()).hexdigest())
                window.destroy();return
            if time.monotonic()-start>30:raise TimeoutError('read-only GUI child did not return in 30 seconds')
            window.after(100,Check)
        except Exception as exc:errors.append(repr(exc));window.destroy()
    window.after(100,Check);return window
tk.Tk=Create
app.App_Main()
if errors:report.update(status='FAIL',errors=errors)
(root/'work/studies/diagnostics/gui_cli_check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
assert not errors,errors
print('HIDDEN_GUI_READONLY_CHILD_PASS; no PDE launch; no manual click acceptance claimed')
