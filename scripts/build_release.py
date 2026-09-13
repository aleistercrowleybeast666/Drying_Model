"""Two independent V5 packages; no automatic execution or numerical tests."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
NAME='A题_药材烘干模型'
OFFICIAL='01_四表正式数据_终端版'
GUI='02_完整功能_GUI版'
OFFICIAL_MODULES=['__init__','official_cli','official_progress','official_support','materials','boundaries','operators','rk4','sampling',
    'geometry','events','inputs','cases','stages','mesh','frozen_mesh','table_solver','table_reference','export','storage','diagnostics','judge_schedule']
OFFICIAL_CONFIGS=['default.toml','stage_schedule.json','stage_solver_reference.json','frozen_mesh','table_reference']
CORE=['materials','boundaries','operators','rk4','sampling','inputs','events','geometry','cases','stages','table_solver']
TOP_TEXT='''本软件分为两个完全独立版本：

1. 01_四表正式数据_终端版
   仅复算题目要求的四份正式 Excel，依赖最少。
   双击“药材烘干模型_四表正式数据.exe”。
   本次测试机完整四表约 2.8 min，不同电脑和后台负载下耗时会变化，仅供参考。

2. 02_完整功能_GUI版
   用于四表、创新实验数据、绘图和数值验证。
   双击“药材烘干模型_GUI.exe”。验证计算量最大，非必要不建议运行。

两版均保留同名 .py 入口、各自的 requirements 和安装依赖脚本。
依赖与 work/results/logs 完全独立。可单独复制任一大目录运行，互不读取或覆盖结果。
初次运行自动创建结果、缓存和日志目录；请完整保留所选版本的 dependencies 文件夹。
'''


def Build_Hash(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def Build_WriteJson(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def Build_Copy(source,target):
    source=Path(source);target=Path(target)
    if source.is_dir():
        shutil.copytree(source,target,dirs_exist_ok=True,copy_function=Build_Copy,
            ignore=shutil.ignore_patterns('__pycache__','*.pyc','.pytest_cache','~$*'))
    else:
        target.parent.mkdir(parents=True,exist_ok=True)
        temp=target.with_name(target.name+'.buildtmp');shutil.copy2(source,temp);os.replace(temp,target)
    return str(target)


def Build_WriteEntries(target,official):
    name='药材烘干模型_四表正式数据' if official else '药材烘干模型_GUI'
    module='official_recompute' if official else 'judge_gui'
    env='DRYING_OFFICIAL_ROOT' if official else 'DRYING_MODEL_ROOT'
    text=f'''"""Independent package Python entry."""
import os
from pathlib import Path
import runpy
import sys
if __name__ == '__main__':
    root=Path(__file__).resolve().parent
    os.environ['{env}']=str(root)
    code=root/'dependencies/application/code'
    sys.path.insert(0,str(code))
    runpy.run_path(str(code/'{module}.py'),run_name='__main__')
'''
    (target/(name+'.py')).write_text(text,encoding='utf-8')
    bat='''@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    py -3 -m pip install -r "%~dp0requirements.txt"
) else (
    python -m pip install -r "%~dp0requirements.txt"
)
pause
'''
    (target/'安装Python依赖.bat').write_text(bat,encoding='utf-8')


def Build_StageOfficial(target):
    target.mkdir(parents=True,exist_ok=True);code=target/'dependencies/application/code';data=target/'dependencies/application/data'
    for name in OFFICIAL_MODULES:Build_Copy(ROOT/f'src/drying/{name}.py',code/f'src/drying/{name}.py')
    for name in OFFICIAL_CONFIGS:Build_Copy(ROOT/'configs'/name,code/'configs'/name)
    Build_Copy(ROOT/'official_recompute.py',code/'official_recompute.py')
    Build_Copy(ROOT/'data/inputs.npz',data/'inputs.npz')
    manifest=json.loads((ROOT/'data/input_manifest.json').read_text(encoding='utf-8'));manifest['source']='data/raw'
    Build_WriteJson(data/'input_manifest.json',manifest)
    for row in manifest['templates'].values():Build_Copy(ROOT/row['path'],data/Path(row['path']).relative_to('data'))
    (target/'requirements.txt').write_text('numpy>=2.0\nnumba>=0.61\nllvmlite>=0.44\nopenpyxl>=3.1\npsutil>=6\n',encoding='utf-8')
    text='''本目录只用于复算题目要求的四份正式 Excel。
不会运行创新实验、绘图或完整数值验证。

双击：药材烘干模型_四表正式数据.exe
Python：先运行 安装Python依赖.bat，再运行同名 .py 文件。

默认执行问题1、问题2/3共享轨迹、问题4；输出 results/tables/result1.xlsx～result4.xlsx。
仅运行部分问题：--official q1 或 --official q23 q4。
可选 --workers auto/1～6；--force-data 强制重算所选 case。
系统保留内存按总内存的 12% 动态计算，下限 384 MiB、上限 2048 MiB；没有固定 2 GiB 启动门槛。
低内存自动减少并发；单任务放不下会报告 MEMORY_REQUIREMENT_UNSATISFIED 及预计内存、available、reserve，不会无限等待。
可自行检查：--dry-run、--verify、--runtime-check。

本版仅包含 NumPy、Numba、llvmlite、OpenPyXL、psutil 及必要标准库。
使用已核验的附件数值输入和冻结网格；不需要 PDF 解析器或绘图/GUI 库。
科学模型、正式步长与 Excel 格式沿用原实现。
work/、results/、logs/ 均只在本目录生成；不读取 GUI 版缓存。
再次运行会核对数据身份和文件哈希，复用本版自己的有效缓存。
Ctrl+C 停止本次任务；未完成轨迹下次继续校验。

当前版本已完成四表终端版实际运行检查（用户实测）。
在本次测试电脑上，完整四表运行约 2.8 min；不同 CPU、内存和后台负载下耗时会变化，该数值仅供参考。
运行中显示真实结构进度、已用时间和预计剩余时间。首次运行先校准，获得真实进度后估计剩余时间。
四表数值运行已实测；新增进度显示为只读显示层，本轮未重新完整复算，也不声称新的 ETA 已完整实测。
'''
    for name in ['README.md','说明.txt']:(target/name).write_text(text,encoding='utf-8')
    Build_WriteEntries(target,True)


def Build_StageGui(target):
    target.mkdir(parents=True,exist_ok=True);code=target/'dependencies/application/code'
    for name in ['src','configs']:Build_Copy(ROOT/name,code/name)
    for name in ['judge_gui.py','offline_recompute.py']:Build_Copy(ROOT/name,code/name)
    Build_Copy(ROOT/'data',target/'dependencies/application/data')
    Build_Copy(ROOT/'requirements.txt',target/'requirements.txt')
    text='''本目录用于四表、创新实验数据、绘图和验证。
D · 验证计算量最大，非必要建议不运行。

双击“药材烘干模型_GUI.exe”；Python 用户先运行“安装Python依赖.bat”，再运行同名 .py。
A 为四表正式数据；B 为逐项创新实验数据；C 为逐图绘制；D 为独立数值验证。
每个模式支持全选/全不选。D 默认折叠，强制重算选项独立。

点击“刷新缓存”重新核验本目录的数据清单和实际文件。
C/D 按自己的前置数据独立启用；缺数据项禁用，悬停可看缺项。
部分问题已完成即可选择对应绘图和验证，不必等待全部问题。
建议先运行 A/B，完成后刷新，再选择 C/D；全选跳过禁用项目。

本版拥有独立 dependencies、work、results、logs；不读取终端版目录。
dependencies 内的计算后台由 GUI 自动调用，请勿单独双击。
首次运行自动创建缓存、结果和日志目录，不携带历史跨任务缓存。
两套 A 使用相同的数值核心源码。正式结果来源、Excel 格式和数值阈值保持。
旧 fixed-grid 为 legacy / diagnostic only；未运行的验证不会声称 PASS。
立即停止会结束本 GUI 启动的计算进程树；关闭窗口时一并停止。

本轮按要求减少验证，发布后未执行复算或数值验证。
'''
    text=(ROOT/'configs/judge_readme_v5.md').read_text(encoding='utf-8')
    for name in ['README.md','说明.txt']:(target/name).write_text(text,encoding='utf-8')
    Build_WriteEntries(target,False)
    worker=target/'药材烘干模型_计算后台.exe'
    if worker.exists():worker.replace(target/'dependencies/药材烘干模型_计算后台.exe')


def Build_Manifest(target,kind):
    files={p.relative_to(target).as_posix():Build_Hash(p) for p in sorted(target.rglob('*')) if p.is_file()
        and p.relative_to(target).parts[0] not in ['work','results','logs'] and p.name!='package_manifest.json' and '__pycache__' not in p.parts}
    value=dict(package=kind,build_time=datetime.now().astimezone().isoformat(),
        git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),files=files,
        official_core_sha256={name:files['dependencies/application/code/src/drying/'+name+'.py'] for name in CORE},
        exe_sha256={k:h for k,h in files.items() if k.endswith('.exe')},
        runtime_validation='NOT_RUN_AT_USER_REQUEST',physically_independent=True)
    Build_WriteJson(target/'package_manifest.json',value)
    return value


def Build_PyInstaller(target,kind):
    folder=ROOT/'work/release_v5/build'/kind;folder.mkdir(parents=True,exist_ok=True)
    staging=folder/('stage_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'));staging.mkdir()
    windows=Path(os.environ['SystemRoot'])
    env=dict(os.environ,DRYING_BUILD_ROOT=str(ROOT),PYINSTALLER_CONFIG_DIR=str(folder/'pyinstaller_cache'),
        PATH=os.pathsep.join(map(str,[Path(sys.executable).parent,Path(sys.base_prefix),Path(sys.base_prefix)/'DLLs',windows/'System32',windows])))
    spec=ROOT/'scripts'/('judge_official_release.spec' if kind=='official' else 'judge_gui_release.spec');log=folder/'build.log'
    with log.open('w',encoding='utf-8') as stream:
        completed=subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--distpath',str(staging),
            '--workpath',str(folder/'pyinstaller'),str(spec)],cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT)
    if completed.returncode:raise RuntimeError('BUILD_FAILED: '+str(log))
    Build_Copy(staging/(OFFICIAL if kind=='official' else GUI),target)


def Build_OfficialPackage(target,update=False,stage_only=False):
    if not update and not stage_only:Build_PyInstaller(target,'official')
    Build_StageOfficial(target)
    forbidden=['pyside','pyqt','matplotlib','imageio','pypdf','iapws','thermal.py','mass_balance.py','judge_gui.py','judge_window.py','judge_twod.py']
    unexpected=[str(p.relative_to(target)) for p in target.rglob('*') if any(token in p.name.lower() for token in forbidden)]
    if unexpected:raise RuntimeError('TERMINAL_DEPENDENCY_NOT_ALLOWED: '+', '.join(unexpected))
    return Build_Manifest(target,'official_only')


def Build_GuiPackage(target,update=False,stage_only=False):
    if not update and not stage_only:Build_PyInstaller(target,'gui')
    Build_StageGui(target)
    return Build_Manifest(target,'full_gui')


def Build_TopLevel(target):
    target.mkdir(parents=True,exist_ok=True)
    for name in ['请评委先看.md','请评委先看.txt']:(target/name).write_text(TOP_TEXT,encoding='utf-8')
    children={name:Build_Hash(target/name/'package_manifest.json') if (target/name/'package_manifest.json').exists() else None for name in [OFFICIAL,GUI]}
    Build_WriteJson(target/'release_manifest.json',dict(build_time=datetime.now().astimezone().isoformat(),
        git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),packages=children,
        instructions={name:Build_Hash(target/name) for name in ['请评委先看.md','请评委先看.txt']},runtime_validation='NOT_RUN_AT_USER_REQUEST'))


def Build_Run():
    parser=argparse.ArgumentParser();parser.add_argument('--dist-dir',type=Path,default=ROOT/'release_v5')
    choices=parser.add_mutually_exclusive_group();choices.add_argument('--official-only',action='store_true');choices.add_argument('--gui-only',action='store_true')
    parser.add_argument('--update-code',action='store_true');parser.add_argument('--stage-only',action='store_true')
    parser.add_argument('--keep-top-level',action='store_true',help='GUI-only maintenance after terminal handoff')
    args=parser.parse_args();target=(args.dist_dir/NAME).resolve()
    if not target.is_relative_to((ROOT/'release_v5').resolve()):raise RuntimeError('OLD_RELEASE_PROTECTED: only release_v5 may be written')
    if args.update_code and not (args.official_only or args.gui_only):parser.error('--update-code requires exactly one package')
    if args.keep_top_level and not args.gui_only:parser.error('--keep-top-level requires --gui-only')
    if not args.gui_only:
        print('BUILD official package',flush=True);Build_OfficialPackage(target/OFFICIAL,args.update_code,args.stage_only)
        print('OFFICIAL_PACKAGE_BUILT',target/OFFICIAL,flush=True)
    if not args.official_only:
        print('BUILD GUI package',flush=True);Build_GuiPackage(target/GUI,args.update_code,args.stage_only)
        print('GUI_PACKAGE_BUILT',target/GUI,flush=True)
    if not args.keep_top_level:Build_TopLevel(target)
    print('PACKAGED; runtime/numerical validation NOT RUN at user request',flush=True)


if __name__=='__main__':Build_Run()
