"""Read-only reports from existing account-scoped records; never authorize inputs."""
from datetime import datetime
from action_state import account_scope
from daily_state import DAILY_STEPS,korea_day,step_label
from history import TERMINAL_RESULTS,history_day,KST
from session_workflow import task_scope
from task_catalog import TASK_LABELS

STATUS_LABELS={'waiting':'시즌 정산 대기','unrun':'미실행','partial':'일부 진행','uncertain':'결과 미확인',
               'held':'재시도 보류','done':'오늘 확인 완료','prior':'오늘 이전 기록 / 계정 구분 미확인'}


def _on_day(stamp,day):
    if not isinstance(stamp,str):return False
    try:return history_day(stamp)==day
    except (ValueError,TypeError):return False


def pending_reason(task,pending):
    """Explain retained requests; this display never grants retry permission."""
    if not isinstance(pending,dict) or not pending:return ''
    lines=[]
    for slot,info in pending.items():
        info=info if isinstance(info,dict) else {}
        request=info.get('input_request',info)
        request=request if isinstance(request,dict) else {}
        stamp=request.get('requested_at')
        if not stamp:since='요청 시각 기록 없음'
        else:
            try:
                when=datetime.fromisoformat(stamp)
                if when.tzinfo is None:when=when.replace(tzinfo=KST)
                since=when.astimezone(KST).strftime('%Y-%m-%d %H:%M KST')+'부터 미확인'
            except (TypeError,ValueError,OverflowError):since='요청 시각 확인 불가'
        name=step_label(task,slot)
        if slot=='claim':name='수령'
        elif task=='worldboss':name={'cerberus':'켈베로스','kraken':'크라켄','void':'공허의 지배자'}.get(slot,name)
        version=f" / 요청 버전 {request['version']}" if request.get('version') else ''
        lines.append(f"{TASK_LABELS.get(task,task)} / {name}: {since}{version}")
    lines.append('게임 화면에서 해당 작업의 완료 또는 수령 상태를 확인하세요. 미확인 동안 중복 입력을 보류합니다. 판단이 어려우면 진단 파일과 함께 확인을 요청하세요.')
    return '\n'.join(lines)


def donation_report(record,day=None):
    """Count only retained, dated request/evidence pairs, never attempted counters.

    A final badge seen on a later recheck proves completion, not which payment
    caused it. Only explicit settlement sources from the original input count.
    The bounded archive is a lower bound, not the day's complete spend ledger.
    """
    day=day or korea_day();detail=record.get('_steps',{}).get('donation',{})
    history=detail.get('input_history',[])
    pairs=list(history) if isinstance(history,list) else []
    if isinstance(detail.get('last_input'),dict) and isinstance(detail.get('input_resolution'),dict):
        pairs.append({'request':detail['last_input'],'resolution':detail['input_resolution']})
    seen=set();verified=[];paid=free=0
    for pair in pairs:
        if not isinstance(pair,dict):continue
        request=pair.get('request',{});resolution=pair.get('resolution',{})
        if not isinstance(request,dict) or not isinstance(resolution,dict):continue
        ident=request.get('id')
        if not isinstance(ident,str) or not ident or ident in seen:continue
        seen.add(ident)
        if (resolution.get('confirmed') is not True or resolution.get('kind')!='confirmed'
            or resolution.get('source') not in {'donation_counter_changed','guild_donated'}
            or not _on_day(request.get('requested_at'),day) or not _on_day(resolution.get('at'),day)):
            continue
        action=request.get('action')
        if action not in {'donate_free','donate_50'}:continue
        paid+=int(action=='donate_50');free+=int(action=='donate_free')
        verified.append({'action':action,'at':resolution['at'],'source':resolution['source']})
    pending=detail.get('pending')
    return {'paid_confirmed':paid,'free_confirmed':free,'ruby_confirmed':paid*50,
            'verified':verified,'pending':pending,'request':detail.get('input_request',{}),
            'completed':(record.get('donation')=='done' or detail.get('status')=='done') and _on_day(detail.get('updated_at'),day),'day':day}


def donation_lines(report):
    text=(f"루비 기부: 확인 {report['paid_confirmed']}회 / 빨간 루비 {report['ruby_confirmed']}개\n"
          f"무료 기부: 확인 {report['free_confirmed']}회 / 보관 기록 중 오늘 확인된 최소 내역")
    if report['pending']:
        request=report['request'] if isinstance(report['request'],dict) else {}
        name='루비 50' if report['pending']=='donate_50' else '무료' if report['pending']=='donate_free' else '기부'
        text+=f"\n결과 미확인: {name} 입력 요청 / {request.get('requested_at') or '요청 시각 기록 없음'}"
    if report['completed']:text+='\n기부 완료 표시는 확인됨 / 이 표시만으로 사용량을 계산하지 않습니다.'
    return text


def account_overview(ident,player,record,daily,actions,day=None,history=None):
    day=day or korea_day();current=record if record.get('day')==day else {}
    selected=set(task_scope(player,'all'));rows=[]
    for task in TASK_LABELS:
        saved=daily.get(task,{}) if task in DAILY_STEPS else {}
        details=saved.get('_steps',{});details=details if isinstance(details,dict) else {}
        action=actions.get(task,{})
        pending={step:info for step,info in details.items() if isinstance(info,dict) and info.get('pending')}
        if task not in DAILY_STEPS and action.get('pending'):pending=action['pending']
        uncertain=bool(pending) or any(isinstance(info,dict) and info.get('status')=='uncertain'
            and info.get('input_resolution',{}).get('kind')!='retry_authorized' for info in details.values())
        blocked=bool(action.get('blocked')) or any(isinstance(info,dict) and info.get('status')=='blocked' for info in details.values())
        if task not in selected and not uncertain and not blocked:continue
        entry=record.get('entries',{}).get(task,{})
        # A run may cross KST midnight. Dated outcomes belong to their actual
        # completion day; the journal start day remains the resume boundary.
        stamp=entry.get('checked_at')
        dated=_on_day(stamp,day)
        task_current=dated or (not stamp and bool(current))
        result=record.get('results',{}).get(task) if task_current else None
        reason=entry.get('reason','') if task_current else ''
        complete=sum(saved.get(step)=='done' and _on_day(details.get(step,{}).get('updated_at'),day)
                     for step in DAILY_STEPS.get(task,()))
        total=len(DAILY_STEPS.get(task,()))
        excluded=sum(info.get('excluded') is True and _on_day(info.get('updated_at'),day)
                     for info in details.values() if isinstance(info,dict))
        started=any(isinstance(info,dict) and info.get('status') and _on_day(info.get('updated_at'),day)
                    for info in details.values())
        if result=='waiting' and '시즌' in reason:status='waiting'
        elif uncertain or result=='attempted':status='uncertain'
        elif blocked or result=='deferred':status='held'
        elif result in TERMINAL_RESULTS or (total and complete==total):status='done'
        elif result or complete or started:status='partial'
        elif task not in current.get('tasks',[]) and _on_day((history or {}).get(task,{}).get('checked_at'),day):status='prior'
        else:status='unrun'
        guidance=pending_reason(task,pending)
        if guidance and guidance not in reason:reason='\n'.join(filter(None,(reason,guidance)))
        rows.append({'task':task,'status':status,'selected':task in selected,
                     'complete':complete,'total':total,'excluded':excluded,'pending':pending,
                     'reason':reason})
    counts={status:sum(row['status']==status for row in rows) for status in STATUS_LABELS}
    return {'id':ident,'name':player.get('name','뮤뮤'),'profile':player.get('daily_profile',''),
            'enabled':bool(player.get('enabled')),'tasks':rows,'counts':counts,
            'donation':donation_report(daily.get('daily_guild',{}),day)}


def build_overview(players,journal,manual,actions,day=None,histories=None):
    day=day or korea_day();accounts=[]
    for ident,player in players.items():
        scope=account_scope(ident,player.get('daily_profile',''))
        daily=manual.get(scope,{}).get('manual',{})
        accounts.append(account_overview(ident,player,journal.get(scope,{}),daily,actions.get(scope,{}),day,(histories or {}).get(ident,{})))
    return {'day':day,'accounts':accounts}
