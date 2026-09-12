# PyInstaller 6.22.2: two onedir applications, one shared COLLECT/support folder.
# Numerical modules are shipped as physical reviewable source in code/src;
# this preserves Numba's file locators and the project's source fingerprints.
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, copy_metadata

root = Path(os.environ['DRYING_BUILD_ROOT'])
cpu_modules = collect_submodules('numba', filter=lambda n: '.tests' not in n and not n.startswith('numba.cuda'))
scientific = collect_submodules('scipy', filter=lambda n: '.tests' not in n and 'conftest' not in n)
hidden = cpu_modules + scientific + collect_submodules('iapws') + [
    'numpy','llvmlite.binding','matplotlib.backends.backend_agg','openpyxl','PIL.Image',
    'imageio','psutil','pypdf','PySide6.QtWidgets','PySide6.QtCore','PySide6.QtGui']
metadata = []
for package in ['imageio','numpy','scipy','numba','llvmlite','matplotlib','openpyxl','pillow','psutil','iapws','pypdf','PySide6']:
    metadata += copy_metadata(package)
cli = Analysis([str(root/'offline_recompute.py')], pathex=[str(root)],
    hiddenimports=hidden+['tomllib','runpy','logging.handlers'], datas=collect_data_files('iapws')+metadata,
    hookspath=[str(root/'scripts/pyinstaller_hooks')],
    excludes=['drying','pytest','tkinter','IPython','notebook'],
    hooksconfig={'matplotlib':{'backends':['Agg']}})
gui = Analysis([str(root/'judge_gui.py')], pathex=[str(root)],
    hiddenimports=['PySide6.QtCore','PySide6.QtGui','PySide6.QtWidgets'],
    excludes=['drying','pytest','tkinter','IPython','notebook'])
# Both entries execute external, reviewable application modules. Share the full
# pure-module closure as well: GUI's minimal Analysis alone misses json/dataclasses
# imported by those external modules (the numerical package is intentionally excluded).
common_pyz = PYZ(cli.pure + gui.pure)
cli_pyz = common_pyz
gui_pyz = common_pyz
cli_exe = EXE(cli_pyz,cli.scripts,[],exclude_binaries=True,
    name='药材烘干模型_完整离线复算',console=True,upx=False,contents_directory='dependencies')
gui_exe = EXE(gui_pyz,gui.scripts,[],exclude_binaries=True,
    name='药材烘干模型_GUI',console=False,upx=False,contents_directory='dependencies')
COLLECT(gui_exe,cli_exe,gui.binaries,gui.datas,cli.binaries,cli.datas,
    name='A题_药材烘干模型',strip=False,upx=False)
