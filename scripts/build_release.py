"""Build, seal and smoke-test a single shared onedir judge distribution."""
import argparse
from datetime import datetime
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
NAME = 'A题_药材烘干模型'
GUI = '药材烘干模型_GUI'
CLI = '药材烘干模型_原题表格复算'


def Build_Hash(path):
    with Path(path).open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()


def Build_WriteJson(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def Build_ArchiveTarget(target):
    """Preserve the used package outside release before replacing it."""
    target=Path(target).resolve()
    if not target.exists():return None
    if not target.is_relative_to((ROOT/'release_v3').resolve()):raise ValueError('OLD_RELEASE_PROTECTED: only release_v3 may be replaced')
    sys.path.insert(0,str(ROOT/'src'))
    from drying.runner_control import Runner_Stop,RunnerStopResult
    from drying.runner_control import Runner_GetProcess
    if Runner_GetProcess(target) is not None:raise RuntimeError('ACTIVE_RELEASE_PROTECTED: package retained')
    import psutil
    for process in psutil.process_iter(['exe']):
        if process.info['exe'] and Path(process.info['exe']).resolve()==target/(GUI+'.exe'):
            raise RuntimeError('ACTIVE_GUI_PROTECTED: package retained')
    archive=(ROOT/'work/release'/('previous_package_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))).resolve()
    if not archive.is_relative_to((ROOT/'work/release').resolve()):raise ValueError('Invalid archive directory')
    shutil.move(str(target),str(archive))
    print('PREVIOUS PACKAGE PRESERVED:',archive,flush=True)
    return archive


def Build_GetReadme(facts):
    timing_path = ROOT/'work/release_v3/progress_cold_benchmark.json'
    if not timing_path.exists():timing_path = ROOT/'work/release_v3/cold_benchmark.json'
    timing = json.loads(timing_path.read_text(encoding='utf-8')) if timing_path.exists() else {}
    benchmark = ('EXE 无缓存原题四表 %.2f min（%s slots，含进程启动/准备/JIT/Excel/readback）' % (timing['external_wall_s']/60,timing.get('workers','auto'))
        if timing.get('returncode') == 0 else 'V3 冷启动未实测；既有 V2 原题四表冷跑约 3.10 min。')
    warm_path=ROOT/'work/release_v3/progress_warm_benchmark.json'
    if warm_path.exists():
        warm=json.loads(warm_path.read_text(encoding='utf-8'))
        if warm.get('returncode')==0:benchmark+='；匹配缓存复用 %.2f s。' % warm['external_wall_s']
    return (ROOT/'configs/judge_readme.md').read_text(encoding='utf-8').format(
        q3=facts['official']['Q3']['drying_time_h'],q4=facts['official']['Q4']['drying_time_h'],benchmark=benchmark)


def Build_GetBat():
    return '''@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    py -3 -m pip install -r requirements.txt
    goto check
)
python -c "import sys" >nul 2>&1
if not errorlevel 1 (
    python -m pip install -r requirements.txt
    goto check
)
echo 未检测到 Python。
echo Windows 用户可直接使用两个 EXE，无需安装 Python。
goto end
:check
if errorlevel 1 (
    echo 依赖安装失败，请检查上方错误和网络连接。
    goto end
)
echo 依赖安装完成。
echo 现在可以运行：
echo python 药材烘干模型_GUI.py
echo 或
echo python 药材烘干模型_原题表格复算.py
:end
pause
'''


def Build_WriteEntries(target):
    for name,module in [(GUI,'judge_gui'),(CLI,'offline_recompute')]:
        text = f'''"""Judge entry; delegates to the same implementation as its EXE."""
import os
from pathlib import Path
import runpy
import sys
if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    os.environ['DRYING_MODEL_ROOT'] = str(root)
    code = root/'code' if (root/'code').is_dir() else root
    if (root/'dependencies/application/code').is_dir():code=root/'dependencies/application/code'
    sys.path.insert(0,str(code))
    runpy.run_path(str(code/'{module}.py'),run_name='__main__')
'''
        (target/(name+'.py')).write_text(text,encoding='utf-8')


def Build_CapturePublication():
    protected = {}
    for folder in ['results','data','configs']:
        for path in (ROOT/folder).rglob('*'):
            if path.is_file() and not path.name.startswith('~$'):
                protected[path.relative_to(ROOT).as_posix()] = Build_Hash(path)
    # Every numerical module remains byte-identical (infrastructure is separate).
    for name in ['materials','boundaries','operators','rk4','sampling','inputs','events','geometry','cases','stages']:
        path = ROOT/f'src/drying/{name}.py'; protected[path.relative_to(ROOT).as_posix()] = Build_Hash(path)
    return protected


def Build_StageCode(target):
    target.mkdir(parents=True,exist_ok=True)
    ignore = shutil.ignore_patterns('__pycache__','*.pyc','.pytest_cache','~$*')
    code = target/'dependencies/application/code'; code.mkdir(parents=True,exist_ok=True)
    for name in ['src','configs','scripts','tests']:
        shutil.copytree(ROOT/name,code/name,dirs_exist_ok=True,ignore=ignore)
    for path in ROOT.glob('*.py'): shutil.copy2(path,code/path.name)
    for name in ['README.md','requirements-build.txt','requirements.txt','pytest.ini','RELEASE_VALIDATION.md','RELEASE_V3_VALIDATION.md']:
        shutil.copy2(ROOT/name,code/name)
    evidence=code/'release_evidence';evidence.mkdir(exist_ok=True)
    shutil.copy2(ROOT/'work/validation/program_tests.json',evidence/'program_tests.json')
    (evidence/'README.txt').write_text('program_tests.json 是构建机的回归测试记录，不表示在评委电脑执行了测试，也不替代复算中的数值验收。\n',encoding='utf-8')


def Build_Stage(target):
    Build_StageCode(target)
    ignore = shutil.ignore_patterns('__pycache__','*.pyc','.pytest_cache','~$*')
    shutil.copytree(ROOT/'data',target/'dependencies/application/data',dirs_exist_ok=True,ignore=ignore)
    Build_WriteEntries(target)
    facts = json.loads((ROOT/'results/paper_facts.json').read_text(encoding='utf-8'))
    text = Build_GetReadme(facts)
    for name in ['README.md','请评委先看这份文件.txt']: (target/name).write_text(text,encoding='utf-8')
    shutil.copy2(ROOT/'requirements.txt',target/'requirements.txt')
    (target/'安装Python依赖.bat').write_text(Build_GetBat(),encoding='utf-8')


def Build_Manifest(target,publication):
    import PyInstaller
    commit = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    value = dict(build_time=datetime.now().astimezone().isoformat(),git_commit=commit,python=sys.version,
        distribution_kind='minimal',
        pyinstaller=PyInstaller.__version__,exe_sha256={p.name:Build_Hash(p) for p in target.glob('*.exe')},
        publication_sha256={p.relative_to(target).as_posix():Build_Hash(p) for p in (target/'dependencies/application').rglob('*')
                            if p.is_file() and '__pycache__' not in p.parts},
        paper_facts_sha256={p.name:Build_Hash(p) for p in (target/'results').glob('paper_facts.*')},
        official_excel_sha256={p.name:Build_Hash(p) for p in (target/'results/tables').glob('result*.xlsx')},
        files=[dict(path=p.relative_to(target).as_posix(),bytes=p.stat().st_size,sha256=Build_Hash(p))
            for p in sorted(target.rglob('*')) if p.is_file() and p.name!='release_manifest.json'
            and p.relative_to(target).parts[0] not in ['work','logs']
            and '__pycache__' not in p.parts])
    Build_WriteJson(target/'release_manifest.json',value)
    return value


def Build_Run():
    parser = argparse.ArgumentParser(); parser.add_argument('--stage-only',action='store_true'); parser.add_argument('--reuse-bundle',action='store_true')
    parser.add_argument('--update-code',action='store_true',help='只更新发布源码和说明，保留用户 work 和已删除/已有的 results')
    parser.add_argument('--dist-dir',type=Path,default=ROOT/'release_v3',help='v3 发布目录；旧 release 禁止修改')
    args = parser.parse_args(); args.dist_dir=args.dist_dir.resolve()
    target = args.dist_dir/NAME
    if not target.resolve().is_relative_to((ROOT/'release_v3').resolve()):
        raise RuntimeError('OLD_RELEASE_PROTECTED: use --dist-dir release_v3; release_v2 is protected; old release is running')
    folder = ROOT/'work/release_v3/build'; folder.mkdir(parents=True,exist_ok=True)
    receipt = ROOT/'work/release/publication_manifest.json'
    if receipt.exists(): publication = json.loads(receipt.read_text(encoding='utf-8'))['publication_sha256']
    else:
        publication = Build_CapturePublication(); Build_WriteJson(receipt,dict(publication_sha256=publication))
    for name,digest in publication.items():
        if Build_Hash(ROOT/name)!=digest: raise RuntimeError('FROZEN_FILE_CHANGED: '+name)
    target = args.dist_dir/NAME
    if not target.resolve().is_relative_to((ROOT/'release_v3').resolve()):
        raise RuntimeError('OLD_RELEASE_PROTECTED: use --dist-dir release_v3; release_v2 is protected; old release is running')
    if args.update_code:
        assert (target/(CLI+'.exe')).is_file() and (target/'dependencies').is_dir()
        Build_StageCode(target)
        content=Build_GetReadme(json.loads((ROOT/'results/paper_facts.json').read_text(encoding='utf-8')))
        for name in ['README.md','请评委先看这份文件.txt']:(target/name).write_text(content,encoding='utf-8')
        Build_Manifest(target,publication)
        print('CODE UPDATED; user results/work preserved');return
    if not args.stage_only and not args.reuse_bundle:
        Build_ArchiveTarget(target)
        # Do not resolve native Qt's ICU dependency to an unrelated MSYS DLL.
        windows = Path(os.environ['SystemRoot'])
        tool_path = os.pathsep.join(map(str,[Path(sys.executable).parent,Path(sys.base_prefix),Path(sys.base_prefix)/'DLLs',windows/'System32',windows]))
        env = dict(os.environ,PATH=tool_path,DRYING_BUILD_ROOT=str(ROOT),PYINSTALLER_CONFIG_DIR=str(folder/'pyinstaller_cache'))
        command = [sys.executable,'-m','PyInstaller','--clean','--noconfirm','--distpath',str(args.dist_dir),
            '--workpath',str(folder/'pyinstaller'),str(ROOT/'scripts/judge_release.spec')]
        subprocess.run(command,cwd=ROOT,env=env,check=True)
    Build_Stage(target)
    if args.stage_only:
        Build_WriteJson(target/'release_manifest.json',dict(publication_sha256={k:v for k,v in publication.items() if k.startswith(('results/','data/'))}))
        print('STAGED',target); return
    assert sorted(p.name for p in target.glob('*.exe'))==sorted([GUI+'.exe',CLI+'.exe'])
    assert (target/'dependencies').is_dir() and not (target/'_internal').exists()
    assert (target/'README.md').read_bytes()==(target/'请评委先看这份文件.txt').read_bytes()
    assert not (target/'work').exists(), 'Build must not ship historical caches'
    value = Build_Manifest(target,publication)
    clean_env = dict(os.environ,PATH=str(Path(os.environ['SystemRoot'])/'System32'),PYTHONHOME='',PYTHONPATH='',DRYING_MODEL_ROOT=str(target),
        PYTHONDONTWRITEBYTECODE='1',NUMBA_CACHE_DIR=str(folder/'smoke_numba'))
    for flag in ['--verify','--runtime-check','--dry-run']:
        result = subprocess.run([str(target/(CLI+'.exe')),flag],env=clean_env,cwd=target,text=True,encoding='utf-8',errors='replace',capture_output=True,timeout=180)
        (folder/(flag[2:]+'_exe.log')).write_text(result.stdout+result.stderr,encoding='utf-8')
        if result.returncode: raise RuntimeError(flag+' EXE smoke failed: '+result.stdout+result.stderr)
    env = dict(clean_env,DRYING_GUI_SMOKE_FILE=str(folder/'exe_gui_smoke.json'))
    subprocess.run([str(target/(GUI+'.exe'))],env=env,cwd=target,check=True,timeout=45)
    assert json.loads((folder/'exe_gui_smoke.json').read_text(encoding='utf-8'))['visible']
    for name,digest in publication.items(): assert Build_Hash(ROOT/name)==digest,name
    print(json.dumps(dict(release=str(target),exe_sha256=value['exe_sha256'],clean_path_smoke='PASS',publication_unchanged=True),ensure_ascii=False,indent=2))


if __name__=='__main__': Build_Run()
