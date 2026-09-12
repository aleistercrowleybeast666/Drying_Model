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
CLI = '药材烘干模型_完整离线复算'


def Build_Hash(path):
    with Path(path).open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()


def Build_WriteJson(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def Build_ArchiveTarget(target):
    """Preserve the used package outside release before replacing it."""
    target=Path(target).resolve()
    if not target.exists():return None
    if not target.is_relative_to((ROOT/'release').resolve()):raise ValueError('Archive target outside release workspace')
    sys.path.insert(0,str(ROOT/'src'))
    from drying.runner_control import Runner_Stop,RunnerStopResult
    if Runner_Stop(target)==RunnerStopResult.FAILED:raise RuntimeError('Cannot stop release runner; package retained')
    import psutil
    for process in psutil.process_iter(['exe']):
        if process.info['exe'] and Path(process.info['exe']).resolve()==target/(GUI+'.exe'):
            process.kill();process.wait(timeout=5)
    archive=(ROOT/'work/release'/('previous_package_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))).resolve()
    if not archive.is_relative_to((ROOT/'work/release').resolve()):raise ValueError('Invalid archive directory')
    shutil.move(str(target),str(archive))
    print('PREVIOUS PACKAGE PRESERVED:',archive,flush=True)
    return archive


def Build_GetReadme(facts):
    return f'''2026 全国大学生数学建模竞赛 A题
药材烘干模型计算程序

一、最简单的使用方式

Windows：
1. 双击“{GUI}.exe”。
2. 勾选需要复算的项目（默认仅正式题目）。
3. 点击“开始离线复算”。

如需完整复算全部内容，直接双击“{CLI}.exe”。
以上 EXE 不需要安装 Python。请先完整解压，保留 dependencies 文件夹。

二、已有 Python / 非 Windows 用户

建议 Python 3.12（64 位）。Windows 可双击“安装Python依赖.bat”。
也可执行：python -m pip install -r requirements.txt
然后执行：python {GUI}.py
或完整复算：python {CLI}.py
只验证已有交付文件：python {CLI}.py --verify
只查看复算计划（不计算）：python {CLI}.py --dry-run

三、文件夹

dependencies/  共享运行依赖；application/ 内包含源码、冻结配置和原始输入，请勿删除
release_manifest.json  文件清单和 SHA256

复算时才创建 work/recompute/，输出位于 work/recompute/results/。
本包不附带历史缓存、检查点或计算结果。首次计算自动新建工作目录和 results/，logs/ 保存运行日志。
已有匹配缓存可复用；没有缓存也可以从原始输入计算。--verify 在无结果时只校验随包源码/配置/输入完整性。
原始数值源码原样复制到独立工作区，物理公式、网格、阈值均不改变。
不要移动正在运行的发布目录，也不要删除其工作缓存。

四、正式结果

Q3 烘干时间：{facts['official']['Q3']['drying_time_h']:.4f} h
Q4 烘干时间：{facts['official']['Q4']['drying_time_h']:.4f} h
上面数字是冻结工程的参考结果；本精简包不附带既有计算结果，运行后生成本次结果。
正式结果采用 M00 一维径向模型。
二维辅助验收 PASS，用于端面效应、降维合理性和终点鲁棒性。
二维完整网格独立性仍未认证（PARTIAL_2D）。
M10/M01/M11 是补充敏感性研究，不替代正式 M00。

五、复算顺序和进度

无参数运行完整入口：正式 Q1、Q2/Q3、Q4 → 二维轨迹/方向验证 → 正式图表 →
冻结本次复算基线 → M00 补充基础验证、几何和环境研究 → M10 → M01 → M11 →
补充图表 → 几何—物性交叉及两张相关图 → 水质量守恒 → 二维辅助验收汇总 →
复算结果及交付事实一致性检查。
基础研究统一执行一次；各权威入口核对匹配缓存后复用，不匹配则重算。
全选的 17 阶段中，第 1～3 阶段生成一维结果和 Excel，第 4 阶段准备二维数据，
第 5 阶段统一生成 Q1～Q4 正式图片及 GIF；第 11 阶段生成补充图，第 13 阶段生成技术图。
仅勾选某道正式题目时，只算对应一维轨迹、验证和 Excel。
综合二维图表需勾选二维辅助；补充研究需要全部正式/二维基线，依赖任务会显示。
水质量守恒需要全部四种模式；几何交叉的既有统一事实发布器也需要四模式数据，因此这两项会补齐 M10/M01/M11。
其他部分研究只刷新已有数据对应的图，不伪造缺失模式的图表。
进度条按实际已完成阶段单调增加；阶段内部保持不变，不循环、不按耗时估算百分比。
日志默认折叠。“立即停止”会结束本次复算及其子进程，不再等待数值检查点。
立即停止在任务运行时呈橙色可点击；未运行时灰色。
运行时仍可修改下一轮项目；开始按钮用于查看当前状态，不会启动重复复算。
重新打开 GUI 会识别同目录仍在运行的复算；关闭 GUI 会同时结束该复算进程树。
写入位置包括 work/recompute 中的缓存、检查点、验证记录和结果，不只是 results。
强制停止会丢失未保存进度，未完成文件可能需要重新生成；重启时仅复用原验证器认可的缓存。
日志使用大字号深色文字，展开后可拖动分隔线调整高度，长行支持横向滚动。
如果删除 results，复算仍能从 data 和 code/configs 启动；成功完成的输出会同步重建 results。
已有 results 时仍保持原交付文件不变，复算输出单独在 work/recompute/results。
仅复算部分项目只生成对应结果；快速验证不会代替缺失结果的计算。
路径以当前 EXE/PY 所在文件夹为基准，可整体移动；无需原开发电脑的盘符或目录。
异常回溯里操作系统展开的路径是本次运行位置，并非写死的依赖路径。

六、说明

完整离线复算耗时很长，可能需要数小时至数天及大量磁盘空间。
交付包不包含开发期巨大轨迹缓存；首次复算会真实生成所需缓存。
GUI 可只勾选需要检查的部分；全选、全不选、仅正式题目均在同一页面。
快速验证仅核对已有文件哈希和状态/事实一致性，不声称重新验证省略的原始缓存。
不需要联网取得题目数据；源码方式首次安装依赖需要网络或预下载的 wheel。
构建及测试详情见 dependencies/application/code/RELEASE_VALIDATION.md（明确列出未执行的长时测试）。
'''


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
echo python 药材烘干模型_完整离线复算.py
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
    for name in ['README.md','requirements-build.txt','requirements.txt','pytest.ini','RELEASE_VALIDATION.md']:
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
    parser.add_argument('--dist-dir',type=Path,default=ROOT/'release',help='最终发布目录；替换前保留旧包到 work/release')
    args = parser.parse_args(); folder = ROOT/'work/release'; folder.mkdir(parents=True,exist_ok=True)
    receipt = folder/'publication_manifest.json'
    if receipt.exists(): publication = json.loads(receipt.read_text(encoding='utf-8'))['publication_sha256']
    else:
        publication = Build_CapturePublication(); Build_WriteJson(receipt,dict(publication_sha256=publication))
    for name,digest in publication.items():
        if Build_Hash(ROOT/name)!=digest: raise RuntimeError('FROZEN_FILE_CHANGED: '+name)
    target = args.dist_dir/NAME
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
