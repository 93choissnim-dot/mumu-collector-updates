"""Persistent uncertain inputs and repeated failures, separate from daily completion."""
import copy
import hashlib
import json
import threading
from pathlib import Path
from daily_state import LedgerError,new_input_request,archive_input
from version import VERSION


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
        self.path=Path(path) if path else None;self.scope=scope;self.data={};self.lock=threading.RLock()
        if self.path:
            try:self.data=json.loads(self.path.read_text(encoding='utf-8'))
            except FileNotFoundError:pass
            except (OSError,ValueError) as exc:raise LedgerError('작업 진행 기록을 읽지 못해 실행을 보류합니다.') from exc
        if not isinstance(self.data,dict) or any(not isinstance(v,dict) or any(not isinstance(e,dict) for e in v.values()) for v in self.data.values()):
            raise LedgerError('작업 진행 기록 형식을 확인해 주세요.')
        for tasks in self.data.values():
            for entry in tasks.values():
                pending=entry.get('pending',{})
                if (not isinstance(pending,dict) or any(not isinstance(v,dict) for v in pending.values())
                    or type(entry.get('failures',0)) is not int or entry.get('failures',0)<0
                    or type(entry.get('blocked',False)) is not bool):
                    raise LedgerError('작업 진행 기록 형식을 확인해 주세요.')
    def get(self,task):
        with self.lock:return copy.deepcopy(self.data.get(self.scope,{}).get(task,{}))
    def update(self,task,**fields):
        with self.lock:
            data=copy.deepcopy(self.data);entry=data.setdefault(self.scope,{}).setdefault(task,{})
            entry.update(fields)
            if self.path:
                tmp=self.path.with_suffix('.tmp')
                try:
                    self.path.parent.mkdir(parents=True,exist_ok=True)
                    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(self.path)
                except OSError as exc:raise LedgerError('작업 진행 기록 저장 실패 / 입력 보류') from exc
            self.data=data
    def pending(self,task,slot='claim'):return self.get(task).get('pending',{}).get(slot)
    def reserve(self,task,slot='claim',*,repeat_authorized=False):
        with self.lock:
            entry=self.get(task);pending=entry.get('pending',{});replaced=slot in pending
            if replaced:
                if not repeat_authorized:return
                request=copy.deepcopy(pending[slot]);request.setdefault('action',slot)
                if not request.get('requested_at'):request.setdefault('origin','legacy_unknown')
                # Permission is enforced by the caller's guarded free-claim route.
                # Retire the old uncertainty and reserve the actual retry atomically.
                archive_input(entry,request,'uncertain',VERSION,
                              source='manual_free_claim_retry',retry_authorized=True)
            pending[slot]=new_input_request(slot,VERSION)
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
        e=self.get(task);return e.get('version')==VERSION and e.get('blocked',False)
    def fail(self,task,step,state,reason):
        e=self.get(task);fingerprint=hashlib.sha256((step+'|'+state+'|'+reason).encode()).hexdigest()
        count=e.get('failures',0)+1 if e.get('version')==VERSION and e.get('fingerprint')==fingerprint else 1
        self.update(task,version=VERSION,fingerprint=fingerprint,failures=count,blocked=count>=2)
        return count>=2
    def reset(self,task):self.update(task,version=VERSION,failures=0,blocked=False,fingerprint='')
