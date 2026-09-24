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
DAILY_STEPS={'daily_pass':('ad','keys','gear'),
    'daily_dungeons':('equipment','summon','stone','rune','relic','treasure','artifact'),
    'daily_guild':('attendance','donation','relic','shop','dungeon','raid')}
DAILY_STEP_LABELS={'ad':'광고 제거','keys':'던전 멤버십','gear':'장비 멤버십',
    'equipment':'장비 보급소','summon':'소환 던전','stone':'스톤 채굴장','rune':'룬 동굴',
    'relic':'유물 던전','treasure':'보물 창고','artifact':'아티팩트 공방',
    'attendance':'출석','donation':'기부','shop':'무료 코인','dungeon':'길드 던전','raid':'공방 약탈'}

def step_label(task,step):
    return '성물 보상' if task=='daily_guild' and step=='relic' else DAILY_STEP_LABELS.get(step,step)

class LedgerError(Halt):
    """Persistence failures must stop all inputs, including recovery navigation."""

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
        except (OSError,ValueError) as exc:raise LedgerError('일일 완료 기록을 읽지 못했습니다. 중복 실행을 막기 위해 일일 작업을 보류합니다.') from exc
        if not isinstance(self.data,dict) or any(not isinstance(days,dict) or any(
                not isinstance(tasks,dict) or any(not isinstance(entry,dict) for entry in tasks.values())
                for tasks in days.values()) for days in self.data.values()):
            raise LedgerError('일일 완료 기록 형식을 확인해 주세요.')
    def get(self,ident,task,step='_complete',day=None):
        with self.lock:
            entry=self.data.get(ident,{}).get(day or korea_day(),{}).get(task,{})
            return entry.get(step) if isinstance(entry,dict) else None
    def done(self,ident,task,step='_complete',day=None):return self.get(ident,task,step,day)=='done'
    def mark(self,ident,task,step='_complete',value='done',day=None):
        self.update(ident,task,{step:value},day)
    def snapshot(self,ident,day=None):
        with self.lock:return copy.deepcopy(self.data.get(ident,{}).get(day or korea_day(),{}))
    def detail(self,ident,task,step,day=None):
        details=self.get(ident,task,'_steps',day)
        value=details.get(step,{}) if isinstance(details,dict) else {}
        return copy.deepcopy(value) if isinstance(value,dict) else {}
    def checkpoint(self,ident,task,step,status,day=None,values=None,**fields):
        with self.lock:
            details=self.get(ident,task,'_steps',day)
            details=copy.deepcopy(details) if isinstance(details,dict) else {}
            entry=self.detail(ident,task,step,day)
            entry.update(fields,status=status,updated_at=korea_now().isoformat(timespec='milliseconds'))
            details[step]=entry
            changes=dict(values or {});changes['_steps']=details
            self.update(ident,task,changes,day)
    def reset_blocked(self,ident,task,day=None):
        for step in DAILY_STEPS[task]:
            detail=self.detail(ident,task,step,day)
            if detail.get('status')=='blocked':
                self.checkpoint(ident,task,step,'pending',day,failures=0,fingerprint='')
    def update(self,ident,task,values,day=None):
        with self.lock:
            data=copy.deepcopy(self.data)
            days=data.setdefault(ident,{})
            days.setdefault(day or korea_day(),{}).setdefault(task,{}).update(values)
            for old in sorted(days)[:-7]:del days[old]
            self.path.parent.mkdir(parents=True,exist_ok=True)
            tmp=self.path.with_suffix('.tmp')
            try:
                tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(self.path)
            except OSError as exc:raise LedgerError('일일 기록 저장 실패: '+str(exc)) from exc
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
