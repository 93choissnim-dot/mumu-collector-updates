"""Daily free-only routes; every spend is durably reserved and reconciled."""
from collector import Halt,ScreenChanged
from daily_execution import OutcomeUnknown
from daily_state import korea_day,step_label
from free_daily_vision import PAGES

SUMMON_PAGES={p for p in PAGES if p.startswith('free_summon_')}
STORE_PAGES={p for p in PAGES if p.startswith('free_store')}

class FreeDailyActions:
    def free_check_day(self):
        self.daily_check_day()
        if korea_day()!=self.daily_day:raise Halt('KST 자정이 지나 무료 작업을 중단했습니다. 새 날짜로 다시 실행해 주세요.')
    def free_count(self,s):
        values=[n for n in (0,1,2) if self.daily_has(s,'free_count_'+str(n))]
        return values[0] if len(values)==1 else None
    def free_commit(self,s,key,count=None,required=()):
        if self.daily_detail().get('pending'):raise OutcomeUnknown('이전 무료 입력 결과 미확인 / 중복 입력 보류')
        def reserve():
            self.free_check_day()
            self.daily_checkpoint('uncertain',pending='free_'+key,before_count=count)
        self.free_check_day()
        return self.daily_try_tap(s,'free_'+key,work=True,before_input=reserve,required=required)
    def daily_summon(self):
        for key in ('character','skill','pet'):
            self.daily_run_step(key,step_label('daily_summon',key),lambda k=key:self.free_summon_step(k))
        self.daily_main()
    def free_summon_step(self,key):
        target='free_summon_'+key;result='free_summon_result_'+key
        s=self.daily_wait(SUMMON_PAGES|{'main','menu'})
        if s.state in {'main','menu'}:
            s=self.daily_open('summon',SUMMON_PAGES)
        # Results expose only a verified close, never their repeat-summon button.
        if s.state.startswith('free_summon_result_') and s.state!=result:
            self.daily_tap(s,'free_result_close');s=self.daily_wait(SUMMON_PAGES)
        if s.state not in {target,result}:
            self.daily_tap(s,'free_tab_'+key);s=self.daily_wait({target})
        deadline=self.now()+110;sent=0
        while self.now()<deadline:
            self.free_check_day()
            s=self.daily_ready({target,result},['free_count_0','free_count_1','free_count_2'],timeout=min(90,max(1,deadline-self.now())))
            n=self.free_count(s);detail=self.daily_detail()
            if detail.get('pending'):
                before=detail.get('before_count')
                if type(before) is int and before in (1,2) and n is not None and 0<=n<before:
                    self.daily_confirm_input('free_count_decreased')
                else:
                    self.pause(.5);continue
            if s.state==result:
                if not self.daily_try_tap(s,'free_result_close'):continue
                continue
            if n==0:
                self.daily_mark(key);return
            if n not in (1,2):raise Halt('무료 소환 횟수를 확인하지 못했습니다.')
            if sent>=2:raise OutcomeUnknown('무료 소환 횟수가 예상과 달라 추가 입력을 보류합니다.')
            if not self.daily_has(s,'free_summon'):
                self.pause(.4);continue
            if self.free_commit(s,'summon',n,required=('free_count_'+str(n),'free_identity_'+key)):
                sent+=1
        raise OutcomeUnknown('무료 소환 결과 확인 시간 초과 / 중복 소환 보류')
    def daily_store(self):
        for key in ('ruby','ruby_ad','cube_ad'):
            self.daily_run_step(key,step_label('daily_store',key),lambda k=key:self.free_store_step(k))
        self.daily_main()
    def free_store_scroll(self,s,up=False):
        self.free_check_day();fresh=self.screen()
        selected='free_selected_general' if self.daily_step=='cube_ad' else 'free_selected_currency'
        if fresh.state!='free_store' or not self.daily_has(fresh,selected):raise ScreenChanged('상점 탭이 바뀌어 스크롤을 보류합니다.')
        self.free_check_day();self.forget_observations()
        self.device.drag((690,165),(690,440)) if up else self.device.drag((690,440),(690,165))
        self.pause(.8)
    def free_store_find(self,key):
        s=self.daily_wait(STORE_PAGES|{'main','menu'})
        if s.state in {'main','menu'}:s=self.daily_open('store',STORE_PAGES)
        if s.state.startswith('free_store_confirm_') or s.state=='free_store_dialog':
            if s.state=='free_store_confirm_'+key:return s
            self.daily_tap(s,'free_dialog_close');s=self.daily_wait({'free_store'})
        tab='general' if key=='cube_ad' else 'currency'
        self.daily_tap(s,'free_tab_'+tab)
        s=self.daily_ready({'free_store'},['free_selected_'+tab])
        # Always start at the top: tab changes and claims may reset/reorder cards.
        for _ in range(3):
            self.free_store_scroll(s,up=True);s=self.daily_ready({'free_store'},['free_selected_'+tab])
        for i in range(9):
            for marker in ('open_'+key,'done_'+key):
                if self.daily_has(s,'free_'+marker):
                    return self.daily_ready({'free_store'},['free_'+marker])
            if key=='cube_ad' and self.daily_has(s,'free_cube_absent'):
                return self.daily_ready({'free_store'},['free_cube_absent'])
            if i<8:
                self.free_store_scroll(s);s=self.daily_ready({'free_store'},['free_selected_'+tab])
        raise Halt(step_label('daily_store',key)+': 무료 상품 또는 수령 완료 표시를 확인하지 못했습니다.')
    def free_store_step(self,key):
        self.free_check_day();s=self.free_store_find(key)
        if self.daily_has(s,'free_done_'+key) or (key=='cube_ad' and self.daily_has(s,'free_cube_absent')):
            if self.daily_detail().get('pending') and key=='cube_ad':
                # A missing card alone cannot settle an interrupted purchase.
                raise OutcomeUnknown('이전 큐브 수령 결과 미확인 / 중복 수령 보류')
            self.daily_mark(key);return
        if self.daily_detail().get('pending'):
            raise OutcomeUnknown('이전 상점 무료 수령 결과 미확인 / 중복 수령 보류')
        if s.state=='free_store':
            if not self.daily_try_tap(s,'free_open_'+key):raise ScreenChanged('무료 상품 화면이 바뀌었습니다. 다시 확인해 주세요.')
            s=self.daily_ready({'free_store_confirm_'+key},['free_confirm_'+key])
        self.daily_reward_seen=False
        if not self.free_commit(s,'confirm_'+key):raise ScreenChanged('무료 확인창이 바뀌었습니다.')
        deadline=self.now()+90
        while self.now()<deadline:
            self.free_check_day()
            s=self.daily_wait({'free_store'},timeout=max(1,deadline-self.now()))
            if self.daily_reward_seen:break
            # The shop reappears before its delayed reward animation. Keep
            # observing; neither retry nor an early failure is justified yet.
            self.pause(.35)
        if not self.daily_reward_seen:
            raise OutcomeUnknown('상점 보상 화면을 확인하지 못했습니다. 중복 수령을 보류합니다.')
        self.daily_confirm_input('store_reward_confirmed')
        self.daily_mark(key)
