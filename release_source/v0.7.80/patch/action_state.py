"""Persistent uncertain inputs and repeated failures, separate from daily completion."""
import copy
import hashlib
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from daily_state import LedgerError,new_input_request,archive_input
from version import VERSION
from recognition_backoff import recognition_hold,RECHECK_SECONDS


# UI snapshots and fleet workers share this file in one application process.
# Serialize readers too: an open Windows read handle can prevent replacement.
_PATH_LOCKS = {}
_PATH_LOCKS_GUARD = threading.Lock()


def _path_lock(path):
    key = os.path.normcase(str(path.resolve()))
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, threading.RLock())


def _os_reason(exc):
    winerror = getattr(exc, 'winerror', None)
    return f'{exc} (winerror={winerror})' if winerror is not None else str(exc)


def account_scope(ident, label=''):
    label=normalize_account(label)
    return hashlib.sha256((ident+'\0'+label).encode()).hexdigest()[:24] if label else ident


def normalize_account(label):
    import unicodedata
    if not isinstance(label,str):raise ValueError('계정/캐릭터 구분을 확인해 주세요.')
    label=unicodedata.normalize('NFC',label.strip())
    if len(label)>40 or any(ord(c)<32 for c in label):raise ValueError('계정/캐릭터 구분은 줄바꿈 없이 40자 이내로 입력해 주세요.')
    return label


class ActionState:
    def __init__(self,path=None,scope='local'):
        self.path=Path(path).resolve() if path else None;self.scope=scope;self.data={}
        self.lock=_path_lock(self.path) if self.path else threading.RLock()
        with self.lock:self.data=self._read()
    def _read(self):
        data=self.data
        if self.path:
            try:data=json.loads(self.path.read_text(encoding='utf-8'))
            except FileNotFoundError:
                # A deleted existing ledger must not silently erase pending claims.
                if self.data:raise LedgerError('작업 진행 기록이 없어 실행을 보류합니다.')
                data={}
            except (OSError,ValueError) as exc:
                raise LedgerError(f'작업 진행 기록을 읽지 못해 실행을 보류합니다. / {_os_reason(exc)}') from exc
        if not isinstance(data,dict) or any(not isinstance(v,dict) or any(not isinstance(e,dict) for e in v.values()) for v in data.values()):
            raise LedgerError('작업 진행 기록 형식을 확인해 주세요.')
        for tasks in data.values():
            for entry in tasks.values():
                pending=entry.get('pending',{})
                if (not isinstance(pending,dict) or any(not isinstance(v,dict) for v in pending.values())
                    or type(entry.get('failures',0)) is not int or entry.get('failures',0)<0
                    or type(entry.get('blocked',False)) is not bool):
                    raise LedgerError('작업 진행 기록 형식을 확인해 주세요.')
        return data
    def get(self,task):
        with self.lock:
            self.data=self._read()
            return copy.deepcopy(self.data.get(self.scope,{}).get(task,{}))
    def update(self,task,**fields):
        with self.lock:
            data=copy.deepcopy(self._read());entry=data.setdefault(self.scope,{}).setdefault(task,{})
            entry.update(fields)
            if self.path:
                tmp=None
                try:
                    self.path.parent.mkdir(parents=True,exist_ok=True)
                    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',
                            dir=self.path.parent,prefix=self.path.name+'.',suffix='.tmp',delete=False) as stream:
                        tmp=Path(stream.name)
                        json.dump(data,stream,ensure_ascii=False,indent=2)
                        stream.flush();os.fsync(stream.fileno())
                    # Only explicit Windows sharing/lock violations are transient.
                    # No input or callback can run until replacement succeeds.
                    for attempt in range(3):
                        try:
                            tmp.replace(self.path)
                            break
                        except OSError as exc:
                            if getattr(exc,'winerror',None) not in (32,33) or attempt==2:raise
                            time.sleep(0.05*(attempt+1))
                except OSError as exc:
                    raise LedgerError(f'작업 진행 기록 저장 실패 / 입력 보류 / {_os_reason(exc)}') from exc
                finally:
                    if tmp is not None:
                        try:tmp.unlink(missing_ok=True)
                        except OSError:pass
            self.data=data
    def pending(self,task,slot='claim'):return self.get(task).get('pending',{}).get(slot)
    def reserve(self,task,slot='claim',*,repeat_authorized=False,evidence=None,repeat_source='manual_free_claim_retry'):
        with self.lock:
            entry=self.get(task);pending=entry.get('pending',{});replaced=slot in pending
            if replaced:
                if not repeat_authorized:return
                request=copy.deepcopy(pending[slot]);request.setdefault('action',slot)
                if not request.get('requested_at'):request.setdefault('origin','legacy_unknown')
                # Permission is enforced by the caller's guarded retry/repeat route.
                # Retire the old uncertainty and reserve the actual retry atomically.
                archive_input(entry,request,'uncertain',VERSION,
                              source=repeat_source,retry_authorized=True)
            pending[slot]=new_input_request(slot,VERSION)
            if evidence is not None:pending[slot]['evidence']=copy.deepcopy(evidence)
            entry['pending']=pending
            self.update(task,**entry)
            callback=getattr(self,'on_input_evidence',None)
            if callback:
                if replaced:callback('resolved',task,slot,self.get(task))
                callback('requested',task,slot,self.get(task))
    def confirm(self,task,slot='claim',*,status='done',source='screen_confirmed',manual_resolution=None,**fields):
        with self.lock:
            entry=self.get(task);pending=entry.get('pending',{});exists=slot in pending
            request=pending.pop(slot,None)
            entry.update(fields,pending=pending)
            if manual_resolution is not None:entry['manual_resolution']=copy.deepcopy(manual_resolution)
            if exists:
                request=copy.deepcopy(request)
                request.setdefault('action',slot)
                if not request.get('requested_at'):request.setdefault('origin','legacy_unknown')
                archive_input(entry,request,status,VERSION,source=source,manual_resolution=manual_resolution)
            self.update(task,**entry)
            callback=getattr(self,'on_input_evidence',None)
            if exists and callback:callback('resolved',task,slot,self.get(task))
    def blocked(self,task):
        e=self.get(task);return e.get('version')==VERSION and e.get('blocked',False) and recognition_hold(e)
    def fail(self,task,step,state,reason):
        with self.lock:
            e=self.get(task);fingerprint=hashlib.sha256((step+'|'+state+'|'+reason).encode()).hexdigest()
            count=e.get('failures',0)+1 if e.get('version')==VERSION and e.get('fingerprint')==fingerprint else 1
            self.update(task,version=VERSION,fingerprint=fingerprint,failures=count,blocked=count>=2,
                        retry_after=time.time()+RECHECK_SECONDS if count>=2 else None)
            return count>=2
    def reset(self,task):self.update(task,version=VERSION,failures=0,blocked=False,fingerprint='',retry_after=None)
