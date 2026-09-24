"""Free autumn-event reward collection at the existing common interval."""
from collector import Halt
from task_catalog import TOP_BAR_POINTS


class AutumnActions:
    def autumn_tap(self,screen,key=None,point=None,*,before_input=None):
        self.tap(screen,key,point,before_input=before_input)
        self.pause(.6)

    def autumn_ready(self,timeout=25):
        from recognition_common import TransitionWatch
        watch=TransitionWatch(self.now(),timeout);end=watch.end;last=None;count=0;overlays={}
        self.trace.expected=['autumn'];self.trace.event('expect_buttons',keys=['autumn_active','autumn_empty'])
        while self.now()<end:
            screen=self.screen()
            if self.dismiss_overlay(screen,overlays):
                last=None;count=0;self.pause(.25);continue
            overlays={}
            keys=tuple(k for k in ('autumn_active','autumn_empty') if k in screen.matches) if screen.state=='autumn' else ()
            observed=keys[0] if len(keys)==1 else None
            count=count+1 if observed and observed==last else int(bool(observed));last=observed
            if count>=2:return screen,observed
            if observed is None and screen.state=='autumn':
                watch.observe(self.last_image,self.now(),(760,462,943,524))
                if watch.expired(self.now()):break
            else:watch.last_change=self.now()
            self.pause(.3)
        raise Halt('가을맞이: 수령 가능 또는 보상 0/10 상태를 확인하지 못했습니다.')

    def collect_autumn(self,menu):
        manual_retry=self.consume_manual_claim_retry('autumn')
        if menu.state not in {'main','menu'}:raise Halt('가을맞이: 진입 전 기본 화면 확인이 필요합니다.')
        self.trace.step='entry'
        self.top_bar_tap(menu,'event')
        page=self.wait_page({'event_menu','autumn'})
        if page.state=='event_menu':
            # Confirm absence separately; never choose a different event by row.
            fresh=self.screen()
            if fresh.state!='event_menu':raise Halt('가을맞이: 이벤트 목록이 바뀌었습니다.')
            if 'autumn_tab' not in page.matches and 'autumn_tab' not in fresh.matches:
                self.log('가을맞이: 이벤트 항목 없음 / 건너뛰기')
                self.record_task('autumn','unavailable');return fresh
            self.trace.step='tab'
            self.autumn_tap(fresh,'autumn_tab')
        self.trace.step='inspect'
        screen,key=self.autumn_ready()
        pending=bool(self.action_state.pending('autumn'))
        self.claim_counts['autumn']=int(pending) or getattr(self,'resume_counts',{}).pop('autumn',0)
        if key=='autumn_empty':
            self.log('가을맞이: 받을 보상 없음 / 다음 공통 간격에 다시 확인')
            self.action_state.confirm('autumn')
            self.record_task('autumn','collected' if pending else 'skipped');return screen
        if pending or self.claim_counts['autumn']:
            if not manual_retry:
                self.log('가을맞이: 이전 수령 결과 미확인 / 중복 입력 보류')
                self.record_task('autumn','deferred');return screen
            self.trace.event('manual_claim_retry',slot='claim')
        self.progress('가을맞이: 누적 재료 수령')
        self.trace.step='claim'
        def reserve():
            self.action_state.reserve('autumn');self.claim_counts['autumn']=1
        self.autumn_tap(screen,'autumn_active',before_input=reserve)
        self.trace.step='verify'
        # One verified free claim per cycle. An uncertain result never authorizes
        # repeated presses; the usual bounded retry schedule can check it later.
        end=self.now()+25
        while self.now()<end:
            screen,key=self.autumn_ready(timeout=max(1,end-self.now()))
            if key=='autumn_empty':
                self.action_state.confirm('autumn')
                self.record_task('autumn','collected');return screen
            self.pause(.5)
        self.record_task('autumn','attempted');return screen
