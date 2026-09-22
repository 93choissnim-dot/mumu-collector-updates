"""Three-card world-boss rewards, excluding cards marked as preparing."""
import time
import cv2
import numpy as np
from collector import Halt
from task_catalog import TOP_BAR_POINTS

BOSSES = (
    ('cerberus', '지옥의 켈베로스', 'x_boss_card', (326,128,346,149)),
    ('kraken', '심해의 군주 크라켄', 'x_boss_card_kraken', (572,128,592,149)),
    ('void', '공허의 지배자', 'x_boss_card_void', (818,128,838,149)),
)


def boss_notices(image):
    """Inspect only each card's small top-right notification location."""
    found = {}
    for key, _, _, box in BOSSES:
        x1,y1,x2,y2 = box
        crop = image[y1:y2,x1:x2]
        hsv = cv2.cvtColor(crop,cv2.COLOR_BGR2HSV)
        mask = ((((hsv[:,:,0] <= 10) | (hsv[:,:,0] >= 170)) &
                 (hsv[:,:,1] >= 80) & (hsv[:,:,2] >= 75)).astype(np.uint8))
        count, _, stats, centers = cv2.connectedComponentsWithStats(mask,8)
        candidates = []
        for i in range(1,count):
            x,y,w,h,area = map(int,stats[i]);cx,cy = centers[i]
            if (14 <= area <= 180 and 4 <= w <= 16 and 5 <= h <= 18
                    and .6 <= w/h <= 1.6 and area/(w*h) >= .4
                    and 5 <= cx <= 15 and 5 <= cy <= 16):
                candidates.append((area,(x1+float(cx),y1+float(cy))))
        if len(candidates) == 1:
            found[key] = candidates[0][1]
    return found


class WorldBossActions:
    def open_boss_selection(self,menu):
        # The top icon overlays moving combat. Use the verified full menu
        # layout, then recheck it immediately before this navigation-only tap.
        if menu.state not in {'main','menu'}:raise Halt('월드보스: 진입 전 기본 화면 확인이 필요합니다.')
        self.trace.step='entry'
        self.top_bar_tap(menu,'worldboss')

    def wait_boss_selection(self, timeout=20):
        deadline=self.now()+timeout;last=None;count=0;overlays={}
        while self.now()<deadline:
            screen=self.screen()
            if self.dismiss_overlay(screen,overlays):
                last=None;count=0;self.pause(.25);continue
            key=None
            if screen.state=='boss_select':
                key=tuple((b[0], 'x_boss_notice_'+b[0] in screen.matches,
                           'x_boss_preparing_'+b[0] in screen.matches) for b in BOSSES)
            count=count+1 if key is not None and key==last else int(key is not None)
            if count>=2:return screen
            last=key;self.pause(.25)
        raise Halt('월드보스: 보스 선택창과 빨간 표시를 확인하지 못했습니다.')

    def return_to_boss_selection(self):
        from task_catalog import PAGE_MARKERS
        from vision import LABELS
        self.progress('월드보스: 수령 확인 후 보스 선택창으로 복귀 중')
        facilities={room+suffix for room in LABELS for suffix in ('_ready','_empty','_wait')}
        states=set(PAGE_MARKERS)|facilities|{'main','menu'}
        counts={}
        for _ in range(9):
            screen=self.wait_page(states)
            page=screen.state
            if page=='boss_select':return screen
            counts[page]=counts.get(page,0)+1
            if counts[page]>3:raise Halt('월드보스: 선택창 복귀를 3회 시도했지만 화면이 그대로입니다.')
            if page not in {'boss','boss_rank'}:
                menu=self.ensure_menu(screen)
                self.open_boss_selection(menu)
            else:
                if self.stop.is_set():raise Halt('사용자가 중지했습니다.')
                fresh=self.screen()
                if fresh.state!=page:continue
                self.log('월드보스: '+('랭킹창 닫기' if page=='boss_rank' else '보스 화면 나가기'))
                self.tap(fresh,point=(866,65) if page=='boss_rank' else (34,28))
                self.pause(.6)
        screen=self.wait_page(states)
        if screen.state=='boss_select':return screen
        raise Halt('월드보스: 선택창 복귀 횟수를 초과했습니다.')

    def collect_world_boss(self, menu):
        self.open_boss_selection(menu)
        selection=self.wait_boss_selection()
        targets=[];results=[];total_clicks=0
        for boss in BOSSES:
            key,title,_,_=boss
            if 'x_boss_preparing_'+key in selection.matches:
                self.log('월드보스: '+title+' / 준비 중 → 건너뛰기')
            elif 'x_boss_notice_'+key in selection.matches or self.action_state.pending('worldboss',key):
                targets.append(boss)
        if targets:self.log('월드보스: 수령 대상 일괄 확인 / '+', '.join(b[1] for b in targets))
        for index,(key,title,card,_) in enumerate(targets):
            if index:
                self.return_to_boss_selection()
                selection=self.wait_boss_selection()
            # Plan once. Recheck only the planned next boss before entering;
            # newly appearing notices belong to the next collection cycle.
            if ('x_boss_preparing_'+key in selection.matches or
                ('x_boss_notice_'+key not in selection.matches and not self.action_state.pending('worldboss',key))):
                self.log('월드보스: '+title+' / 대상 상태 변경 → 건너뛰기')
                continue
            self.boss_slot=key
            self.progress('월드보스: '+title+' / 보상 확인')
            def verify_target():
                fresh=self.last_screen
                if ('x_boss_preparing_'+key in fresh.matches or
                    ('x_boss_notice_'+key not in fresh.matches and not self.action_state.pending('worldboss',key))):
                    raise Halt('월드보스: 진입 직전 대상 상태가 바뀌어 클릭을 보류합니다.')
            self.click_match('boss_select',card,selection,before_input=verify_target)
            boss=self.wait_page({'boss'})
            self.click_match('boss','x_boss_rank_open',boss)
            ranking=self.wait_page({'boss_rank'})
            try:
                result=self.claim_extra('worldboss',ranking,record=False)
            finally:
                total_clicks+=self.claim_counts.get('worldboss',0)
                self.claim_counts['worldboss']=total_clicks
            results.append(result)
            label={'collected':'수령 완료','skipped':'수령할 보상 없음','attempted':'완료 여부 미확인','deferred':'결과 확인 필요 / 중복 입력 보류'}[result]
            self.log('월드보스: '+title+' / '+label)
        if not targets:self.log('월드보스: 빨간 표시가 있는 수령 대상 없음 → 수령 생략')
        # A persistent non-ranking notice must not reopen the same boss forever.
        result='deferred' if 'deferred' in results else 'attempted' if 'attempted' in results else 'collected' if 'collected' in results else 'skipped'
        self.claim_counts['worldboss']=total_clicks
        self.record_task('worldboss',result)
        return self.last_screen
