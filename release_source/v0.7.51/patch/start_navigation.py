"""Bounded start-only recovery; never send another Back on a usable menu."""


def prepare_start(collector):
    from collector import Halt,ScreenChanged

    c = collector
    deadline = c.now() + 45
    last, seen, since = None, 0, c.now()
    backs, wakes, cancels = 0, 0, 0
    overlays = {}
    while c.now() < deadline:
        screen = c.screen()
        key = screen.state
        seen = seen + 1 if key == last else 1
        if key != last:
            since = c.now()
        last = key
        if seen < 2:
            c.pause(.25)
            continue

        # Modal priority is enforced in Vision. A partial exit match blocks
        # input until the title and BOTH buttons are independently recognized.
        if key == 'exit_dialog':
            if not all(k in screen.matches for k in ('exit_title', 'exit_cancel', 'exit_confirm')):
                c.pause(.25)
                continue
            if cancels >= 3:
                raise Halt('게임 종료창 취소를 3회 시도했지만 닫히지 않았습니다.')
            c.progress(f'게임 종료 확인창 → 취소 ({cancels+1}/3)')
            try:
                fresh=c.tap(screen,'exit_cancel',required=('exit_title','exit_cancel','exit_confirm'))
                c.post_input(fresh,'exit_cancel',delay=.6)
            except ScreenChanged:
                c.forget_observations()
            else:cancels += 1
        elif key in {'main', 'menu'}:
            c.log('시작 화면 확인 / 오른쪽 메뉴 바로 사용' if key == 'menu' else '시작 화면 복귀 확인')
            return screen
        elif key == 'sleep':
            if wakes >= c.WAKE_ATTEMPTS:
                raise Halt('절전 해제를 3회 시도했지만 절전 화면이 그대로입니다.')
            wakes += 1
            c.wake_attempts = wakes
            c.progress(f'절전 해제: 손잡이를 오른쪽 끝까지 이동 ({wakes}/{c.WAKE_ATTEMPTS})')
            c.forget_observations()
            c.device.drag(c.SLEEP_START, c.SLEEP_END)
            c.pause(.6)
        elif c.dismiss_overlay(screen, overlays):
            # Preserve proven reward/equipment dismissal. Always recapture.
            c.pause(.25)
            continue
        elif any(c.room_visible(screen,room) for room in ('farm','wood','mine')):
            room=next(room for room in ('farm','wood','mine') if c.room_visible(screen,room))
            # A known facility has a verified back arrow. ESC can open the
            # game's exit prompt instead of navigating out of the facility.
            return c.leave_room(room,screen)
        else:
            # Let animations/transitions settle before one Escape-equivalent
            # input. Each input needs new frames; never blindly send a burst.
            if c.now() - since < 1.0:
                c.pause(.25)
                continue
            if backs >= 6:
                raise Halt('초기화면 복귀를 6회 시도했지만 메뉴가 확인되지 않았습니다.')
            if not callable(getattr(c.device, 'back', None)):
                raise Halt('이 연결 방식에서 ESC 복귀를 지원하지 않습니다.')
            backs += 1
            c.progress(f'시작 화면 정리: ESC로 창 닫기 ({backs}/6)')
            c.forget_observations()
            c.device.back()
            c.pause(.8)
        last, seen, since = None, 0, c.now()
    raise Halt('시작 화면 복귀 시간 초과 / 초기화면 또는 오른쪽 메뉴를 확인해 주세요.')
