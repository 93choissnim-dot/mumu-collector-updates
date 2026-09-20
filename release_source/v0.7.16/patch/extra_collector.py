"""Recorded reward routes; every action requires a freshly recognized page."""
import time
import cv2
import numpy as np
from collector import Collector,Halt
from vision import LABELS
from task_catalog import EXTRA_LABELS,PAGE_MARKERS,DAILY_LABELS
from world_boss import WorldBossActions
from daily_actions import DailyActions,DAILY_PAGES

class ExtraCollector(DailyActions,WorldBossActions,Collector):
    def wait_page(self,states,timeout=35):
        deadline=self.now()+timeout;previous=None;count=0;overlay_count=0;last_tap=0;overlays={}
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
                        self.device.click((640,520));overlay_count+=1;last_tap=self.now()
                self.pause(.3);continue
            if screen.state in states:
                count=count+1 if previous==screen.state else 1
                if count>=2:return screen
            else:count=0
            previous=screen.state;self.pause(.25)
        raise Halt('추가 기능 화면 확인 시간 초과 / 임의 클릭 없이 중지')

    def ensure_menu(self,screen=None,room=None):
        if screen is not None and screen.state in DAILY_PAGES:
            screen=self.daily_main()
        states=set(PAGE_MARKERS)|{'main','menu','sleep'}|{r+s for r in LABELS for s in ('_ready','_empty','_wait')}
        screen=self.wait_page(states) if screen is None or screen is not self.last_screen or screen.state in {'offline_reward','equipment','reward'} else screen
        # Nested boss dialogs need at most three confirmed departures.
        for _ in range(3):
            page=screen.state
            if page not in PAGE_MARKERS:return super().ensure_menu(screen,room)
            point={'boss_rank':(866,65),'boss_select':(830,85),'training':(830,50)}.get(page,(34,28))
            self.device.click(point);self.pause(.6)
            screen=self.wait_page(states)
        if screen.state in PAGE_MARKERS:raise Halt('추가 기능 닫기 3회 후에도 화면이 남아 있습니다.')
        return super().ensure_menu(screen,room)

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
        self.results[task]=result
        if self.on_result:self.on_result(task,result)
        return result

    def claim_extra(self,task,screen,*,record=True):
        page={'ranking':'ranking','worldboss':'boss_rank','excavation':'excavation','training':'training'}[task]
        prefix={'ranking':'x_rank','worldboss':'x_boss','excavation':'x_dig','training':'x_train'}[task]
        finish=lambda result:self.record_task(task,result) if record else result
        self.claim_counts[task]=getattr(self, 'resume_counts', {}).pop(task, 0) if task != 'worldboss' else 0
        attempts=self.claim_counts[task];evidence=False;before=None;stable=0;last=None
        deadline=self.now()+70
        while self.now()<deadline:
            # Button state must agree on two observations, independently of page recognition.
            screen=self.wait_page({page})
            active=prefix+'_active' in screen.matches
            empty=prefix+'_empty' in screen.matches
            if active==empty:
                stable=0;self.pause(.4);continue
            key='active' if active else 'empty'
            stable=stable+1 if key==last else 1;last=key
            if stable<2:self.pause(.25);continue
            if attempts and task=='training' and before is not None:
                frame=cv2.resize(self.last_image,(960,540))
                after=frame[85:107,735:807]
                evidence=evidence or float(np.mean(np.max(cv2.absdiff(before,after),axis=2)>35))>.02
            if empty:
                return finish('collected' if attempts and (task!='training' or evidence) else ('attempted' if attempts else 'skipped'))
            if attempts>=3:return finish('attempted')
            if task=='training':
                frame=cv2.resize(self.last_image,(960,540));before=frame[85:107,735:807].copy()
            self.progress(EXTRA_LABELS[task]+f': 실행 ({attempts+1}/3)')
            self.click_match(page,prefix+'_active',screen)
            attempts+=1;self.claim_counts[task]=attempts
            stable=0;last=None;self.pause(1)
        raise Halt(EXTRA_LABELS[task]+': 버튼 상태를 확인하지 못했습니다.')

    def cycle(self,selected,restore_sleep=False):
        self.results={};self.claim_counts={};self.wake_attempts=0
        from start_navigation import prepare_start
        menu=self.ensure_menu(prepare_start(self))
        for task in selected:
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
                else:
                    screen=self.enter(task,menu)
                    self.claim_extra(task,screen)
                    screen=self.last_screen
            except Halt as exc:
                if self.stop.is_set():raise
                if task not in self.results:self.record_task(task,'failed')
                if self.on_issue:self.on_issue(task,str(exc))
                self.log(title+': 확인 실패 / 안전한 메뉴 복귀 확인')
                screen=self.screen()
                known=screen.state in set(PAGE_MARKERS)|DAILY_PAGES|{'main','menu'} or (task in LABELS and self.room_visible(screen,task))
                if not known:raise
            # Do not reset exhausted navigation attempts by retrying this block.
            menu=self.ensure_menu(screen,task if task in LABELS else None)
        if restore_sleep:
            self.progress('작업 완료 → 절전 모드 복귀 중')
            self.click_match('menu','sleep_menu',menu);self.wait_for({'sleep'})
        return dict(self.results)
