"""Source and windowed EXE entry; importing this module does not import Qt."""
import os
import sys
import traceback
from pathlib import Path


def main():
    root = (Path(sys.executable).parent if getattr(sys,'frozen',False) else
        Path(os.environ.get('DRYING_MODEL_ROOT') or Path(__file__).parent)).resolve()
    code = root/'code' if (root/'code/src').is_dir() else root
    if (root/'dependencies/application/code/src').is_dir():code=root/'dependencies/application/code'
    os.environ['DRYING_MODEL_ROOT'] = str(root)
    os.environ.setdefault('NUMBA_CACHE_DIR',str(root/'work/recompute/numba_cache'))
    sys.path.insert(0, str(code/'src'))
    try:
        from PySide6.QtWidgets import QApplication
        from drying.gui.judge_window import JudgeWindow
        app = QApplication.instance() or QApplication(sys.argv)
        window = JudgeWindow(root)
        window.show()
        if os.environ.get('DRYING_GUI_SMOKE_FILE'):
            from PySide6.QtCore import QTimer
            def Smoke_Check():
                window.Smoke_Check(os.environ['DRYING_GUI_SMOKE_FILE'])
                window.close()
            QTimer.singleShot(1500, Smoke_Check)
        return app.exec()
    except Exception as error:
        if isinstance(error, ImportError) and 'PySide6' in str(error):
            message = '未安装 PySide6。\n请先运行“安装Python依赖.bat”\n或执行：\npython -m pip install -r requirements.txt'
        else:
            message = '图形界面启动失败：'+str(error)+'\n详情见 logs/gui_startup_error.txt'
        folder = root/'logs'; folder.mkdir(parents=True, exist_ok=True)
        (folder/'gui_startup_error.txt').write_text(message+'\n'+traceback.format_exc(), encoding='utf-8')
        if sys.stderr is not None: print(message, file=sys.stderr)
        if os.name == 'nt' and not os.environ.get('DRYING_GUI_SMOKE_FILE'):
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, '药材烘干模型', 0x10)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
