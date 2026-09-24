"""Free autumn-event reward collection at the existing common interval."""
from collector import Halt
from task_catalog import TOP_BAR_POINTS


class AutumnActions:
    def autumn_tap(self,screen,key=None,point=None):
        fresh=self.screen()
        if fresh.state!=screen.state:raise Halt('가을맞이: 화면이 바뀌어 클릭을 보류합니다.')
        if key:
            if key not in screen.matches or key not in fresh.matches:raise Halt('가을맞이: 버튼 상태가 바뀌어 클릭을 보류합니다.')
            point=fresh.matches[key].center
        if point is None:raise Halt('가을맞이: 클릭 위치를 확인하지 못했습니다.')
        self.trace.frame(self.last_image,fresh)
        self.trace.event('input',action=key or 'event_open',point=list(point),before=fresh.state)
        self.device.click(point);self.pause(.6)

    def autumn_ready(self,timeout=25):
        end=self.now()+timeout;last=None;count=0;overlays={}
        while self.now()<end:
            screen=self.screen()
            if self.dismiss_overlay(screen,overlays):
                last=None;count=0;self.pause(.25);continue
            overlays={}
            keys=tuple(k for k in ('autumn_active','autumn_empty') if k in screen.matches) if screen.state=='autumn' else ()
            observed=keys[0] if len(keys)==1 else None
            count=count+1 if observed and observed==last else int(bool(observed));last=observed
            if count>=2:return screen,observed
            self.pause(.3)
        raise Halt('가을맞이: 수령 가능 또는 보상 0/10 상태를 확인하지 못했습니다.')

    def collect_autumn(self,menu):
        if menu.state not in {'main','menu'}:raise Halt('가을맞이: 진입 전 기본 화면 확인이 필요합니다.')
        self.autumn_tap(menu,point=TOP_BAR_POINTS['event'])
        page=self.wait_page({'event_menu','autumn'})
        if page.state=='event_menu':
            # Confirm absence separately; never choose a different event by row.
            fresh=self.screen()
            if fresh.state!='event_menu':raise Halt('가을맞이: 이벤트 목록이 바뀌었습니다.')
            if 'autumn_tab' not in page.matches and 'autumn_tab' not in fresh.matches:
                self.log('가을맞이: 이벤트 항목 없음 / 건너뛰기')
                self.record_task('autumn','unavailable');return fresh
            self.autumn_tap(fresh,'autumn_tab')
        screen,key=self.autumn_ready()
        self.claim_counts['autumn']=0
        if key=='autumn_empty':
            self.log('가을맞이: 받을 보상 없음 / 다음 공통 간격에 다시 확인')
            self.record_task('autumn','skipped');return screen
        self.progress('가을맞이: 누적 재료 수령')
        self.autumn_tap(screen,'autumn_active');self.claim_counts['autumn']=1
        # One verified free claim per cycle. An uncertain result never authorizes
        # repeated presses; the usual bounded retry schedule can check it later.
        end=self.now()+25
        while self.now()<end:
            screen,key=self.autumn_ready(timeout=max(1,end-self.now()))
            if key=='autumn_empty':
                self.record_task('autumn','collected');return screen
            self.pause(.5)
        self.record_task('autumn','attempted');return screen
