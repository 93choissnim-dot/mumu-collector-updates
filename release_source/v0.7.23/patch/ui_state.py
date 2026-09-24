"""Read-only UI summaries. Displayed success always comes from recorded results."""
from datetime import datetime
from task_catalog import TASK_LABELS
from vision import LABELS
from history import RESULTS,ISSUES



def selected_tasks(player):
    selected=player.get('selected')
    if not isinstance(selected,dict):selected={key:True for key in LABELS}
    return [key for key in TASK_LABELS if selected.get(key,False)]


def retry_tasks(player,entries,requested=None):
    allowed=set(requested) if requested is not None else set(TASK_LABELS)
    return [task for task in selected_tasks(player)
            if task in allowed and entries.get(task,{}).get('result') in ISSUES]


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
        return datetime.fromisoformat(value).strftime('%m/%d %H:%M')
    except (ValueError, TypeError):
        return '기록 없음'


def task_summary(task, result):
    from daily_state import DAILY_TASKS,DAILY_ALREADY
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
        status='완료' if done else labels.get(info.get('status'),'미실행')
        items.append(step_label(task,step)+': '+status)
    return f"오늘 {complete}/{len(DAILY_STEPS[task])} 완료\n"+' / '.join(items)


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
    from daily_state import DAILY_TASKS
    daily_count=sum(t in DAILY_TASKS for t in tasks)
    if daily_count and not (busy and state.get('status') in {'수령 중','재시도 중'}):
        phase=(f'매일 {daily_count}개 / KST 00:00 초기화' if daily_count==len(tasks) else phase+f' / 일일 {daily_count}개')
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
    selected = {key:bool(values['selected'].get(key,False)) for key in TASK_LABELS}
    if values['enabled'] and not any(selected.values()):
        raise ValueError('실행할 작업을 하나 이상 선택해 주세요. 전체 해제 상태로 저장하려면 실행 대상에서 제외해 주세요.')
    return {'enabled':bool(values['enabled']),'minutes':minutes,'selected':selected,
            'restore_sleep':True}
