"""Fresh recognition immediately before every protected touch."""
from collector import Halt,ScreenChanged
from run_control import checkpoint,RunControl,ResumeRecognition


def verified_tap(collector, screen, name=None, point=None, *, before_input=None,
                 validate=None, action=None, required=()):
    checkpoint(collector.stop)
    if collector.stop.is_set():raise Halt('사용자가 중지했습니다.')
    if validate:validate()
    fresh=collector.screen()
    # Only unreadable transition frames may be re-observed here. A recognized
    # different page, changed button or counter goes back to the route decision.
    if fresh.state=='unknown' and screen.state not in {'unknown','daily_battle','daily_result','daily_clear','reward','equipment','offline_reward'}:
        recovered=0
        for _ in range(6):
            collector.pause(.2)
            if validate:validate()
            fresh=collector.screen()
            if fresh.state not in {'unknown',screen.state}:break
            matches=(fresh.state==screen.state and (not name or name in fresh.matches)
                     and all(k in fresh.matches for k in required))
            recovered=recovered+1 if matches else 0
            if recovered>=2:break
            if fresh.state==screen.state and not matches:break
        if recovered<2:
            raise ScreenChanged('일시적 화면 변화 후 재확인이 되지 않아 클릭을 보류합니다.')
        collector.trace.event('preinput_recovered',state=fresh.state)
    generation=collector.stop.generation if isinstance(collector.stop,RunControl) else None
    if validate:validate()
    same_room=action=='leave_room' and any(collector.room_visible(screen,r) and collector.room_visible(fresh,r) for r in ('farm','wood','mine'))
    if fresh.state!=screen.state and not same_room:
        raise ScreenChanged('화면이 바뀌어 클릭을 보류합니다.')
    if any(k not in old.matches for old in (screen,fresh) for k in required):
        raise ScreenChanged('진입 기준 아이콘이 바뀌어 클릭을 보류합니다.')
    if name:
        if name not in screen.matches or name not in fresh.matches:
            raise ScreenChanged('버튼 상태가 바뀌어 클릭을 보류합니다: '+name)
        opposites=(['empty_'+name[6:]] if name.startswith('ready_') else
                   [name[:-7]+'_empty',name[:-7]+'_done'] if name.endswith('_active') else [])
        if any(other in observed.matches for other in opposites for observed in (screen,fresh)):
            raise Halt('버튼 판정이 서로 달라 클릭을 보류합니다: '+name)
        point=fresh.matches[name].center
    if point is None:raise Halt('클릭 위치를 확인하지 못했습니다.')
    if before_input:before_input()
    collector.trace.frame(collector.last_image,fresh)
    collector.trace.event('input',action=action or name or 'navigation',point=list(point),before=fresh.state)
    if validate:validate()
    checkpoint(collector.stop)
    if collector.stop.is_set():raise Halt('사용자가 중지했습니다.')
    if generation is not None and generation!=collector.stop.generation:raise ResumeRecognition()
    collector.forget_observations()
    collector.device.click(point)
    return fresh
