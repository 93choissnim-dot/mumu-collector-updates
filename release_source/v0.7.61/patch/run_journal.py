"""Private unfinished work checkpoints, scoped to account and KST date."""
import copy
import json
from pathlib import Path
from daily_state import LedgerError,korea_day
from history import TERMINAL_RESULTS
from task_catalog import TASK_LABELS
from version import VERSION
from datetime import datetime,timezone
from history import RESULTS

class RunJournal:
    def __init__(self,path):
        self.path=Path(path)
        try:self.data=json.loads(self.path.read_text(encoding='utf-8'))
        except FileNotFoundError:self.data={}
        except (OSError,ValueError) as exc:raise LedgerError('이어하기 기록을 읽지 못했습니다. 진단 파일을 확인해 주세요.') from exc
        if not isinstance(self.data,dict):raise LedgerError('이어하기 기록 형식 오류')
        for record in self.data.values():
            if (not isinstance(record,dict) or not isinstance(record.get('day'),str)
                or not isinstance(record.get('tasks'),list) or any(not isinstance(t,str) or t not in TASK_LABELS for t in record['tasks'])
                or not isinstance(record.get('results'),dict)
                or any(not isinstance(v,str) or v not in RESULTS for v in record.get('results',{}).values())
                or not isinstance(record.get('entries',{}),dict)
                or any(not isinstance(v,dict) for v in record.get('entries',{}).values())):
                raise LedgerError('이어하기 기록 형식 오류')
    def _save(self,data):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        tmp=self.path.with_suffix('.tmp')
        try:
            tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(self.path)
        except OSError as exc:raise LedgerError('이어하기 기록 저장 실패 / 입력 보류') from exc
        self.data=data
    def begin(self,scope,tasks,day=None):
        if any(t not in TASK_LABELS for t in tasks):raise LedgerError('지원하지 않는 이어하기 작업')
        day=day or korea_day();previous=self.data.get(scope,{})
        keep=[t for t in self.remaining(scope,day) if t not in tasks]
        record={'day':day,'version':VERSION,'started_at':datetime.now(timezone.utc).isoformat(),
                'tasks':list(dict.fromkeys([*tasks,*keep])), 'planned':list(tasks),
                'results':{t:v for t,v in previous.get('results',{}).items() if t in keep},
                'entries':{t:v for t,v in previous.get('entries',{}).items() if t in keep}}
        self._save({**self.data,scope:record})
    def continue_run(self,scope,tasks,day=None):
        if self.data.get(scope,{}).get('day')!=(day or korea_day()):return False
        if not set(tasks).issubset(self.remaining(scope,day)):raise LedgerError('이어하기 대상이 변경됐습니다.')
        return True
    def result(self,scope,task,result,entry=None):
        if result not in RESULTS:raise LedgerError('지원하지 않는 작업 결과')
        data=copy.deepcopy(self.data);record=data.get(scope)
        if record is None or task not in record['tasks']:return
        record['results'][task]=result
        if entry is not None:record.setdefault('entries',{})[task]=copy.deepcopy(entry)
        self._save(data)
    def remaining(self,scope,day=None):
        record=self.data.get(scope,{})
        if record.get('day')!=(day or korea_day()):return []
        return [t for t in record.get('tasks',[]) if record['results'].get(t) not in TERMINAL_RESULTS]
