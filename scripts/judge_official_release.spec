"""A-only runtime. Independent Analysis/PYZ/COLLECT."""
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules,copy_metadata
root=Path(os.environ['DRYING_BUILD_ROOT'])
hidden=collect_submodules('numba',filter=lambda n:'.tests' not in n and not n.startswith('numba.cuda'))
metadata=[]
for package in ['numpy','numba','llvmlite','openpyxl','psutil']:metadata+=copy_metadata(package)
analysis=Analysis([str(root/'official_recompute.py')],pathex=[str(root)],
    hiddenimports=hidden+['numpy','llvmlite.binding','openpyxl','psutil','tomllib'],datas=metadata,
    excludes=['drying','PySide6','PyQt5','PyQt6','matplotlib','imageio','PIL','scipy','pypdf','iapws','pytest','tkinter','IPython','notebook'])
pyz=PYZ(analysis.pure)
exe=EXE(pyz,analysis.scripts,[],exclude_binaries=True,name='药材烘干模型_四表正式数据',
    console=True,upx=False,contents_directory='dependencies')
COLLECT(exe,analysis.binaries,analysis.datas,name='01_四表正式数据_终端版',strip=False,upx=False)
