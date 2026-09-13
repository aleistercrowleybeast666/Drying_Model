"""Shared immutable files and explicit case ownership for private workspaces."""
import os
from pathlib import Path
import shutil
import uuid


def Resource_CopyMutableFile(source,destination):
    """Replace the destination inode before copying mutable setup metadata."""
    source=Path(source);destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    temporary=destination.with_name(destination.name+'.'+uuid.uuid4().hex+'.copy')
    try:shutil.copy2(source,temporary);os.replace(temporary,destination)
    finally:temporary.unlink(missing_ok=True)
    return str(destination)


def Resource_CopyFile(source,destination):
    """Share immutable files without ever writing through an existing hardlink."""
    source=Path(source);destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists():
        if os.path.samefile(source,destination):return str(destination)
        destination.unlink()
    try:os.link(source,destination)
    except OSError:shutil.copy2(source,destination)
    return str(destination)


def Resource_CopyTree(source,destination,immutable=False):
    source=Path(source);destination=Path(destination)
    if not source.exists():return
    shutil.copytree(source,destination,dirs_exist_ok=True,copy_function=Resource_CopyFile if immutable else shutil.copy2,
        ignore=shutil.ignore_patterns('__pycache__','*.pyc','.pytest_cache','~$*'))


def Resource_GetLocks(job):
    return {'baseline':['baseline_manifest','results_publish'],
        'validation_publish':['validation_summary','study_outputs'],
        'auxiliary':['validation_summary','study_outputs'],
        'extension_publish':['baseline_manifest','study_index','study_outputs','render_manifest'],
        'validation_study_plots':['study_outputs','render_manifest'],
        'mass_prepare':['mass_manifest'],'mass_publish':['study_outputs','mass_manifest'],
        'thermal_warmup':['jit_warmup'],'consistency':['results_publish'],
        'plot':['original_render']}.get(job['kind'],[])
