"""Recorded reward routes; every action requires a freshly recognized page."""
import time
from collector import Collector,Halt,ScreenChanged
from vision import LABELS
from task_catalog import EXTRA_LABELS,PAGE_MARKERS,DAILY_LABELS,BASE_TASKS
from world_boss import WorldBossActions
from daily_actions import DailyActions,DAILY_PAGES
from autumn_actions import AutumnActions

class ExtraCollector(AutumnActions,DailyActions,WorldBossActions,Collector):
    def wait_page(self,states,timeout=35,*,reuse=True):
        from recognition_common import TransitionWatch
        watch=TransitionWatch(self.now(),timeout)
        self.trace.expected=sorted(states)
        deadline=self.now()+timeout;previous=None;count=0;overlay_count=0;last_tap=0;overlays={}
        if reuse:
            previous,count,screen=self.confirmation_seed(lambda s:s.state if s.state in states else None)
            if count>=2:return screen
        while self.now()<deadline:
            screen=self.screen()
            if screen.state in {'equipment','offline_reward'}:
                if self.dismiss_overlay(screen,overlays):
                    previous=None;count=0;self.pause(.25);continue
            else:
                overlays['kind']=None;overlays['seen']=0
            if screen.state=='reward':
                # Allow long reward animations, but don't keep tapping indefinitely.
                previous=None;count=0
                if 'reward_close' in screen.matches and overlay_count<3 and self.now()-last_tap>=2:
                    self.pause(.3);fresh=self.screen()
                    if fresh.state=='reward' and 'reward_close' in fresh.matches:
                        self.tap(fresh,point=(640,520),action='reward_close');overlay_count+=1;last_tap=self.now()
                self.pause(.3);continue
            if screen.state in states:
                count=count+1 if previous==screen.state else 1
                if count>=2:return screen
            else:count=0
            if screen.state=='unknown':
                watch.observe(self.last_image,self.now())
                if watch.expired(self.now()):break
            else:watch.last_change=self.now()
            previous=screen.state;self.pause(.25)
        raise Halt('추가 기능 화면 확인 시간 초과 / 임의 클릭 없이 중지')

    def return_base(self,screen=None,room=None):
        if screen is not None and screen.state in DAILY_PAGES:
            screen=self.daily_main()
        states=set(PAGE_MARKERS)|{'main','menu','sleep'}|{r+s for r in LABELS for s in ('_ready','_empty','_wait')}
        if screen is None or screen is not self.last_screen or (
                screen.state not in states and not (room is not None and self.room_visible(screen,room))):
            screen=self.wait_page(states)
        # Nested boss dialogs need at most three confirmed departures.
        for _ in range(3):
            page=screen.state
            if page in {'main','menu'}:return screen
            if page not in PAGE_MARKERS:return super().ensure_menu(screen,room)
            try:
                if page in {'event_menu','autumn'}:
                    self.autumn_tap(screen,'event_home')
                else:
                    point={'boss_rank':(866,65),'boss_select':(830,85),'training':(830,50)}.get(page,(34,28))
                    self.tap(screen,point=point);self.pause(.6)
            except ScreenChanged:
                # This exception is raised before input only. A transport error
                # after dispatch must still propagate without another touch.
                self.trace.event('navigation_recheck',action='return',state=page)
            screen=self.wait_page(states)
        if screen.state in PAGE_MARKERS:raise Halt('추가 기능 닫기 3회 후에도 화면이 남아 있습니다.')
        return super().ensure_menu(screen,room)

    def ensure_menu(self,screen=None,room=None):
        return super().ensure_menu(self.return_base(screen,room),room)

    def enter(self,task,menu):
        if task=='ranking':
            self.click_match('menu','x_menu_rank',menu)
            return self.wait_page({'ranking'})
        if task=='training':
            self.click_match('menu','x_menu_train',menu)
            return self.wait_page({'training'})
        if task=='excavation':
            self.click_match('menu','x_menu_relic',menu)
            page=self.wait_page({'relic','excavation'})
            if page.state=='relic':
                self.click_match('relic','x_dig_open',page)
                page=self.wait_page({'excavation'})
            return page
        raise Halt('지원하지 않는 추가 기능입니다.')

    def record_task(self,task,result):
        from history import TERMINAL_RESULTS
        if task not in DAILY_LABELS:
            if result in TERMINAL_RESULTS:self.action_state.reset(task)
            elif result in {'attempted','unrecognized'}:
                if self.action_state.fail(task,self.trace.step or 'verify',getattr(self.last_screen,'state','unknown'),result):result='deferred'
        if (task=='autumn' and result in {'deferred','attempted'}
                and self.action_state.pending(task) and self.on_issue):
            self.on_issue(task,EXTRA_LABELS[task]+': 이전 입력 결과 미확인 / 현재 화면을 기록했습니다. 중복 입력을 보류합니다.')
        return super().record_task(task,result)

    def consume_manual_claim_retry(self,task,slot='claim'):
        """One explicit free-claim retry per task/boss, never replenished on resume."""
        if task not in {'autumn','ranking','excavation','worldboss'}:return False
        tasks=getattr(self,'manual_retry_tasks',set())
        if task=='worldboss':
            if task in tasks:
                from world_boss import BOSSES
                tasks.discard(task)
                self.manual_boss_retry_slots={boss[0] for boss in BOSSES}
            slots=getattr(self,'manual_boss_retry_slots',set())
            allowed=slot in slots;slots.discard(slot)
            return allowed
        allowed=task in tasks;tasks.discard(task)
        return allowed

    def claim_training(self,screen,*,record=True):
        # Training is a repeatable donation. Level text is unrelated to readiness.
        task='training';slot='claim'
        pending=self.action_state.pending(task,slot) is not None
        resumed=getattr(self,'resume_counts',{}).pop(task,0)
        self.claim_counts[task]=max(int(pending),resumed)
        attempts=self.claim_counts[task]
        def finish(result,reason=None):
            value=self.record_task(task,result) if record else result
            if value=='deferred' and self.on_issue:
                self.on_issue(task,reason or '수련: 버튼 상태를 확인하지 못해 실행을 보류했습니다.')
            return value
        self.trace.step='inspect'
        deadline=self.now()+70;previous=None;stable=0
        while self.now()<deadline:
            screen=self.screen()
            active=screen.state=='training' and 'x_train_active' in screen.matches
            empty=screen.state=='training' and 'x_train_empty' in screen.matches
            key=('active' if active else 'empty') if active!=empty else None
            stable=stable+1 if key is not None and key==previous else int(key is not None)
            previous=key
            if stable>=2:
                if empty:
                    self.action_state.confirm(task,slot,source='training_button_inactive')
                    return finish('collected' if attempts else 'skipped')
                self.progress(EXTRA_LABELS[task]+': 기부 실행 / 활성 버튼이 남아 있으면 반복')
                self.trace.step='claim'
                def reserve():
                    self.action_state.reserve(task,slot,repeat_authorized=True,
                        repeat_source='repeatable_training_donation',evidence={'mode':'repeatable_donation'})
                    self.claim_counts[task]+=1
                try:self.click_match('training','x_train_active',screen,before_input=reserve)
                except ScreenChanged:
                    previous=None;stable=0;self.pause(.25);continue
                attempts+=1;self.trace.step='verify';previous=None;stable=0
            self.pause(.3)
        reason=('수련: 반복 실행 제한 시간에 도달했습니다. 다음 실행에서 현재 버튼을 다시 확인합니다.'
                if attempts else '수련: 버튼 상태를 확인하지 못해 실행을 보류했습니다.')
        return finish('deferred',reason)

    def claim_extra(self,task,screen,*,record=True):
        if task=='training':return self.claim_training(screen,record=record)
        page={'ranking':'ranking','worldboss':'boss_rank','excavation':'excavation','training':'training'}[task]
        prefix={'ranking':'x_rank','worldboss':'x_boss','excavation':'x_dig','training':'x_train'}[task]
        def finish(result):
            value=self.record_task(task,result) if record else result
            if self.on_issue and value in {'deferred','attempted'} and (task!='training' or not record):
                self.on_issue(task,EXTRA_LABELS[task]+': 입력 결과 미확인 / 중복 입력 보류. 완료 상태를 확인한 뒤 진행합니다.')
            return value
        self.trace.step='inspect'
        slot=getattr(self,'boss_slot','claim') if task=='worldboss' else 'claim'
        manual_retry=self.consume_manual_claim_retry(task,slot)
        resumed_pending=bool(self.action_state.pending(task,slot))
        self.claim_counts[task]=getattr(self, 'resume_counts', {}).pop(task, 0) if task != 'worldboss' else 0
        if resumed_pending:self.claim_counts[task]=max(1,self.claim_counts[task])
        attempts=self.claim_counts[task];resumed_input=bool(attempts);stable=0;last=None
        deadline=self.now()+70
        while self.now()<deadline:
            # Button state must agree on two observations, independently of page recognition.
            screen=self.wait_page({page},reuse=stable==0)
            active=prefix+'_active' in screen.matches
            empty=prefix+'_empty' in screen.matches
            if active==empty:
                stable=0;self.pause(.4);continue
            key='active' if active else 'empty'
            stable=stable+1 if key==last else 1;last=key
            _,observations,_=self.confirmation_seed(lambda s:
                key if s.state==page and (prefix+'_'+key) in s.matches
                and (prefix+'_'+('empty' if key=='active' else 'active')) not in s.matches else None)
            stable=max(stable,observations)
            if stable<2:self.pause(.25);continue
            if empty:
                result='collected' if attempts else 'skipped'
                if result in {'collected','skipped'}:self.action_state.confirm(task,slot)
                return finish(result)
            if resumed_pending or resumed_input:
                if not manual_retry:return finish('deferred')
                # Only a stable active FREE claim can use the explicit permission.
                # The guarded reserve archives the old uncertainty before the new input.
                self.trace.event('manual_claim_retry',slot=slot)
                manual_retry=False;resumed_pending=False;resumed_input=False
                attempts=0;self.claim_counts[task]=0
            if attempts:
                self.pause(.4)
                continue
            self.progress(EXTRA_LABELS[task]+': 실행 / 결과 확인 전 중복 입력 보류')
            self.trace.step='claim'
            def reserve():
                self.action_state.reserve(task,slot,repeat_authorized=bool(self.action_state.pending(task,slot)))
                self.claim_counts[task]=attempts+1
            self.click_match(page,prefix+'_active',screen,before_input=reserve)
            attempts+=1
            deadline=min(deadline,self.now()+15)
            self.trace.step='verify'
            stable=0;last=None;self.pause(1)
        if attempts:return finish('deferred')
        raise Halt(EXTRA_LABELS[task]+': 버튼 상태를 확인하지 못했습니다.')

    def cycle(self,selected,restore_sleep=False):
        self.results={};self.claim_counts={};self.wake_attempts=0
        from start_navigation import prepare_start
        start=prepare_start(self)
        menu=self.return_base(start) if selected and selected[0] in BASE_TASKS else self.ensure_menu(start)
        for index,task in enumerate(selected):
            self.trace.task=task;self.trace.step='entry'
            if task not in DAILY_LABELS and self.action_state.blocked(task):
                self.log('같은 오류 반복 / 자동 재시도 보류: '+task)
                self.record_task(task,'deferred');continue
            if task not in LABELS and task not in EXTRA_LABELS and task not in DAILY_LABELS:raise Halt('지원하지 않는 작업입니다.')
            title=LABELS.get(task) or EXTRA_LABELS.get(task) or DAILY_LABELS[task]
            self.progress(title+': 화면 열기')
            try:
                if task in LABELS:
                    screen=self.open_room(task,menu)
                    screen=self.collect_room(task,screen)
                elif task in DAILY_LABELS:
                    self.collect_daily(task)
                    screen=self.last_screen
                elif task=='worldboss':
                    screen=self.collect_world_boss(menu)
                elif task=='autumn':
                    screen=self.collect_autumn(menu)
                else:
                    screen=self.enter(task,menu)
                    self.claim_extra(task,screen)
                    screen=self.last_screen
            except Halt as exc:
                if self.stop.is_set():raise
                from daily_state import LedgerError
                if isinstance(exc,LedgerError):raise
                result=self.daily_outcome() if task in DAILY_LABELS and getattr(self,'daily_task',None)==task else None
                if task not in DAILY_LABELS and self.action_state.fail(task,self.trace.step or 'entry',getattr(self.last_screen,'state','unknown'),str(exc)):
                    result='deferred'
                if task not in self.results:self.record_task(task,result or 'failed')
                if self.on_issue:self.on_issue(task,str(exc))
                self.log(title+': 확인 실패 / 안전한 메뉴 복귀 확인')
                screen=self.screen()
                known=screen.state in set(PAGE_MARKERS)|DAILY_PAGES|{'main','menu'} or (task in LABELS and self.room_visible(screen,task))
                if not known:raise
            # Do not reset exhausted navigation attempts by retrying this block.
            self.trace.task=task;self.trace.step='return'
            try:
                next_task=selected[index+1] if index+1<len(selected) else None
                navigate=self.return_base if next_task in BASE_TASKS else self.ensure_menu
                menu=navigate(screen,task if task in LABELS else None)
            except Halt as exc:
                if self.on_issue and not self.stop.is_set():self.on_issue(task,'화면 복귀 확인 필요: '+str(exc))
                raise
        if restore_sleep:
            self.progress('작업 완료 → 절전 모드 복귀 중')
            self.click_match('menu','sleep_menu',menu);self.wait_for({'sleep'})
        return dict(self.results)
