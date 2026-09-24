"""Persistent per-MuMu checkpoints, with a fixed Korea midnight boundary."""
import copy
import json
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collector import Halt
from version import VERSION

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

INPUT_HISTORY_LIMIT=8
INPUT_ARCHIVE_FIELDS=('last_input','input_resolution','input_history')

def new_input_request(action,version):
    """Record dispatch intent once; later observations must not become its origin."""
    return {'id':uuid.uuid4().hex,'action':action,
            'requested_at':korea_now().isoformat(timespec='milliseconds'),'version':version}

def archive_input(entry,request,status,version,*,source=None,manual_resolution=None,retry_authorized=False):
    """Keep bounded origins/results without mistaking a rearm for game evidence."""
    manual=manual_resolution if isinstance(manual_resolution,dict) else None
    if retry_authorized:
        kind='retry_authorized';confirmed=False
    elif manual is not None:
        kind='manual_resolution';confirmed=manual.get('outcome')=='completed'
    else:
        confirmed=status in {'done','running'}
        kind='confirmed' if confirmed else 'unconfirmed'
    resolution={'at':korea_now().isoformat(timespec='milliseconds'),'version':version,
                'status':status,'kind':kind,'confirmed':confirmed,
                'source':source or (manual.get('source','user_confirmed') if manual is not None else
                                    'screen_confirmed' if confirmed else 'checkpoint')}
    if manual is not None:resolution['outcome']=manual.get('outcome')
    history=entry.get('input_history',[])
    history=copy.deepcopy(history[-(INPUT_HISTORY_LIMIT-1):]) if isinstance(history,list) else []
    history.append({'request':copy.deepcopy(request),'resolution':copy.deepcopy(resolution)})
    entry.update(last_input=copy.deepcopy(request),input_resolution=resolution,input_history=history)

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
            old_pending=entry.get('pending');old_request=copy.deepcopy(entry.get('input_request'))
            entry.update(fields,status=status,updated_at=korea_now().isoformat(timespec='milliseconds'))
            pending=entry.get('pending');phase=None
            if old_pending:
                # Legacy pending inputs have no knowable request date/version.
                # Never replace an existing origin even when a recheck names it again.
                if isinstance(old_request,dict):entry['input_request']=old_request
                else:entry.pop('input_request',None)
                if not pending:
                    request=old_request if isinstance(old_request,dict) else {'action':old_pending,'origin':'legacy_unknown'}
                    archive_input(entry,request,status,VERSION,source=fields.get('resolution_source'),
                                  manual_resolution=fields.get('manual_resolution'),
                                  retry_authorized=fields.get('retry_authorized',False))
                    entry.pop('input_request',None);phase='resolved'
            elif pending:
                entry['input_request']=new_input_request(pending,VERSION);phase='requested'
                # These explain a prior resolution, never the newly dispatched input.
                for key in ('retry_authorized','resolution_source','manual_resolution'):entry.pop(key,None)
            if not phase and status=='done' and isinstance(fields.get('completion_evidence'),dict):
                phase='completed'
            details[step]=entry
            changes=dict(values or {});changes['_steps']=details
            self.update(ident,task,changes,day)
            callback=getattr(self,'on_input_evidence',None)
            if phase and callback:callback(phase,task,step,copy.deepcopy(entry))
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
            tmp=self.path.with_suffix('.tmp')
            try:
                self.path.parent.mkdir(parents=True,exist_ok=True)
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

class ManualQuestLedger(DailyLedger):
    """One explicit run, independent of calendar dates; unresolved inputs survive."""
    manual=True
    def get(self,ident,task,step='_complete',day=None):
        return super().get(ident,task,step,'manual')
    def snapshot(self,ident,day=None):return super().snapshot(ident,'manual')
    def update(self,ident,task,values,day=None):
        return super().update(ident,task,values,'manual')
    def begin_run(self,ident,legacy_path=None):
        with self.lock:
            prior=self.snapshot(ident)
            if ident not in self.data and legacy_path and Path(legacy_path).exists():
                legacy=DailyLedger(legacy_path)
                for day in sorted(legacy.data.get(ident,{})):
                    for task,entry in legacy.snapshot(ident,day).items():
                        if task in DAILY_TASKS:prior[task]=entry
            fresh={}
            for task in DAILY_TASKS:
                old=prior.get(task,{})
                details=old.get('_steps',{})
                pending={step:copy.deepcopy(info) for step,info in details.items()
                         if isinstance(info,dict) and info.get('pending')}
                for info in pending.values():info.update(failures=0,fingerprint='',status='uncertain')
                # A new explicit run resets work, not the provenance of past inputs.
                for step,info in details.items():
                    if step not in pending and isinstance(info,dict):
                        archive={key:copy.deepcopy(info[key]) for key in INPUT_ARCHIVE_FIELDS if key in info}
                        if archive:pending[step]=archive
                entry={'_steps':pending}
                if pending.get('donation',{}).get('pending'):
                    for key in ('donation_paid','donation_verified'):
                        if key in old:entry[key]=old[key]
                if old.get('raid')=='started':entry['raid']='started'
                fresh[task]=entry
            data=copy.deepcopy(self.data);data[ident]={'manual':fresh}
            tmp=self.path.with_suffix('.tmp')
            try:
                self.path.parent.mkdir(parents=True,exist_ok=True)
                tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(self.path)
            except OSError as exc:raise LedgerError('일일 퀘스트 실행 기록 저장 실패: '+str(exc)) from exc
            self.data=data
