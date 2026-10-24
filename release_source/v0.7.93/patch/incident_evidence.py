"""Bounded first-failure evidence for each run; never mutates execution records."""
import os
from pathlib import Path
import re
import shutil
import tempfile

MAX_FILES=12
MAX_BYTES=24*1024*1024
from task_catalog import TASK_LABELS
_TASKS='|'.join(map(re.escape,TASK_LABELS))
_PATTERN=re.compile(rf'incident_[0-9a-f]{{24}}_[0-9a-f]{{32}}_(?:{_TASKS})_[a-z_]{{1,32}}_evidence\.zip')


def incidents(data):
    return [p for p in Path(data).glob('incident_*.zip')
            if _PATTERN.fullmatch(p.name) and p.is_file() and not p.is_symlink()]


def retain_incident(data,source,scope,run_id,task,step):
    from task_catalog import TASK_LABELS
    name=f'incident_{scope}_{run_id}_{task}_{step}_evidence.zip'
    if task not in TASK_LABELS or not _PATTERN.fullmatch(name):return
    data=Path(data);source=Path(source);target=data/name
    if source.is_symlink() or source.stat().st_size>12_000_000:return
    if target.is_symlink():return
    if not target.exists():
        temporary=None
        try:
            with tempfile.NamedTemporaryFile(dir=data,prefix='incident-',suffix='.tmp',delete=False) as stream:
                temporary=Path(stream.name)
                with source.open('rb') as original:shutil.copyfileobj(original,stream)
                stream.flush();os.fsync(stream.fileno())
            temporary.replace(target)
        finally:
            if temporary is not None:temporary.unlink(missing_ok=True)
    files=sorted(incidents(data),key=lambda p:(p.stat().st_mtime_ns,p.name),reverse=True)
    used=0
    for index,path in enumerate(files):
        size=path.stat().st_size
        if index>=MAX_FILES or used+size>MAX_BYTES:path.unlink()
        else:used+=size
