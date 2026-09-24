"""Read-only account/day-scoped continuation and current-run presentation."""
from pathlib import Path
from daily_state import DAILY_TASKS,DAILY_STEPS,ManualQuestLedger,korea_day
from action_state import ActionState,account_scope
from history import TERMINAL_RESULTS
from run_journal import RunJournal
from ui_state import selected_tasks


def selected_daily(player):
    selected=player.get('daily_selected')
    return [task for task in DAILY_TASKS if not isinstance(selected,dict) or selected.get(task,False)]


def task_scope(player,scope='regular',repeat=False):
    if repeat:return selected_tasks(player) if scope!='daily' else []
    return ([*selected_tasks(player),*selected_daily(player)] if scope=='all' else
            selected_daily(player) if scope=='daily' else selected_tasks(player))


def held_reason(task,result,actions,records):
    if task in DAILY_STEPS:
        details=records.get(task,{}).get('_steps',{})
        if any(d.get('pending') or d.get('status')=='uncertain' for d in details.values()):
            return '입력 후 결과 미확인 / 중복 실행 보류'
        if any(d.get('status')=='blocked' for d in details.values()):return '반복 실패 / 기록 확인 필요'
    else:
        if actions.get(task).get('pending'):return '입력 후 결과 미확인 / 중복 실행 보류'
        if actions.blocked(task):return '반복 실패 / 기록 확인 필요'
    if result in {'attempted','deferred'}:return '이전 결과 미확인 또는 보류 / 기록 확인 필요'
    return ''


def continuation(data,players,day=None):
    data=Path(data);day=day or korea_day();journal=RunJournal(data/'run_progress.json')
    ledger=ManualQuestLedger(data/'daily_manual.json');targets={};safe=[];held=[];records={}
    for ident,p in players.items():
        scope=account_scope(ident,p.get('daily_profile',''));record=journal.data.get(scope,{})
        if record.get('day')==day:records[ident]=record
        if not p.get('enabled'):continue
        allowed=set(task_scope(p,'all'));actions=ActionState(data/'action_state.json',scope)
        daily=ledger.snapshot(scope,day)
        for task in journal.remaining(scope,day):
            if task not in allowed:continue
            reason=held_reason(task,record['results'].get(task),actions,daily)
            item={'id':ident,'name':p.get('name','뮤뮤'),'task':task,'reason':reason or '현재 화면을 확인한 뒤 이어갑니다.'}
            (held if reason else safe).append(item)
            if not reason:targets.setdefault(ident,[]).append(task)
    return {'targets':targets,'safe':safe,'held':held,'records':records,'day':day}


def session_entry(task,record,previous):
    if task not in record.get('tasks',[]):return {**previous,'previous':True}
    result=record.get('results',{}).get(task)
    if result is None:return {'result':'waiting','reason':'이번 실행에서 아직 확인하지 않은 작업입니다.'}
    return {**record.get('entries',{}).get(task,{}),'result':result}
