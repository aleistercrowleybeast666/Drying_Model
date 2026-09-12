"""Hidden configuration UI checks only; no compute/plot child is launched."""
import sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk
root=Path(__file__).resolve().parents[3];sys.path.insert(0,str(root))
import app
original=tk.Tk;errors=[]
def Create():
    window=original();window.withdraw()
    def Check():
        try:
            selectors=[child for frame in window.winfo_children() for child in frame.winfo_children() if isinstance(child,ttk.Combobox)]
            assert len(selectors)==4
            selectors[1].set('geometry');assert selectors[2].get()=='q4' and selectors[3].get()=='M00' and str(selectors[3]['state'])=='disabled'
            selectors[1].set('thermal');selectors[3].set('M11');assert str(selectors[3]['state'])=='readonly'
            selectors[0].set('baseline');assert selectors[2].get()=='all' and selectors[3].get()=='M00'
            assert all(str(widget['state'])=='disabled' for widget in selectors[1:])
        except Exception as exc:errors.append(repr(exc))
        finally:window.destroy()
    window.after(100,Check);return window
tk.Tk=Create
assert app.App_Main()==0
assert not errors,errors
print('HIDDEN_GUI_CONFIGURATION_PASS; no child process launched; no manual click acceptance claimed')
