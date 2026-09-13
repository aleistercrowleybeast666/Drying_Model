"""Independent full GUI runtime with its own private console worker."""
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules,collect_data_files,copy_metadata
root=Path(os.environ['DRYING_BUILD_ROOT'])
hidden=collect_submodules('numba',filter=lambda n:'.tests' not in n and not n.startswith('numba.cuda'))
hidden+=collect_submodules('scipy',filter=lambda n:'.tests' not in n and 'conftest' not in n)
hidden+=collect_submodules('iapws')+['numpy','llvmlite.binding','matplotlib.backends.backend_agg','openpyxl','PIL.Image',
    'imageio','psutil','pypdf','PySide6.QtWidgets','PySide6.QtCore','PySide6.QtGui','tomllib','runpy','logging.handlers','contextvars','unittest.mock']
metadata=[]
for package in ['imageio','numpy','scipy','numba','llvmlite','matplotlib','openpyxl','pillow','psutil','iapws','pypdf','PySide6']:metadata+=copy_metadata(package)
worker=Analysis([str(root/'offline_recompute.py')],pathex=[str(root)],hiddenimports=hidden,
    datas=collect_data_files('iapws',include_py_files=True)+metadata,hookspath=[str(root/'scripts/pyinstaller_hooks')],
    excludes=['drying','pytest','tkinter','IPython','notebook'],hooksconfig={'matplotlib':{'backends':['Agg']}})
gui=Analysis([str(root/'judge_gui.py')],pathex=[str(root)],
    hiddenimports=['PySide6.QtCore','PySide6.QtGui','PySide6.QtWidgets'],excludes=['drying','pytest','tkinter','IPython','notebook'])
pyz=PYZ(worker.pure+gui.pure)
gui_exe=EXE(pyz,gui.scripts,[],exclude_binaries=True,name='药材烘干模型_GUI',console=False,upx=False,contents_directory='dependencies')
worker_exe=EXE(pyz,worker.scripts,[],exclude_binaries=True,name='药材烘干模型_计算后台',console=True,upx=False,contents_directory='.')
COLLECT(gui_exe,worker_exe,gui.binaries,gui.datas,worker.binaries,worker.datas,name='02_完整功能_GUI版',strip=False,upx=False)
