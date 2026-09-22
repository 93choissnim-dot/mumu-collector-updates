"""Skip confirmed empty rooms; retry unresolved claims and navigation within limits."""
import time
from time import perf_counter
from run_control import RunControl, checkpoint
from vision import LABELS, state_label
from observation_window import ObservationWindow


class Halt(Exception):
    pass


class ScreenChanged(Halt):
    """A fresh capture changed before input; no input was sent."""


class Collector(ObservationWindow):
    ENTRY_ATTEMPTS = 3
    ENTRY_MENU_GRACE = 2.0
    CLAIM_ATTEMPTS = 3
    BACK_ATTEMPTS = 3
    WAKE_ATTEMPTS = 3
    BUTTON_CHECKS = 3
    SLEEP_START = (412, 469)
    SLEEP_END = (600, 469)

    def __init__(self, device, vision, stop_event, log, on_frame=None, on_progress=None, on_result=None, on_issue=None):
        self.device, self.vision = device, vision
        self.stop, self.log = stop_event, log
        self.on_frame, self.on_progress = on_frame, on_progress
        self.on_result = on_result
        self.on_issue = on_issue
        self.last_image, self.last_screen = None, None
        self.phase = "게임 화면 확인"
        self.last_preview_at = 0
        self.results, self.claim_counts = {}, {}
        self.wake_attempts = 0
        from execution_trace import ExecutionTrace
        self.trace = ExecutionTrace()
        from action_state import ActionState
        self.action_state=ActionState()

    def progress(self, text):
        self.phase = text
        self.trace.event('progress',text=text)
        self.log(text)
        if self.on_progress:
            self.on_progress(text)

    def now(self):
        return self.stop.clock() if isinstance(self.stop, RunControl) else time.monotonic()

    def pause(self, seconds):
        started=self.now()
        if self.stop.wait(seconds):
            raise Halt("사용자가 중지했습니다.")
        self.trace.timing['wait_seconds']=self.trace.timing.get('wait_seconds',0.)+max(0,self.now()-started)

    def screen(self):
        checkpoint(self.stop)
        if self.stop.is_set():
            raise Halt("사용자가 중지했습니다.")
        started=perf_counter()
        generation=getattr(self.stop,'generation',None)
        image = self.device.capture()
        captured=perf_counter()
        screen = self.vision.recognize(image)
        self.trace.observe(image,screen,captured-started,perf_counter()-captured)
        now = self.now()
        changed = self.last_screen is None or screen.state != self.last_screen.state
        self.last_image, self.last_screen = image, screen
        self.remember_observation(screen,generation)
        if self.on_frame and (changed or now-self.last_preview_at >= 1):
            self.on_frame(image, screen)
            self.last_preview_at = now
        return screen

    def dismiss_overlay(self, screen, tracking):
        # Confirm the same modal on consecutive captures before any input.
        kind = screen.state if screen.state == "equipment" or (
            screen.state == "reward" and "reward_close" in screen.matches) or (
            screen.state == "offline_reward" and "offline_confirm" in screen.matches) else None
        tracking["seen"] = tracking.get("seen", 0)+1 if kind and tracking.get("kind") == kind else int(kind is not None)
        tracking["kind"] = kind
        if kind is None:
            return False
        if tracking["seen"] < 2:
            return True
        # Each type has its own budget: an offline reward can cover equipment.
        attempts = tracking.setdefault("attempts_by_kind", {})
        attempt = attempts.get(kind, 0)+1
        if attempt > 3:
            raise Halt(state_label(kind)+": 닫기 3회 후에도 화면이 남아 있습니다. 연결과 수령 기록은 유지됩니다.")
        if self.stop.is_set():
            raise Halt("사용자가 중지했습니다.")
        if kind == "offline_reward":
            point = screen.matches["offline_confirm"].center
            self.log(f"오프라인 보상: 확인 누르기 ({attempt}/3)")
        else:
            # Recorded safe points outside equipment cards / the reward band.
            point = (940, 350) if kind == "equipment" else (640, 520)
            self.log(f"{state_label(kind)}: 빈 공간 눌러 닫기 ({attempt}/3)")
        try:
            self.tap(screen,point=point,action="dismiss_"+kind)
        except ScreenChanged:
            # A transient overlay vanished before input. Nothing was sent;
            # observe again instead of failing the entire collection cycle.
            tracking['seen']=0
            self.forget_observations()
            return True
        attempts[kind] = attempt
        self.pause(.6)
        tracking["seen"] = 0
        # The caller must capture again and verify dismissal before proceeding.
        return True

    def wait_for(self, states, timeout=20):
        self.trace.expected=sorted(states)
        deadline = self.now() + timeout
        last,count,screen=self.confirmation_seed(lambda s:s.state if s.state in states else None)
        if count>=2:return screen
        overlays = {}
        while self.now() < deadline:
            screen = self.screen()
            if self.dismiss_overlay(screen, overlays):
                last, count = None, 0
                self.pause(.25)
                continue
            if screen.state in states:
                count = count+1 if last == screen.state else 1
                if count >= 2:
                    return screen
            else:
                count = 0
            last = screen.state
            self.pause(.25)
        expected = ", ".join(state_label(state) for state in sorted(states))
        raise Halt(f"{self.phase}: 화면 확인 시간 초과 / 대기: {expected} / 마지막: {state_label(last or 'unknown')}")

    def tap(self,screen,name=None,point=None,**kwargs):
        from input_safety import verified_tap
        return verified_tap(self,screen,name,point,**kwargs)

    def top_bar_tap(self,screen,key,*,validate=None):
        if screen.state not in {'main','menu'}:raise Halt('상단 메뉴 진입 전 기본 화면 확인이 필요합니다.')
        marker='top_'+key
        deadline=self.now()+5
        while marker not in screen.matches:
            if self.now()>=deadline:raise Halt('상단 아이콘을 확인하지 못해 진입을 보류합니다: '+key)
            self.pause(.25);fresh=self.screen()
            if fresh.state!=screen.state:raise Halt('상단 메뉴 확인 중 화면이 바뀌었습니다.')
            screen=fresh
        fresh=self.tap(screen,marker,validate=validate,action='open_'+key)
        self.post_input(fresh,marker,delay=.6)

    def click_match(self, state, name, screen=None, *, before_input=None):
        if screen is None or screen is not self.last_screen:
            screen = self.wait_for({state})
        if screen.state != state or name not in screen.matches:
            raise Halt("버튼을 인식하지 못했습니다: " + name)
        fresh=self.tap(screen,name,before_input=before_input)
        self.post_input(fresh,name,delay=.6)

    @staticmethod
    def room_visible(screen, room):
        if screen.state in {room+s for s in ("_ready", "_empty", "_wait")}:
            return True
        # During a known room visit, the resource-specific claim text is enough
        # even when the separate production label is temporarily unreadable.
        # Never accept a reward overlay or a recognized different facility.
        return (screen.state == "unknown"
                and any(kind+room in screen.matches for kind in ("ready_", "empty_"))
                and not any("room_"+other in screen.matches for other in LABELS if other != room))

    @staticmethod
    def claim_button(screen, room):
        return next((kind+room for kind in ("ready_", "empty_") if kind+room in screen.matches), None)

    def wait_for_room(self, room, *, allow_exit=False, require_button=False, entry=False, timeout=20, reuse=True):
        deadline = self.now() + timeout
        last_key, count, last_state = None, 0, "unknown"
        def observed(s):
            if self.room_visible(s,room) and (not require_button or self.claim_button(s,room)):return room
            if allow_exit and s.state in {'main','menu'}:return s.state
        if reuse:
            last_key,count,screen=self.confirmation_seed(observed)
            if count>=2 and not (entry and last_key in {'main','menu'}):return screen
        key_since = self.now()
        overlays = {}
        while self.now() < deadline:
            screen = self.screen()
            last_state = screen.state
            if self.dismiss_overlay(screen, overlays):
                last_key, count = None, 0
                self.pause(.25)
                continue
            key = None
            if self.room_visible(screen, room) and (not require_button or self.claim_button(screen, room)):
                key = room
            elif allow_exit and screen.state in {"main", "menu"}:
                key = screen.state
            # Active, inactive and ambiguous buttons belong to the same page.
            # Their animation must not reset confirmation of the facility itself.
            count = count+1 if key is not None and key == last_key else int(key is not None)
            if count == 1:
                key_since = self.now()
            # After entry input, a menu must remain visible for a grace period
            # before another tap. Normal facility entry returns immediately.
            waiting_transition = entry and key in {"main", "menu"} and self.now()-key_since < self.ENTRY_MENU_GRACE
            if count >= 2 and not waiting_transition:
                return screen
            last_key = key
            self.pause(.25)
        raise Halt(f"{self.phase}: 화면 확인 시간 초과 / {LABELS[room]} 또는 이동 결과 확인 필요 / 마지막: {state_label(last_state)}")

    def leave_room(self, room, screen):
        for attempt in range(1, self.BACK_ATTEMPTS+1):
            if screen is not self.last_screen:
                screen = self.wait_for_room(room, allow_exit=True)
            if screen.state in {"main", "menu"}:
                return screen
            if not self.room_visible(screen, room):
                raise Halt(LABELS[room] + ": 시설 화면을 확인하지 못해 이동을 멈췄습니다.")
            self.progress(f"{LABELS[room]}: 메뉴로 돌아가기 ({attempt}/{self.BACK_ATTEMPTS})")
            if self.stop.is_set():
                raise Halt("사용자가 중지했습니다.")
            try:
                self.tap(screen,point=(34,28),action="leave_room")
            except ScreenChanged:
                self.forget_observations()
                screen=self.wait_for_room(room,allow_exit=True)
                if screen.state in {'main','menu'}:return screen
                continue
            self.pause(.6)
            screen = self.wait_for_room(room, allow_exit=True)
            if screen.state in {"main", "menu"}:
                return screen
        raise Halt(LABELS[room] + ": 뒤로가기를 3회 눌렀지만 시설 화면이 그대로입니다. 수령 기록과 연결은 유지됩니다.")

    def wake(self, screen, states):
        self.wake_attempts = 0
        for attempt in range(1, self.WAKE_ATTEMPTS+1):
            if screen is not self.last_screen:
                screen = self.wait_for(states)
            if screen.state != "sleep":
                return screen
            self.progress(f"절전 해제: 손잡이를 오른쪽 끝까지 이동 ({attempt}/{self.WAKE_ATTEMPTS})")
            if self.stop.is_set():
                raise Halt("사용자가 중지했습니다.")
            self.wake_attempts = attempt
            # Continue past the track's right edge (about x568), rather than
            # releasing near its inner end. Input is still scoped to the game.
            self.forget_observations()
            self.device.drag(self.SLEEP_START, self.SLEEP_END)
            self.pause(.6)
            screen = self.wait_for(states)
            if screen.state != "sleep":
                self.log("절전 해제 확인")
                return screen
            if attempt < self.WAKE_ATTEMPTS:
                self.log("절전 화면이 남아 있어 새 화면 확인 후 슬라이드를 다시 보냅니다.")
        raise Halt("절전 해제를 3회 시도했지만 절전 화면이 그대로입니다. 선택한 뮤뮤 주소는 유지됩니다.")

    def ensure_menu(self, screen=None, room=None):
        facilities = {r+s for r in LABELS for s in ("_ready", "_empty", "_wait")}
        states = {"sleep", "main", "menu"} | facilities
        if screen is None or screen is not self.last_screen or screen.state in {"offline_reward", "equipment", "reward"}:
            screen = self.wait_for(states)
        if screen.state == "sleep":
            screen = self.wake(screen, states)
        if screen.state in facilities:
            room = screen.state.split("_")[0]
        if room is not None and self.room_visible(screen, room):
            screen = self.leave_room(room, screen)
        if screen.state == "main":
            for _ in range(3):
                self.progress("게임 화면 확인 → 오른쪽 메뉴 자동 열기")
                try:
                    self.click_match("main", "main_menu", screen)
                except ScreenChanged:
                    self.forget_observations()
                    screen=self.wait_for({'main','menu'})
                    if screen.state=='menu':break
                    continue
                # Once dispatched, do not toggle a menu whose opening is slow.
                screen = self.wait_for({"menu"})
                break
        if screen.state != "menu":
            raise Halt("시설 메뉴가 확인되지 않아 다음 시설 이동을 멈췄습니다.")
        return screen

    def open_room(self, room, menu):
        for attempt in range(1, self.ENTRY_ATTEMPTS+1):
            self.progress(f"{LABELS[room]}: 시설 화면 열기 ({attempt}/{self.ENTRY_ATTEMPTS})")
            self.click_match("menu", "menu_"+room, menu)
            screen = self.wait_for_room(room, allow_exit=True, entry=True)
            if self.room_visible(screen, room):
                return screen
            if attempt == self.ENTRY_ATTEMPTS:
                raise Halt(LABELS[room]+": 시설 진입을 3회 시도했지만 메뉴가 그대로입니다.")
            self.log(LABELS[room]+": 메뉴가 남아 있어 시설 진입을 다시 시도합니다.")
            # Only verified main/menu frames reach here; never retry through
            # unknown pages or by reusing a previous capture's coordinates.
            menu = self.ensure_menu(screen)
        raise Halt("시설 진입 확인 실패")

    def check_claim_button(self, room, screen=None):
        # A recognized facility with an unreadable button is not an unknown
        # screen. Recheck briefly, then let its verified back navigation run.
        for check in range(1, self.BUTTON_CHECKS+1):
            if check != 1 or screen is None or screen is not self.last_screen or not self.room_visible(screen, room):
                screen = self.wait_for_room(room,reuse=check==1)
            if self.claim_button(screen, room):
                return screen
            if check < self.BUTTON_CHECKS:
                self.progress(f"{LABELS[room]}: 버튼 다시 확인 ({check+1}/{self.BUTTON_CHECKS})")
                self.pause(.4)
        return screen

    def record_task(self, task, result):
        self.results[task] = result
        if self.on_result:
            self.on_result(task, result)
        return result

    def confirm_room_empty(self,room,screen):
        def empty(s):
            return self.room_visible(s,room) and 'empty_'+room in s.matches and 'ready_'+room not in s.matches
        if not empty(screen):return screen,False
        _,count,_=self.confirmation_seed(lambda s:'empty' if empty(s) else None)
        if count>=2:return screen,True
        self.pause(.15)
        fresh=self.screen()
        return fresh,empty(fresh)

    def collect_room(self, room, screen=None):
        self.progress(LABELS[room] + ": 수령 버튼 확인 중")
        self.claim_counts[room] = max(getattr(self, 'resume_counts', {}).pop(room, 0),int(bool(self.action_state.pending(room))))
        screen = self.check_claim_button(room, screen)
        screen,initially_empty = self.confirm_room_empty(room,screen)
        empty = initially_empty
        saw_ready = self.claim_counts[room] > 0
        confirmed = saw_ready and empty
        for attempt in range(self.claim_counts[room]+1, 2):
            if empty:
                self.log(LABELS[room] + ": 비활성 버튼 확인 → 수령 클릭 생략")
                break
            button = self.claim_button(screen, room)
            if button is None:
                # The page is still confirmed, so leaving it does not depend on
                # recognizing a particular disabled-button animation.
                self.log(LABELS[room] + ": 버튼 확인이 어려워 이 시설의 클릭을 끝내고 다음 시설로 이동합니다.")
                break
            saw_ready |= "ready_"+room in screen.matches and "empty_"+room not in screen.matches
            self.progress(f"{LABELS[room]}: 수령 버튼 누르기 / 결과 확인 전 중복 입력 보류")
            def reserve():
                self.action_state.reserve(room);self.claim_counts[room]=attempt
            # ScreenChanged is raised before input: a transient stat-up effect can
            # hide the room marker. Reconfirm a fully recognized facility rather
            # than relaxing the fresh-screen guard or spending a click attempt.
            for recheck in range(3):
                try:
                    self.click_match(screen.state, button, screen, before_input=reserve)
                    break
                except ScreenChanged:
                    if self.claim_counts[room]>=attempt or recheck==2:raise
                    self.log(LABELS[room]+': 클릭 전 화면 변화 / 시설을 다시 확인합니다.')
                    self.forget_observations()
                    screen=self.wait_for({room+'_ready',room+'_empty'},timeout=5)
                    button=self.claim_button(screen,room)
                    if button!='ready_'+room:
                        if button=='empty_'+room and self.claim_counts[room]==0:initially_empty=True
                        break
            # Close verified reward overlays, then recheck the facility.
            # A transient toast alone never means the claim failed.
            screen = self.check_claim_button(room)
            screen,empty = self.confirm_room_empty(room,screen)
            confirmed |= self.claim_counts[room]>0 and empty
            if empty:
                self.log(LABELS[room] + ": 비활성 전환 확인 → 남은 재클릭 생략")
                break
            deadline=self.now()+15
            while self.claim_counts[room] and not empty and self.now()<deadline:
                self.pause(.4)
                screen=self.check_claim_button(room)
                screen,empty=self.confirm_room_empty(room,screen)
                confirmed |= empty
        if empty:self.action_state.confirm(room)
        result = "collected" if confirmed else ("skipped" if initially_empty and empty else "attempted")
        if result == "attempted":
            result = "deferred" if self.claim_counts[room] else "unrecognized"
        result = self.record_task(room, result)
        detail = {"collected": "수령 완료 확인", "skipped": "수령할 자원 없음 확인",
                  "attempted": "수령 버튼 누름 / 완료 여부 미확인",
                  "unrecognized": "수령 버튼 미인식 / 이번 시설 보류",
                  "deferred": "수령 결과 미확인 / 중복 입력 보류"}[result]
        self.log(f"{LABELS[room]}: {detail} / {self.claim_counts[room]}회 클릭")
        if self.on_issue and result in {"attempted", "unrecognized", "deferred"}:
            self.on_issue(room, detail)
        return screen

    def cycle(self, selected, restore_sleep=False):
        self.results, self.claim_counts = {}, {}
        self.wake_attempts = 0
        from start_navigation import prepare_start
        menu = self.ensure_menu(prepare_start(self))
        for room in selected:
            self.progress(LABELS[room] + ": 시설 화면 열기")
            try:
                screen = self.open_room(room, menu)
                screen = self.collect_room(room, screen)
            except Halt as exc:
                if self.stop.is_set():raise
                # Continue only after fresh recognition proves a safe menu.
                # Unknown screens or a lost connection propagate to VM recovery.
                if self.on_issue:self.on_issue(room,str(exc))
                if room not in self.results:
                    self.results[room]="failed"
                    if self.on_result:self.on_result(room,"failed")
                self.log(LABELS[room]+": 확인 실패 / 메뉴 복귀 확인 후 다음 시설 진행")
                recovery=self.screen()
                if recovery.state not in {"main","menu"} and not self.room_visible(recovery,room):raise
                menu=self.ensure_menu(recovery,room)
            else:
                menu=self.ensure_menu(screen,room)
        if restore_sleep:
            self.progress("수령 확인 완료 → 절전 모드 복귀 중")
            self.click_match("menu", "sleep_menu", menu)
            self.wait_for({"sleep"})
            self.log("절전 모드 복귀 확인")
        self.log("이번 수령 확인 완료")
        return dict(self.results)
