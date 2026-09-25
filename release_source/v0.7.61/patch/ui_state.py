"""Read-only UI summaries. Displayed success always comes from recorded results."""
from datetime import datetime,timedelta,timezone
from task_catalog import TASK_LABELS,REGULAR_LABELS,DAILY_LABELS
from vision import LABELS
from history import RESULTS,ISSUES



def selected_tasks(player):
    selected=player.get('selected')
    if not isinstance(selected,dict):selected={key:True for key in LABELS}
    return [key for key in REGULAR_LABELS if selected.get(key,False)]


def retry_tasks(player,entries,requested=None):
    allowed=set(requested) if requested is not None else set(TASK_LABELS)
    return [task for task in [*selected_tasks(player), *DAILY_LABELS]
            if task in allowed and entries.get(task,{}).get('result') in ISSUES]


def task_display_order(player,entries,show_disabled=False):
    """Prioritize unresolved records without changing selection or execution order."""
    selected=set(selected_tasks(player)) | {task for task in DAILY_LABELS if entries.get(task)}
    visible=[task for task in TASK_LABELS if task in selected or (show_disabled and task in REGULAR_LABELS)]
    return sorted(visible,key=lambda task: 2 if entries.get(task,{}).get('previous') else 0 if entries.get(task,{}).get('result') in ISSUES else 1)


def remaining_text(due, now):
    if due is None:
        return '예약 없음'
    seconds = max(0, int(due-now))
    if seconds == 0:
        return '곧 시작'
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes:02d}:{seconds:02d}'


def short_time(value):
    try:
        stamp=datetime.fromisoformat(value)
        if stamp.tzinfo is not None:stamp=stamp.astimezone(timezone(timedelta(hours=9)))
        return stamp.strftime('%m/%d %H:%M')
    except (ValueError, TypeError):
        return '기록 없음'


def task_summary(task, result):
    from daily_state import DAILY_TASKS,DAILY_ALREADY
    if result=='unavailable':return '이벤트 없음','muted'
    if task=='autumn' and result=='skipped':return '수령 대기','muted'
    if result in {"already_complete","already_claimed","no_entries"}:return RESULTS[result], "success"
    if task in DAILY_TASKS and result in {'collected','skipped'}:
        return ('일일 완료' if result=='collected' else RESULTS[DAILY_ALREADY[task]]), 'success'
    if result == 'collected':
        return ('수련 완료' if task == 'training' else '수령 완료'), 'success'
    if result == 'skipped':
        return ('조건 미충족' if task == 'training' else '받을 보상 없음'), 'muted'
    if result == 'failed':
        return '확인 필요', 'error'
    if result == 'deferred':return '자동 재시도 보류', 'warning'
    if result in {'attempted', 'unrecognized'}:
        return '완료 미확인', 'warning'
    return '기록 없음', 'muted'

def daily_step_summary(task,record):
    from daily_state import DAILY_STEPS,step_label
    if task not in DAILY_STEPS:return ''
    details=record.get('_steps',{})
    if not isinstance(details,dict):details={}
    labels={'running':'진행 중 또는 중단됨','failed':'확인 필요','blocked':'재시도 보류','uncertain':'결과 미확인'}
    items=[];complete=0
    for step in DAILY_STEPS[task]:
        info=details.get(step,{})
        if not isinstance(info,dict):info={}
        done=record.get(step)=='done' or record.get('_complete')=='done'
        complete+=int(done)
        proof=info.get('completion_evidence',{})
        verified_empty=isinstance(proof,dict) and proof.get('kind')=='no_entries' and proof.get('revision')==1
        status=('입장 횟수 없음 확인' if verified_empty else '완료') if done else labels.get(info.get('status'),'미실행')
        items.append(step_label(task,step)+': '+status)
    return f"최근 실행 {complete}/{len(DAILY_STEPS[task])} 완료\n"+' / '.join(items)


def player_summary(player, state, connected, busy, paused, now):
    tasks = selected_tasks(player)
    results = state.get('results', {})
    issue = bool(state.get('history_issue')) or state.get('status') == '확인 필요' or any(value in ISSUES for value in results.values())
    enabled = bool(player.get('enabled'))
    status, tone = '대기', 'muted'
    if not connected:
        status, tone = '연결 미확인', 'warning'
    elif paused and busy and enabled:
        status, tone = '일시중지', 'warning'
    elif busy and state.get('status') in {'수령 중', '재시도 중'}:
        status, tone = state['status'], 'active'
    elif issue:
        status, tone = '확인 필요', 'error'
    elif not enabled:
        status = '제외됨'
    elif busy and state.get('next_at') is not None:
        status, tone = '예약 대기', 'success'
    elif state.get('status') == '확인 완료':
        status, tone = '확인 완료', 'success'
    elif state.get('status') == '중지됨':
        status = '중지됨'
    cycle = state.get('rooms', tasks)
    completed = sum(room in results for room in cycle)
    phase = state.get('phase', '') if busy and state.get('status') in {'수령 중','재시도 중'} else ''
    if not phase:
        phase = f'{len(tasks)}개 작업 / {player.get("minutes",60):g}분 간격' if isinstance(player.get('minutes',60),(int,float)) else f'{len(tasks)}개 작업 / {player.get("minutes",60)}분 간격'
    next_text = '일시중지' if paused and busy and enabled else remaining_text(state.get('next_at'), now)
    return {'status':status,'tone':tone,'phase':phase,'next':next_text,'issue':issue,
            'completed':completed,'total':len(cycle),'enabled':enabled,'connected':connected}


def visible_players(players, summaries, query='', mode='전체'):
    query = query.strip().casefold()
    return [ident for ident, player in players.items()
            if query in player.get('name','뮤뮤').casefold()
            and (mode != '실행 대상' or player.get('enabled'))
            and (mode != '확인 필요' or summaries[ident]['issue'] or not summaries[ident]['connected'])]


def validate_profile(values):
    minutes = float(values['minutes'])
    if not 1 <= minutes <= 1440:
        raise ValueError('수령 간격은 1~1440분으로 입력해 주세요.')
    selected = {key:bool(values['selected'].get(key,False)) for key in REGULAR_LABELS}
    from action_state import normalize_account
    from session_workflow import selected_daily
    daily={t:t in selected_daily(values) for t in DAILY_LABELS}
    return {'enabled':bool(values['enabled']),'minutes':minutes,'selected':selected,
            'restore_sleep':True,'daily_selected':daily,'daily_profile':normalize_account(values.get('daily_profile',''))}


def entry_summary(task,entry):
    if entry.get('previous'):return '이전 기록','muted'
    if entry.get('result')=='waiting':return '이번 실행 대기','muted'
    progress=entry.get('progress',{})
    if isinstance(progress,dict):
        complete=progress.get('complete',0);total=progress.get('total',0);excluded=progress.get('excluded',0)
        if all(type(n) is int for n in (complete,total,excluded)) and total>0:
            if excluded==total:return '유료 항목 제외','muted'
            if 0<complete<total:return f'부분 완료 {complete}/{total}','warning'
            if complete==total and excluded:return '무료 작업 완료','success'
            if complete<total and progress.get('free_keys',0):return '열쇠 수령 / 미완료','warning'
    if task=='daily_dungeons' and entry.get('result')=='collected':return '던전 완료','success'
    if task=='daily_guild' and entry.get('result')=='collected':return '길드 완료','success'
    return task_summary(task,entry.get('result'))


def connection_summary(reports):
    from adb_device import READY_STATES
    connected=len(reports)
    ready=sum(r.get('image') is not None and r.get('state') in READY_STATES and bool(r.get('package')) and not r.get('package_error') for r in reports.values())
    if not connected:return '뮤뮤 연결을 확인해 주세요.'
    if ready==connected:return f'뮤뮤 {connected}개 연결됨 / 실행 준비 완료'
    return f'뮤뮤 {connected}개 연결됨 / 게임 화면 확인 필요 {connected-ready}개'


def execution_summary(states,stopped=False):
    from history import ISSUES
    results=[value for state in states.values() for value in state.get('results',{}).values()]
    confirmed=sum(value=='collected' for value in results)
    checked=sum(value in {'skipped','already_complete','already_claimed','no_entries','unavailable'} for value in results)
    issues=sum(value in ISSUES for value in results)
    missing=sum(sum(task not in state.get('results',{}) for task in state.get('rooms',[])) for state in states.values())
    return f"{'중지됨' if stopped else '실행 종료'} / 수행 확인 {confirmed}건 / 소진 또는 제외 {checked}건 / 확인 필요 {issues+missing}건"
