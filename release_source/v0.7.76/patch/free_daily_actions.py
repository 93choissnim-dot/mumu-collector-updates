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
        from adb_device import InputNotSent
        if self.daily_detail().get('pending'):raise OutcomeUnknown('이전 무료 입력 결과 미확인 / 중복 입력 보류')
        reserved=False
        def reserve():
            nonlocal reserved
            self.free_check_day()
            self.daily_checkpoint('uncertain',pending='free_'+key,before_count=count)
            reserved=True
        self.free_check_day()
        try:sent=self.daily_try_tap(s,'free_'+key,work=True,before_input=reserve,required=required)
        except InputNotSent:
            if reserved:
                self.daily_checkpoint('running',pending=None,before_count=None,
                                      reason='',resolution_source='input_not_sent')
            raise
        if not sent and reserved:
            # ScreenChanged guarantees this call dispatched no input. Retire
            # only the reservation made by this call, never an inherited one.
            self.daily_checkpoint('running',pending=None,before_count=None,
                                  reason='',resolution_source='input_not_sent')
        return sent
    def daily_summon(self):
        for key in ('character','skill','pet'):
            self.daily_run_step(key,step_label('daily_summon',key),lambda k=key:self.free_summon_step(k))
        self.daily_main()
    def free_summon_step(self,key):
        target='free_summon_'+key;result='free_summon_result_'+key;reveal='free_summon_reveal_'+key
        s=self.daily_wait(SUMMON_PAGES|{'main','menu'})
        if s.state in {'main','menu'}:
            s=self.daily_open('summon',SUMMON_PAGES)
        if s.state.startswith('free_summon_reveal_') and s.state!=reveal:
            other=s.state.removeprefix('free_summon_reveal_')
            self.daily_tap(s,'free_reveal',required=('free_identity_'+other,))
            s=self.daily_wait({'free_summon_result_'+other})
        # Results expose only a verified close, never their repeat-summon button.
        if s.state.startswith('free_summon_result_') and s.state!=result:
            self.daily_tap(s,'free_result_close');s=self.daily_wait(SUMMON_PAGES)
        if s.state not in {target,result,reveal}:
            self.daily_tap(s,'free_tab_'+key);s=self.daily_wait({target})
        deadline=self.now()+110;sent=0;reveal_attempts=0
        while self.now()<deadline:
            self.free_check_day()
            s=self.daily_ready({target,result,reveal},['free_count_0','free_count_1','free_count_2','free_reveal'],timeout=min(90,max(1,deadline-self.now())))
            if s.state==reveal:
                if reveal_attempts>=3:raise OutcomeUnknown('소환 결과 펼치기 3회 후에도 화면이 남아 있습니다.')
                if self.daily_try_tap(s,'free_reveal',required=('free_identity_'+key,)):
                    reveal_attempts+=1
                continue
            reveal_attempts=0
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
    def free_store_reward_identity(self,key):
        detail=self.daily_detail();request=detail.get('input_request')
        if detail.get('pending')!='free_confirm_'+key or not isinstance(request,dict) or not request.get('id'):return None
        return dict(kind='store_reward',request_id=request['id'],account=self.daily_ident,
                    task=self.daily_task,step=key,day=self.daily_day)
    def before_overlay_dismiss(self,screen):
        armed=getattr(self,'free_store_reward_request',None)
        if not armed or screen.state!='reward' or 'reward_close' not in screen.matches:return
        self.free_check_day()
        current=self.free_store_reward_identity(self.daily_step)
        if self.daily_task!='daily_store' or current!=armed:return
        # This hook runs inside verified_tap after a fresh reward observation,
        # before the close input. A failed save leaves the proof on screen.
        self.daily_checkpoint('uncertain',store_reward_proof=current)
    def free_store_finish_proven_reward(self,key):
        identity=self.free_store_reward_identity(key)
        if identity is None or self.daily_detail().get('store_reward_proof')!=identity:return False
        self.free_check_day()
        self.daily_checkpoint('done',values={key:'done'},pending=None,reason='',
                              resolution_source='store_reward_confirmed')
        return True
    def free_store_visible_target(self,s,key,tab):
        if s.state!='free_store' or not self.daily_has(s,'free_selected_'+tab):return None
        markers=('open_'+key,'done_'+key)+(('cube_absent',) if key=='cube_ad' else ())
        for marker in markers:
            if self.daily_has(s,'free_'+marker):
                return self.daily_ready({'free_store'},['free_'+marker])
        return None
    def free_store_find(self,key):
        s=self.daily_wait(STORE_PAGES|{'main','menu'})
        if s.state in {'main','menu'}:s=self.daily_open('store',STORE_PAGES)
        if s.state.startswith('free_store_confirm_') or s.state=='free_store_dialog':
            if s.state=='free_store_confirm_'+key:return s
            self.daily_tap(s,'free_dialog_close');s=self.daily_wait({'free_store'})
        tab='general' if key=='cube_ad' else 'currency'
        visible=self.free_store_visible_target(s,key,tab)
        if visible is not None:return visible
        if not self.daily_has(s,'free_selected_'+tab):self.daily_tap(s,'free_tab_'+tab)
        s=self.daily_ready({'free_store'},['free_selected_'+tab])
        visible=self.free_store_visible_target(s,key,tab)
        if visible is not None:return visible
        # Search toward the top, stopping as soon as the target is verified.
        for _ in range(3):
            self.free_store_scroll(s,up=True);s=self.daily_ready({'free_store'},['free_selected_'+tab])
            visible=self.free_store_visible_target(s,key,tab)
            if visible is not None:return visible
        for i in range(9):
            visible=self.free_store_visible_target(s,key,tab)
            if visible is not None:return visible
            if i<8:
                self.free_store_scroll(s);s=self.daily_ready({'free_store'},['free_selected_'+tab])
        raise Halt(step_label('daily_store',key)+': 무료 상품 또는 수령 완료 표시를 확인하지 못했습니다.')
    def free_store_step(self,key):
        self.free_check_day()
        if self.free_store_finish_proven_reward(key):return
        s=self.free_store_find(key)
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
        self.free_store_reward_request=self.free_store_reward_identity(key)
        try:
            deadline=self.now()+90
            while self.now()<deadline:
                self.free_check_day()
                s=self.daily_wait({'free_store'},timeout=max(1,deadline-self.now()))
                if self.daily_reward_seen:break
                # A delayed animation may follow the shop page; never retry the claim.
                self.pause(.35)
            if not self.daily_reward_seen:
                raise OutcomeUnknown('상점 보상 화면을 확인하지 못했습니다. 중복 수령을 보류합니다.')
            self.daily_checkpoint('done',values={key:'done'},pending=None,reason='',
                                  resolution_source='store_reward_confirmed')
        finally:
            self.free_store_reward_request=None
