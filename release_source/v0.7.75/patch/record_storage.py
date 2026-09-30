"""Durable JSON replacement and shared reader/writer locks for record files."""
import json
import os
import tempfile
import threading
import time
from pathlib import Path

_LOCKS={}
_LOCKS_GUARD=threading.Lock()


def path_lock(path):
    key=os.path.normcase(str(Path(path).resolve()))
    with _LOCKS_GUARD:return _LOCKS.setdefault(key,threading.RLock())


def save_json(path,data):
    path=Path(path);tmp=None
    with path_lock(path):
        try:
            path.parent.mkdir(parents=True,exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,
                    prefix=path.name+'.',suffix='.tmp',delete=False) as stream:
                tmp=Path(stream.name)
                json.dump(data,stream,ensure_ascii=False,indent=2)
                stream.flush();os.fsync(stream.fileno())
            for attempt in range(3):
                try:
                    tmp.replace(path);break
                except OSError as exc:
                    if getattr(exc,'winerror',None) not in (32,33) or attempt==2:raise
                    time.sleep(.05*(attempt+1))
        finally:
            if tmp is not None:
                try:tmp.unlink(missing_ok=True)
                except OSError:pass
