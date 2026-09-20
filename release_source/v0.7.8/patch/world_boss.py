"""Three-card world-boss rewards, excluding cards marked as preparing."""
import time
import cv2
import numpy as np
from collector import Halt

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
        self.progress('월드보스: 수령 확인 후 보스 선택창으로 복귀 중')
        states={'boss_rank','boss','boss_select','main','menu'}
        counts={}
        for _ in range(9):
            screen=self.wait_page(states)
            page=screen.state
            if page=='boss_select':return screen
            counts[page]=counts.get(page,0)+1
            if counts[page]>3:raise Halt('월드보스: 선택창 복귀를 3회 시도했지만 화면이 그대로입니다.')
            if page in {'main','menu'}:
                menu=self.ensure_menu(screen)
                self.click_match('menu','x_menu_boss',menu)
            else:
                if self.stop.is_set():raise Halt('사용자가 중지했습니다.')
                self.log('월드보스: '+('랭킹창 닫기' if page=='boss_rank' else '보스 화면 나가기'))
                self.device.click((866,65) if page=='boss_rank' else (34,28))
                self.pause(.6)
        screen=self.wait_page(states)
        if screen.state=='boss_select':return screen
        raise Halt('월드보스: 선택창 복귀 횟수를 초과했습니다.')

    def collect_world_boss(self, menu):
        self.click_match('menu','x_menu_boss',menu)
        visited=set();preparing_logged=set();results=[];total_clicks=0
        for _ in range(len(BOSSES)):
            selection=self.wait_boss_selection()
            for key,title,_,_ in BOSSES:
                if 'x_boss_preparing_'+key in selection.matches and key not in preparing_logged:
                    self.log('월드보스: '+title+' / 준비중 → 건너뛰기')
                    preparing_logged.add(key)
            candidate=next((b for b in BOSSES if b[0] not in visited
                and 'x_boss_notice_'+b[0] in selection.matches
                and 'x_boss_preparing_'+b[0] not in selection.matches),None)
            if candidate is None:break
            key,title,card,_=candidate
            visited.add(key)
            self.progress('월드보스: '+title+' / 빨간 표시 확인')
            self.click_match('boss_select',card,selection)
            boss=self.wait_page({'boss'})
            self.click_match('boss','x_boss_rank_open',boss)
            ranking=self.wait_page({'boss_rank'})
            try:
                result=self.claim_extra('worldboss',ranking,record=False)
            finally:
                total_clicks+=self.claim_counts.get('worldboss',0)
                self.claim_counts['worldboss']=total_clicks
            results.append(result)
            label={'collected':'수령 완료','skipped':'수령할 보상 없음','attempted':'완료 여부 미확인'}[result]
            self.log('월드보스: '+title+' / '+label)
            self.return_to_boss_selection()
        if not visited:self.log('월드보스: 빨간 표시가 있는 수령 대상 없음 → 수령 생략')
        # A persistent non-ranking notice must not reopen the same boss forever.
        result='attempted' if 'attempted' in results else 'collected' if 'collected' in results else 'skipped'
        self.claim_counts['worldboss']=total_clicks
        self.record_task('worldboss',result)
        return self.last_screen
