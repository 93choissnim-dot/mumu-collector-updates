"""Daily routes. Every input is bound to a freshly confirmed game screen."""
from collector import Halt,ScreenChanged
from daily_state import korea_day,DAILY_ALREADY
from daily_vision import DUNGEONS
from task_catalog import TOP_BAR_POINTS
from daily_execution import DailyExecution,OutcomeUnknown

DUNGEON_NAMES=dict(zip(DUNGEONS,('장비 보급소','소환 던전','스톤 채굴장','룬 동굴','유물 던전','보물 창고','아티팩트 공방')))
SWEEP_DUNGEONS=frozenset(('equipment','summon'))
WORK_BUTTONS={'pass_'+k+'_active' for k in ('ad','keys','gear')}|{
    'sweep_action','d_enter','donate_free','donate_50','relic_claim','shop_confirm_free',
    'guild_fight','guild_loot_claim','raid_fight'}
DAILY_PAGES={'daily_pass_'+k for k in ('ad','keys','gear')}|{'daily_room_'+k for k in DUNGEONS}|{
    'daily_dungeons','daily_sweep','daily_guild_menu','daily_guild_battle','daily_donate',
    'daily_relic','daily_shop','daily_shop_confirm','daily_guild_dungeon','daily_raid_map','daily_raid_detail'}

class DailyActions(DailyExecution):
    def daily_check_day(self):
        if getattr(getattr(self,'daily_ledger',None),'manual',False):return
        if korea_day()!=self.daily_day:raise Halt('KST 자정이 지나 일일 작업을 다시 예약합니다. 완료한 기록은 이전 날짜로 유지됩니다.')
    def daily_has(self,screen,key):return 'daily_'+key in screen.matches
    def daily_done(self,step):return self.daily_ledger.done(self.daily_ident,self.daily_task,step,self.daily_day)
    def daily_mark(self,step,value='done'):
        if value=='done' and step!='_complete':
            self.daily_ledger.checkpoint(self.daily_ident,self.daily_task,step,'done',self.daily_day,
                values={step:value},reason='',pending=None)
        else:self.daily_ledger.mark(self.daily_ident,self.daily_task,step,value,self.daily_day)
    def daily_wait(self,states,timeout=40):
        if hasattr(self,'trace'):self.trace.expected=sorted(states)
        self.daily_check_day()
        prior,count,screen=self.confirmation_seed(lambda s:s.state if s.state in states else None)
        if count>=2:return screen
        end=self.now()+timeout;overlays={}
        while self.now()<end:
            self.daily_check_day();screen=self.screen()
            if self.dismiss_overlay(screen,overlays):
                if screen.state=='reward' and overlays.get('attempts_by_kind',{}).get('reward',0):self.daily_reward_seen=True
                prior=None;count=0;self.pause(.25);continue
            # Each new overlay gets its own bounded dismissal budget.
            overlays={}
            if screen.state in states:
                count=count+1 if screen.state==prior else 1
                if count>=2:return screen
            else:count=0
            prior=screen.state;self.pause(.25)
        raise Halt('일일 작업: 예상 화면 '+', '.join(sorted(states))+' / 현재 '+getattr(self.last_screen,'state','unknown')+' / 화면 확인 시간 초과')
    def daily_ready(self,states,keys,timeout=25):
        self.daily_check_day()
        def observed(s):
            active=tuple(k for k in keys if self.daily_has(s,k)) if s.state in states else ()
            return (s.state,active) if active else None
        last,count,screen=self.confirmation_seed(observed)
        if count>=2:return screen
        end=self.now()+timeout;overlays={}
        if hasattr(self,'trace'):
            self.trace.expected=sorted(states);self.trace.event('expect_buttons',keys=list(keys))
        while self.now()<end:
            self.daily_check_day();screen=self.screen()
            if self.dismiss_overlay(screen,overlays):
                if screen.state=='reward' and overlays.get('attempts_by_kind',{}).get('reward',0):self.daily_reward_seen=True
                last=None;count=0;self.pause(.25);continue
            overlays={}
            active=tuple(k for k in keys if self.daily_has(screen,k)) if screen.state in states else ()
            current=(screen.state,active)
            count=count+1 if active and current==last else int(bool(active));last=current
            if count>=2:return screen
            self.pause(.25)
        raise Halt('일일 작업 버튼 확인 시간 초과: '+', '.join(keys))
    def daily_wait_marker(self,states,key,timeout=25):
        return self.daily_ready(states,[key],timeout)
    def daily_try_tap(self,screen,key=None,point=None,**kwargs):
        """A rejected pre-input capture sent nothing. Re-observe the decision.

        Device/ledger errors after an attempted input must never be retried here.
        """
        try:self.daily_tap(screen,key,point,**kwargs)
        except ScreenChanged:
            self.forget_observations();self.pause(.35)
            return False
        return True
    def daily_committed_tap(self,screen,key,**kwargs):
        if self.daily_detail().get('pending'):
            raise OutcomeUnknown('이전 입력 결과 미확인 / 중복 실행 보류: '+key)
        return self.daily_try_tap(screen,key,before_input=lambda:
            self.daily_checkpoint('uncertain',pending=key),**kwargs)
    def daily_confirm_input(self):
        if self.daily_detail().get('pending'):
            self.daily_checkpoint('running',pending=None,reason='')
    def daily_close_room(self,page):
        for _ in range(3):
            screen=self.daily_wait({page,'daily_dungeons'},timeout=8)
            if screen.state=='daily_dungeons':return
            if not self.daily_try_tap(screen,'d_close'):continue
            self.pause(1)
        self.daily_wait({'daily_dungeons'},timeout=8)
    def daily_tap(self,screen,key=None,point=None,*,work=False,before_input=None,required=()):
        fresh=self.tap(screen,'daily_'+key if key else None,point,
                 before_input=before_input,validate=self.daily_check_day,action=key or 'navigation',
                 required=tuple('daily_'+k for k in required))
        if work or key in WORK_BUTTONS:self.daily_performed=True
        # Combat observers own every battle/result frame, including short results.
        if key in {'d_enter','guild_fight','raid_fight','battle_skip','raid_skip','battle_leave','donate_50'}:
            self.pause(.65)
        else:self.post_input(fresh,'daily_'+key if key else None)
    def daily_main(self):
        screen=self.daily_wait(DAILY_PAGES|{'main','menu'})
        for _ in range(4):
            if screen.state=='main':return screen
            if screen.state=='menu':self.daily_tap(screen,point=(915,28))
            elif screen.state=='daily_sweep':self.daily_tap(screen,'sweep_close')
            elif screen.state=='daily_donate':self.daily_tap(screen,'donate_close')
            elif screen.state=='daily_relic':self.daily_tap(screen,'relic_close')
            elif screen.state=='daily_shop_confirm':self.daily_tap(screen,'shop_confirm_close')
            elif screen.state.startswith('daily_room_'):self.daily_tap(screen,'d_close')
            else:self.daily_tap(screen,point=(918,28))
            screen=self.daily_wait(DAILY_PAGES|{'main','menu'})
        raise Halt('일일 작업 후 기본 화면 복귀를 확인하지 못했습니다.')
    def daily_open(self,key,states):
        # Main-screen icons are translucent over live combat. Their background
        # is not a stable template. Navigation is bound to the complete main
        # screen and rechecked immediately before the fixed navigation input.
        points={'pass':TOP_BAR_POINTS['pass'],'dungeon':(509,505),'guild':(563,505)}
        if key not in points:raise Halt('지원하지 않는 일일 작업 진입입니다.')
        main=self.daily_main()
        if main.state!='main':raise Halt('일일 작업 진입 전 기본 화면 확인이 필요합니다.')
        if key=='pass':self.top_bar_tap(main,'pass',validate=self.daily_check_day)
        else:self.daily_tap(main,point=points[key])
        return self.daily_wait(states)
    def daily_combat(self,return_states,timeout=240,on_result=None):
        end=self.now()+timeout;last=None;count=0;skipped=False;overlays={};result=False;entered=False
        while self.now()<end:
            self.daily_check_day();screen=self.screen()
            if self.dismiss_overlay(screen,overlays):
                last=None;count=0;self.pause(.25);continue
            overlays={};count=count+1 if last==screen.state else 1;last=screen.state
            if count<2:self.pause(.25);continue
            if screen.state in {'daily_battle','daily_result','daily_clear'}:entered=True
            if screen.state=='daily_result':
                if not result and on_result:on_result()
                result=True
            elif screen.state=='daily_clear':
                try:self.daily_tap(screen,'battle_leave')
                except ScreenChanged:
                    last=None;count=0;self.pause(.25);continue
            elif screen.state=='daily_battle' and not skipped:
                key='raid_skip' if self.daily_has(screen,'raid_skip') else 'battle_skip'
                try:self.daily_tap(screen,key)
                except ScreenChanged:
                    last=None;count=0;self.pause(.25);continue
                skipped=True
            elif screen.state in return_states and entered:
                return screen,result
            self.pause(.3)
        raise Halt(('전투 종료' if entered else '전투 시작')+' 화면 확인 시간 초과 / 같은 전투를 임의로 다시 시작하지 않습니다.')
    def collect_daily(self,task):
        if not hasattr(self,'daily_ledger'):raise Halt('일일 완료 기록 연결이 없습니다.')
        self.daily_task=task;self.daily_day=korea_day();self.daily_reward_seen=False;self.daily_performed=False
        self.daily_summary='';self.daily_step=None
        if hasattr(self,'trace'):self.trace.task=task;self.trace.step=None
        if self.daily_done('_complete'):return self.record_task(task,DAILY_ALREADY[task])
        {'daily_pass':self.daily_pass,'daily_dungeons':self.daily_dungeons,'daily_guild':self.daily_guild}[task]()
        outcome=self.daily_outcome()
        if outcome:return self.record_task(task,outcome)
        self.daily_check_day();self.daily_mark('_complete')
        return self.record_task(task,'collected' if self.daily_performed else DAILY_ALREADY[task])
    def daily_pass(self):
        pages={'daily_pass_'+k for k in ('ad','keys','gear')}
        if any(not self.daily_done(k) and self.daily_detail(k).get('status')!='blocked' for k in ('ad','keys','gear')):
            self.daily_open('pass',pages)
        for key,y in [('ad',90),('keys',148),('gear',204)]:
            label='패스 수령: '+{'ad':'광고 제거','keys':'던전 멤버십','gear':'장비 멤버십'}[key]
            self.daily_run_step(key,label,lambda k=key,pos=y:self.daily_pass_tab(k,pos,pages))
        self.daily_main()
    def daily_pass_tab(self,key,y,pages):
        screen=self.daily_wait(pages|{'main','menu'})
        if screen.state in {'main','menu'}:screen=self.daily_open('pass',pages)
        if screen.state!='daily_pass_'+key:
            self.daily_tap(screen,point=(68,y));screen=self.daily_wait({'daily_pass_'+key})
        deadline=self.now()+20
        while self.now()<deadline:
            screen=self.daily_ready({'daily_pass_'+key},['pass_'+key+'_done','pass_'+key+'_active'],timeout=max(1,deadline-self.now()))
            if self.daily_has(screen,'pass_'+key+'_done'):
                self.progress('패스 수령 / '+('수령 완료' if self.daily_detail().get('pending') else '이미 완료'))
                self.daily_mark(key);return
            if self.daily_detail().get('pending'):
                self.pause(.4);continue
            self.daily_committed_tap(screen,'pass_'+key+'_active')
        raise OutcomeUnknown('패스 수령 결과 미확인 / 중복 수령 보류')
    def daily_find_dungeon(self,key):
        screen=self.daily_wait({'daily_dungeons'})
        for direction in (-1,-1,-1,-1,1,1,1,1,None):
            if self.daily_has(screen,'card_'+key):
                self.daily_tap(screen,'card_'+key);return self.daily_wait({'daily_room_'+key})
            if direction is None:break
            self.daily_check_day();fresh=self.screen()
            if fresh.state!='daily_dungeons':raise Halt('던전 목록이 바뀌었습니다.')
            self.daily_check_day()
            self.forget_observations()
            self.device.drag((800,290),(240,290)) if direction==-1 else self.device.drag((240,290),(800,290))
            self.pause(.8);screen=self.daily_wait({'daily_dungeons'})
        raise Halt(DUNGEON_NAMES[key]+': 던전 카드를 찾지 못했습니다.')
    def daily_dungeons(self):
        if any(not self.daily_done(k) and self.daily_detail(k).get('status')!='blocked' for k in DUNGEONS):
            self.daily_open('dungeon',{'daily_dungeons'})
        for key in DUNGEONS:
            label='1일 던전: '+DUNGEON_NAMES[key]
            self.daily_run_step(key,label,lambda k=key:self.daily_dungeon(k))
        self.daily_main()
    def daily_dungeon(self,key):
        page='daily_room_'+key;screen=self.daily_find_dungeon(key)
        if key in SWEEP_DUNGEONS:
            self.daily_tap(screen,'d_sweep_open');screen=self.daily_wait({'daily_sweep'})
            self.daily_reward_seen=False
            for _ in range(16):
                screen=self.daily_ready({'daily_sweep'},['sweep_action','sweep_free_0','sweep_free_1'])
                if self.daily_has(screen,'sweep_count_0') and self.daily_has(screen,'sweep_free_0'):
                    self.progress('1일 던전: '+DUNGEON_NAMES[key]+' / 입장 횟수 없음')
                    self.daily_mark(key);break
                if self.daily_detail().get('pending'):
                    if self.daily_has(screen,'sweep_count_0') or self.daily_reward_seen:self.daily_confirm_input()
                    else:raise OutcomeUnknown('소탕 결과 미확인 / 중복 소탕 보류')
                if self.daily_has(screen,'sweep_free_1') and self.daily_has(screen,'sweep_count_0'):
                    if not self.daily_try_tap(screen,point=(480,382),work=True,
                                             required=('sweep_free_1','sweep_count_0')):continue
                    self.daily_wait_marker({'daily_sweep'},'sweep_action')
                elif self.daily_has(screen,'sweep_action'):
                    self.daily_reward_seen=False
                    if not self.daily_committed_tap(screen,'sweep_action'):continue
                else:raise Halt(DUNGEON_NAMES[key]+': 소탕 또는 무료 열쇠 상태를 확인하지 못했습니다.')
            else:raise Halt(DUNGEON_NAMES[key]+': 소탕 횟수 확인이 필요합니다.')
            self.daily_tap(screen,'sweep_close');screen=self.daily_wait({page})
        else:
            for _ in range(16):
                screen=self.daily_ready({page},['d_enter','d_free_0','d_free_1'])
                zero=any(self.daily_has(screen,k) for k in ('d_count_0','d_count_zero1','d_count_zero2'))
                if zero and self.daily_has(screen,'d_free_0'):
                    self.progress('1일 던전: '+DUNGEON_NAMES[key]+' / 입장 횟수 없음')
                    self.daily_mark(key);break
                if self.daily_detail().get('pending'):
                    raise OutcomeUnknown('던전 입장 결과 미확인 / 중복 입장 보류')
                if zero and self.daily_has(screen,'d_free_1'):
                    counter=next(k for k in ('d_count_0','d_count_zero1','d_count_zero2') if self.daily_has(screen,k))
                    if not self.daily_try_tap(screen,point=(744,440),work=True,required=('d_free_1',counter)):continue
                    self.daily_wait_marker({page},'d_enter');continue
                if self.daily_has(screen,'d_enter'):
                    if not self.daily_committed_tap(screen,'d_enter'):continue
                    screen,_=self.daily_combat({page})
                    self.daily_confirm_input()
                else:raise Halt(DUNGEON_NAMES[key]+': 입장 횟수 또는 무료 열쇠 확인이 필요합니다.')
            else:raise Halt(DUNGEON_NAMES[key]+': 입장 횟수 확인이 필요합니다.')
        self.daily_close_room(page)
    def daily_guild_root(self):return self.daily_open('guild',{'daily_guild_menu','daily_guild_battle'})
    def daily_guild(self):
        for step,label in [('attendance','출석'),('donation','기부'),('relic','성물 보상'),('shop','상점 무료 코인'),('dungeon','길드 던전'),('raid','공방 약탈')]:
            self.daily_run_step(step,'길드: '+label,getattr(self,'daily_guild_'+step))
        self.daily_main()
    def daily_guild_page(self,battle=False):
        screen=self.daily_wait(DAILY_PAGES|{'main','menu'})
        if screen.state=='daily_shop_confirm':
            self.daily_tap(screen,'shop_confirm_close');screen=self.daily_wait({'daily_shop'})
        # Recorded left-arrow routes return to the guild's previous tab.
        # Never use a guessed back action on combat, modal, or unknown pages.
        if screen.state in {'daily_shop','daily_guild_dungeon'}:
            self.daily_tap(screen,point=(34,28))
            screen=self.daily_wait({'daily_guild_menu','daily_guild_battle','main'})
        elif screen.state in {'daily_donate','daily_relic'}:
            self.daily_tap(screen,'donate_close' if screen.state=='daily_donate' else 'relic_close')
            screen=self.daily_wait({'daily_guild_menu','daily_guild_battle','main'})
        if screen.state not in {'daily_guild_menu','daily_guild_battle'}:screen=self.daily_guild_root()
        wanted='daily_guild_battle' if battle else 'daily_guild_menu'
        if screen.state!=wanted:
            if battle:self.daily_tap(screen,'guild_battle_tab')
            else:self.daily_tap(screen,point=(385,75))
            screen=self.daily_wait({wanted})
        return screen
    def daily_guild_attendance(self):
        screen=self.daily_guild_page()
        if not self.daily_has(screen,'guild_attended'):
            self.daily_tap(screen,point=(78,478),work=True);screen=self.daily_wait({'daily_guild_menu'})
        else:self.progress('길드: 출석 / 이미 수령')
        if not self.daily_has(screen,'guild_attended'):raise Halt('길드 출석 완료 확인이 필요합니다.')
        self.daily_mark('attendance')
    def daily_guild_donation(self):
        self.daily_guild_page()
        for attempt in range(5):
            screen=self.daily_wait({'daily_guild_menu','daily_donate'})
            if screen.state=='daily_guild_menu':
                if self.daily_has(screen,'guild_donated'):
                    if attempt==0:self.progress('길드: 기부 / 이미 수령')
                    self.daily_mark('donation');return
                # A pending paid tap cannot be resolved from an unchanged generic button.
                if self.daily_detail().get('pending'):
                    raise OutcomeUnknown('루비 기부 결과 미확인 / 중복 기부 보류')
                self.daily_tap(screen,'guild_donate_open');screen=self.daily_wait({'daily_donate'})
            if self.daily_detail().get('pending'):
                raise OutcomeUnknown('루비 기부 결과 미확인 / 중복 기부 보류')
            if self.daily_has(screen,'donate_free'):self.daily_tap(screen,'donate_free')
            elif self.daily_has(screen,'donate_50'):
                paid=self.daily_ledger.get(self.daily_ident,self.daily_task,'donation_paid',self.daily_day) or 0
                if type(paid) is not int or paid<0:
                    from daily_state import LedgerError
                    raise LedgerError('루비 기부 시도 기록의 형식을 확인해 주세요.')
                if paid>=3:raise OutcomeUnknown('루비 기부 3회 시도 기록 / 추가 기부 보류')
                from donation_evidence import counter_frame,changed_counter,correlation
                before=None
                def reserve():
                    nonlocal before
                    before=counter_frame(self.last_image)
                    self.daily_checkpoint('uncertain',pending='donate_50',values={'donation_paid':paid+1})
                self.daily_reward_seen=False
                self.daily_tap(screen,'donate_50',before_input=reserve)
                # The donation dialog remains open between paid donations. A
                # newly observed reward overlay (or final donated badge) is evidence.
                end=self.now()+15;previous=None;stable=0
                while True:
                    # Counter-change evidence must come from new observations,
                    # never repeated access to a cached page confirmation.
                    self.forget_observations()
                    returned=self.daily_wait({'daily_guild_menu','daily_donate'},timeout=max(1,end-self.now()))
                    if self.daily_reward_seen or self.daily_has(returned,'guild_donated'):break
                    changed=changed_counter(before,counter_frame(self.last_image)) if returned.state=='daily_donate' else None
                    stable=stable+1 if changed is not None and correlation(previous,changed)>=.97 else int(changed is not None)
                    previous=changed
                    if stable>=2:
                        self.trace.event('verified',evidence='donation_counter_changed');break
                    if self.now()>=end:raise OutcomeUnknown('루비 기부 보상 확인 시간 초과 / 중복 기부 보류')
                    self.pause(.25)
                verified=self.daily_ledger.get(self.daily_ident,self.daily_task,'donation_verified',self.daily_day) or 0
                self.daily_checkpoint('running',pending=None,values={'donation_verified':verified+1})
                if self.daily_has(returned,'guild_donated'):
                    self.daily_mark('donation');return
            else:raise Halt('길드 기부: 무료 또는 루비 50 버튼을 확인하지 못했습니다.')
        raise Halt('길드 기부 완료 확인이 필요합니다.')
    def daily_guild_relic(self):
        screen=self.daily_guild_page();self.daily_tap(screen,'guild_relic_open')
        screen=self.daily_ready({'daily_relic'},['relic_claim','relic_empty'])
        if self.daily_has(screen,'relic_claim'):
            self.daily_tap(screen,'relic_claim');screen=self.daily_ready({'daily_relic'},['relic_claim','relic_empty'])
        else:self.progress('길드: 성물 보상 / 이미 수령')
        if not self.daily_has(screen,'relic_empty'):raise Halt('길드 성물 수령 완료 확인이 필요합니다.')
        self.daily_mark('relic');self.daily_tap(screen,'relic_close');self.daily_wait({'daily_guild_menu'})
    def daily_guild_shop(self):
        screen=self.daily_guild_page();self.daily_tap(screen,'guild_shop_open');screen=self.daily_wait({'daily_shop'})
        if self.daily_has(screen,'shop_coin') and self.daily_has(screen,'shop_free'):
            self.daily_tap(screen,'shop_free');screen=self.daily_wait({'daily_shop','daily_shop_confirm'})
            if screen.state=='daily_shop_confirm':
                screen=self.daily_ready({'daily_shop_confirm'},['shop_confirm_free'])
                self.daily_tap(screen,'shop_confirm_free',required=('shop_confirm_title','shop_confirm_item','shop_confirm_close'))
                screen=self.daily_wait({'daily_shop'})
        elif self.daily_has(screen,'shop_cube') and self.daily_has(screen,'shop_contract'):
            self.progress('길드: 상점 무료 코인 / 이미 수령')
        if not (self.daily_has(screen,'shop_cube') and self.daily_has(screen,'shop_contract')):
            raise Halt('길드 상점 무료 코인 수령 확인이 필요합니다.')
        self.daily_mark('shop')
    def daily_guild_dungeon(self):
        screen=self.daily_guild_page(battle=True);self.daily_tap(screen,'guild_dungeon_open')
        for _ in range(12):
            screen=self.daily_ready({'daily_guild_dungeon'},['guild_count_'+str(n) for n in range(4)])
            if self.daily_has(screen,'guild_count_0'):
                self.progress('길드: 길드 던전 / 입장 횟수 없음');claimed=False
                if not self.daily_has(screen,'guild_loot_zero'):
                    if not any(self.daily_has(screen,'guild_loot_'+str(n)) for n in (10,20,30)):
                        raise Halt('길드 전리품 개수 확인이 필요합니다.')
                    self.daily_tap(screen,'guild_loot_claim');claimed=True;screen=self.daily_wait({'daily_guild_dungeon'})
                if not self.daily_has(screen,'guild_loot_zero'):raise Halt('길드 전리품 수령 완료 확인이 필요합니다.')
                self.progress('길드: 던전 전리품 / '+('수령 완료' if claimed else '이미 수령'))
                self.daily_mark('dungeon');return
            if not any(self.daily_has(screen,'guild_count_'+str(n)) for n in (1,2,3)):
                raise Halt('길드 던전 남은 도전 횟수 확인이 필요합니다.')
            counter=next('guild_count_'+str(n) for n in (1,2,3) if self.daily_has(screen,'guild_count_'+str(n)))
            if not self.daily_committed_tap(screen,'guild_fight',required=(counter,)):continue
            self.daily_combat({'daily_guild_dungeon'})
            self.daily_confirm_input()
        raise Halt('길드 던전 완료 확인이 필요합니다.')
    def daily_guild_raid(self):
        status=self.daily_ledger.get(self.daily_ident,self.daily_task,'raid',self.daily_day)
        if status=='started':raise OutcomeUnknown('공방 약탈 시작 기록이 있지만 결과 확인이 없습니다. 중복 전투를 보류합니다.')
        screen=self.daily_guild_page(battle=True)
        self.daily_tap(screen,'guild_raid_open');screen=self.daily_wait({'daily_raid_map'})
        # Names rotate weekly. Confirm the generic workshop label in the
        # middle banner, then select its center independently of name/length.
        self.daily_tap(screen,point=(500,352),required=('raid_center',));screen=self.daily_wait({'daily_raid_detail'})
        def reserve():self.daily_checkpoint('uncertain',pending='raid_fight',values={'raid':'started'})
        self.daily_tap(screen,'raid_fight',before_input=reserve)
        screen,result=self.daily_combat({'daily_raid_map','daily_raid_detail'},on_result=lambda:self.daily_mark('raid'))
        if not result:raise OutcomeUnknown('공방 약탈 결과를 확인하지 못했습니다. 중복 전투를 보류합니다.')
