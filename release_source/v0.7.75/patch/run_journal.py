"""Private unfinished work checkpoints, scoped to account and KST date."""
import copy
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from daily_state import LedgerError,korea_day
from history import TERMINAL_RESULTS
from task_catalog import TASK_LABELS
from version import VERSION
from datetime import datetime,timezone
from history import RESULTS


# Fleet workers and UI snapshots must serialize both reads and replacements.
_PATH_LOCKS = {}
_PATH_LOCKS_GUARD = threading.Lock()


def _path_lock(path):
    key = os.path.normcase(str(path.resolve()))
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, threading.RLock())


def _os_reason(exc):
    # Include the destination separately; never stringify journal contents.
    reason = str(exc.strerror or type(exc).__name__).replace('\n', ' ')[:240]
    code = getattr(exc, 'winerror', None)
    return f'{reason} (winerror={code})' if code is not None else f'{reason} (errno={exc.errno})'


class RunJournal:
    def __init__(self,path):
        self.path=Path(path).resolve();self.data={};self.lock=_path_lock(self.path)
        with self.lock:self.data=self._read()
    def _read(self):
        try:data=json.loads(self.path.read_text(encoding='utf-8'))
        except FileNotFoundError as exc:
            if self.data:raise LedgerError(f'이어하기 기록이 없어 실행을 보류합니다. / {self.path}') from exc
            data={}
        except OSError as exc:
            raise LedgerError(f'이어하기 기록 읽기 실패 / 입력 보류 / {self.path} / {_os_reason(exc)}') from exc
        except ValueError as exc:
            raise LedgerError(f'이어하기 기록 형식 오류 / 입력 보류 / {self.path}') from exc
        if not isinstance(data,dict):raise LedgerError('이어하기 기록 형식 오류')
        for record in data.values():
            if (not isinstance(record,dict) or not isinstance(record.get('day'),str)
                or not isinstance(record.get('tasks'),list) or any(not isinstance(t,str) or t not in TASK_LABELS for t in record['tasks'])
                or not isinstance(record.get('results'),dict)
                or any(not isinstance(v,str) or v not in RESULTS for v in record.get('results',{}).values())
                or not isinstance(record.get('entries',{}),dict)
                or any(not isinstance(v,dict) for v in record.get('entries',{}).values())):
                raise LedgerError('이어하기 기록 형식 오류')
        return data
    def _save(self,data):
        tmp=None
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=self.path.parent,
                    prefix=self.path.name+'.',suffix='.tmp',delete=False) as stream:
                tmp=Path(stream.name)
                json.dump(data,stream,ensure_ascii=False,indent=2)
                stream.flush();os.fsync(stream.fileno())
            for attempt in range(3):
                try:
                    tmp.replace(self.path)
                    break
                except OSError as exc:
                    if getattr(exc,'winerror',None) not in (32,33) or attempt==2:raise
                    time.sleep(0.05*(attempt+1))
        except OSError as exc:
            raise LedgerError(f'이어하기 기록 저장 실패 / 입력 보류 / {self.path} / {_os_reason(exc)}') from exc
        finally:
            if tmp is not None:
                try:tmp.unlink(missing_ok=True)
                except OSError:pass
        self.data=data
    def begin(self,scope,tasks,day=None):
        if any(t not in TASK_LABELS for t in tasks):raise LedgerError('지원하지 않는 이어하기 작업')
        with self.lock:
            data=self._read();day=day or korea_day();previous=data.get(scope,{})
            keep=[t for t in self._remaining(previous,day) if t not in tasks]
            record={'day':day,'version':VERSION,'started_at':datetime.now(timezone.utc).isoformat(),
                    'tasks':list(dict.fromkeys([*tasks,*keep])), 'planned':list(tasks),
                    'results':{t:v for t,v in previous.get('results',{}).items() if t in keep},
                    'entries':{t:v for t,v in previous.get('entries',{}).items() if t in keep}}
            self._save({**data,scope:record})
    def continue_run(self,scope,tasks,day=None):
        with self.lock:
            self.data=self._read();day=day or korea_day();record=self.data.get(scope,{})
            if record.get('day')!=day:return False
            if not set(tasks).issubset(self._remaining(record,day)):raise LedgerError('이어하기 대상이 변경됐습니다.')
            return True
    def result(self,scope,task,result,entry=None):
        if result not in RESULTS:raise LedgerError('지원하지 않는 작업 결과')
        with self.lock:
            data=copy.deepcopy(self._read());record=data.get(scope)
            if record is None or task not in record['tasks']:return
            record['results'][task]=result
            if entry is not None:record.setdefault('entries',{})[task]=copy.deepcopy(entry)
            self._save(data)
    @staticmethod
    def _remaining(record,day):
        if record.get('day')!=day:return []
        return [t for t in record.get('tasks',[]) if record['results'].get(t) not in TERMINAL_RESULTS]
    def remaining(self,scope,day=None):
        with self.lock:
            self.data=self._read()
            return self._remaining(self.data.get(scope,{}),day or korea_day())
