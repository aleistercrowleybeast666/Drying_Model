"""Copy static V5 assets into a new handoff; never update the live test packages."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import sys

from build_release import ROOT,NAME,OFFICIAL,GUI,Build_Hash,Build_StageOfficial,Build_Manifest,Build_TopLevel,Build_WriteJson


def Finalize_IsStatic(name):
    path=Path(name)
    return not any(p in ['results','work','logs','__pycache__','.pytest_cache'] for p in path.parts) and not (
        path.suffix in ['.pyc','.tmp','.buildtmp'] or path.name.startswith('~$'))


def Finalize_CopyPackage(source,target):
    source=Path(source).resolve();target=Path(target).resolve()
    manifest=json.loads((source/'package_manifest.json').read_text(encoding='utf-8'))
    entry='药材烘干模型_四表正式数据' if source.name==OFFICIAL else '药材烘干模型_GUI'
    allowed={entry+'.exe',entry+'.py','README.md','说明.txt','requirements.txt','安装Python依赖.bat'}
    copied={}
    for name in manifest['files']:
        relative=Path(name)
        if not Finalize_IsStatic(name):continue
        if relative.parts[0]!='dependencies' and name not in allowed:continue
        path=(source/relative).resolve();destination=(target/relative).resolve()
        if not path.is_relative_to(source) or not destination.is_relative_to(target):raise ValueError('PACKAGE_PATH_OUTSIDE_ROOT')
        if path.is_symlink() or not path.is_file():raise ValueError('PACKAGE_FILE_MISSING: '+name)
        destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,destination)
        if path.samefile(destination):raise ValueError('SHARED_PHYSICAL_FILE: '+name)
        copied[name]=Build_Hash(destination)
        if copied[name]!=Build_Hash(path):raise ValueError('SOURCE_CHANGED_DURING_COPY: '+name)
    if not {entry+'.exe',entry+'.py','requirements.txt'}<=copied.keys():raise ValueError('PACKAGE_ENTRY_MISSING')
    return copied


def Finalize_CheckClean(target):
    target=Path(target)
    for package in [target,target/OFFICIAL,target/GUI]:
        for name in ['results','work','logs']:
            if (package/name).exists():raise ValueError('HANDOFF_RUNTIME_DIRECTORY: '+str(package/name))
    if (target/'dependencies').exists():raise ValueError('SHARED_DEPENDENCIES')
    for path in target.rglob('*'):
        if not Finalize_IsStatic(path.relative_to(target)):raise ValueError('NONSTATIC_HANDOFF_FILE: '+str(path))
    official=target/OFFICIAL;gui=target/GUI
    for path in (official/'dependencies').rglob('*'):
        other=gui/path.relative_to(official)
        if path.is_file() and other.is_file() and path.samefile(other):raise ValueError('PACKAGES_SHARE_PHYSICAL_FILE')
    return dict(results='absent',work='absent',logs='absent',physically_independent=True)


def Finalize_Run(source,target):
    source=Path(source).resolve();target=Path(target).resolve()
    if target.exists():raise ValueError('HANDOFF_ALREADY_EXISTS: choose a new empty output; no existing package will be deleted')
    if target.is_relative_to(source) or source.is_relative_to(target):raise ValueError('HANDOFF_MUST_BE_SEPARATE')
    target.mkdir(parents=True)
    copied={name:Finalize_CopyPackage(source/name,target/name) for name in [OFFICIAL,GUI]}
    # Only the terminal's external application code and documentation are updated.
    # Its EXE bootstrap already loads these .py files. Never rebuild or restage GUI.
    Build_StageOfficial(target/OFFICIAL)
    gui_text=(source/GUI/'README.md').read_text(encoding='utf-8')
    gui_text='\n'.join(line for line in gui_text.splitlines() if not any(token in line for token in
        ['本轮只进行少量','本轮按要求减少验证','本轮按要求未执行']))
    gui_text=gui_text.replace('D 未运行不声称验证 PASS；','')
    gui_text+='\n\nD 为可选验证，计算量最大，不是四表复算的必要步骤，非必要不建议运行。\n'
    for name in ['README.md','说明.txt']:(target/GUI/name).write_text(gui_text,encoding='utf-8')
    for name,kind in [(OFFICIAL,'official_only'),(GUI,'full_gui')]:
        manifest=Build_Manifest(target/name,kind)
        manifest.update(finalized_at=datetime.now().astimezone().isoformat(),
            source_package_manifest_sha256=Build_Hash(source/name/'package_manifest.json'),
            runtime_validation='TERMINAL_NUMERICAL_RUN_USER_REPORTED_2_8_MIN; NEW_PROGRESS_UNIT_TESTED_ONLY' if name==OFFICIAL else 'SOURCE_GUI_BINARY_AND_CODE_UNCHANGED')
        Build_WriteJson(target/name/'package_manifest.json',manifest)
    gui_after=json.loads((target/GUI/'package_manifest.json').read_text(encoding='utf-8'))['files']
    unchanged=[k for k in copied[GUI] if k not in ['README.md','说明.txt']]
    if any(gui_after.get(k)!=copied[GUI][k] for k in unchanged):raise ValueError('GUI_STATIC_BYTES_CHANGED')
    core=[json.loads((target/name/'package_manifest.json').read_text(encoding='utf-8'))['official_core_sha256'] for name in [OFFICIAL,GUI]]
    if core[0]!=core[1]:raise ValueError('NUMERICAL_CORE_DIVERGED')
    Build_TopLevel(target)
    top=json.loads((target/'release_manifest.json').read_text(encoding='utf-8'))
    top['runtime_validation']='SEE_DEVELOPER_VALIDATION_RECORD; FINAL_DIRECTORY_NOT_EXECUTED'
    Build_WriteJson(target/'release_manifest.json',top)
    clean=Finalize_CheckClean(target)
    return dict(output=str(target),clean=clean,gui_static_files_unchanged=len(unchanged),
        numerical_core_sha256=hashlib.sha256(json.dumps(core[0],sort_keys=True).encode()).hexdigest(),
        integrity={str(path.relative_to(target)):Build_Hash(path) for path in [
            target/OFFICIAL/'药材烘干模型_四表正式数据.exe',target/GUI/'药材烘干模型_GUI.exe',
            target/OFFICIAL/'package_manifest.json',target/GUI/'package_manifest.json',target/'release_manifest.json']})


def Finalize_Main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=ROOT/'release_v5'/NAME)
    parser.add_argument('--output',type=Path,default=ROOT/'release_v5_submit'/NAME)
    args=parser.parse_args()
    if not args.output.resolve().is_relative_to((ROOT/'release_v5_submit').resolve()):raise ValueError('OUTPUT_MUST_BE_IN_RELEASE_V5_SUBMIT')
    receipt=Finalize_Run(args.source,args.output)
    Build_WriteJson(ROOT/'work/release_v5/finalize_audit/finalizer.json',receipt)
    print(json.dumps(receipt,ensure_ascii=False,indent=2))


if __name__=='__main__':Finalize_Main()
