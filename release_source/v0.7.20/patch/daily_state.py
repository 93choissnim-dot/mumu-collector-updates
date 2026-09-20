"""Persistent per-MuMu checkpoints, with a fixed Korea midnight boundary."""
import copy
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collector import Halt

KST=timezone(timedelta(hours=9))
DAILY_TASKS=('daily_pass','daily_dungeons','daily_guild')
DAILY_ALREADY={'daily_pass':'already_complete','daily_dungeons':'no_entries','daily_guild':'already_claimed'}

def korea_now():return datetime.now(KST)
def korea_day(now=None):return (now or korea_now()).astimezone(KST).date().isoformat()
def seconds_to_midnight(now=None):
    now=(now or korea_now()).astimezone(KST)
    return ((now+timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0)-now).total_seconds()

class DailyLedger:
    def __init__(self,path):
        self.path=Path(path);self.lock=threading.RLock()
        try:self.data=json.loads(self.path.read_text(encoding='utf-8'))
        except FileNotFoundError:self.data={}
        except (OSError,ValueError) as exc:raise Halt('일일 완료 기록을 읽지 못했습니다. 중복 실행을 막기 위해 일일 작업을 보류합니다.') from exc
        if not isinstance(self.data,dict):raise Halt('일일 완료 기록 형식을 확인해 주세요.')
    def get(self,ident,task,step='_complete',day=None):
        with self.lock:
            entry=self.data.get(ident,{}).get(day or korea_day(),{}).get(task,{})
            return entry.get(step) if isinstance(entry,dict) else None
    def done(self,ident,task,step='_complete',day=None):return self.get(ident,task,step,day)=='done'
    def mark(self,ident,task,step='_complete',value='done',day=None):
        with self.lock:
            data=copy.deepcopy(self.data)
            days=data.setdefault(ident,{})
            days.setdefault(day or korea_day(),{}).setdefault(task,{})[step]=value
            for old in sorted(days)[:-7]:del days[old]
            self.path.parent.mkdir(parents=True,exist_ok=True)
            tmp=self.path.with_suffix('.tmp')
            try:
                tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(self.path)
            except OSError as exc:raise Halt('일일 기록 저장 실패: '+str(exc)) from exc
            self.data=data

class DailySchedule:
    """Merge common intervals and midnight daily batches without waking finished VMs."""
    def __init__(self,selected,interval,clock,wall=korea_now):
        from run_support import Schedule
        self.clock,self.wall=clock,wall
        self.selected=list(selected);self.day=None;self.chosen=[]
        repeated=[r for r in selected if r not in DAILY_TASKS]
        daily=[r for r in selected if r in DAILY_TASKS]
        self.parts=[]
        if repeated:self.parts.append(('repeat',Schedule(repeated,interval)))
        if daily:self.parts.append(('daily',Schedule(daily,86400)))
    def next(self):
        now=self.wall();day=korea_day(now)
        choices=[]
        for kind,schedule in self.parts:
            if kind=='daily':
                if self.day is not None and day!=self.day:
                    schedule.regular_at=0;schedule.pending.clear();schedule.attempts.clear();self.day=None
                elif self.day==day:schedule.regular_at=self.clock()+seconds_to_midnight(now)
            due,rooms,retry=schedule.next();choices.append((due,kind,schedule,rooms,retry,day))
        earliest=min(c[0] for c in choices)
        self.chosen=[c for c in choices if c[0]==earliest]
        rooms=[r for r in self.selected if any(r in c[3] for c in self.chosen)]
        return earliest,rooms,all(c[4] for c in self.chosen)
    def complete(self,rooms,results,retry,now):
        for _,kind,schedule,selected,is_retry,day in self.chosen:
            schedule.complete(selected,results,is_retry,now)
            if kind=='daily' and not is_retry:self.day=day
