"""Daily routes. Every input is bound to a freshly confirmed game screen."""
from collector import Halt
from daily_state import korea_day,DAILY_ALREADY
from daily_vision import DUNGEONS
from task_catalog import TOP_BAR_POINTS

DUNGEON_NAMES=dict(zip(DUNGEONS,('장비 보급소','소환 던전','스톤 채굴장','룬 동굴','유물 던전','보물 창고','아티팩트 공방')))
SWEEP_DUNGEONS=frozenset(('equipment','summon'))
WORK_BUTTONS={'pass_'+k+'_active' for k in ('ad','keys','gear')}|{
    'sweep_action','d_enter','donate_free','donate_50','relic_claim','shop_free',
    'guild_fight','guild_loot_claim','raid_fight'}
DAILY_PAGES={'daily_pass_'+k for k in ('ad','keys','gear')}|{'daily_room_'+k for k in DUNGEONS}|{
    'daily_dungeons','daily_sweep','daily_guild_menu','daily_guild_battle','daily_donate',
    'daily_relic','daily_shop','daily_guild_dungeon','daily_raid_map','daily_raid_detail'}

class DailyActions:
    def daily_check_day(self):
        if korea_day()!=self.daily_day:raise Halt('KST 자정이 지나 일일 작업을 다시 예약합니다. 완료한 기록은 이전 날짜로 유지됩니다.')
    def daily_has(self,screen,key):return 'daily_'+key in screen.matches
    def daily_done(self,step):return self.daily_ledger.done(self.daily_ident,self.daily_task,step,self.daily_day)
    def daily_mark(self,step,value='done'):
        self.daily_ledger.mark(self.daily_ident,self.daily_task,step,value,self.daily_day)
    def daily_wait(self,states,timeout=40):
        end=self.now()+timeout;prior=None;count=0;overlays={}
        while self.now()<end:
            self.daily_check_day();screen=self.screen()
            if self.dismiss_overlay(screen,overlays):
                if screen.state=='reward':self.daily_reward_seen=True
                prior=None;count=0;self.pause(.25);continue
            # Each new overlay gets its own bounded dismissal budget.
            overlays={}
            if screen.state in states:
                count=count+1 if screen.state==prior else 1
                if count>=2:return screen
            else:count=0
            prior=screen.state;self.pause(.25)
        raise Halt('일일 작업: 다음 화면을 확인하지 못했습니다. 완료 기록은 유지됩니다.')
    def daily_ready(self,states,keys,timeout=25):
        end=self.now()+timeout;last=None;count=0
        while self.now()<end:
            screen=self.daily_wait(states,timeout=max(1,end-self.now()))
            active=tuple(k for k in keys if self.daily_has(screen,k))
            count=count+1 if active and active==last else int(bool(active));last=active
            if count>=2:return screen
            self.pause(.2)
        raise Halt('일일 작업 버튼 상태가 안정되지 않았습니다. 다음 재시도에서 이어갑니다.')
    def daily_wait_marker(self,states,key,timeout=25):
        end=self.now()+timeout
        while self.now()<end:
            screen=self.daily_wait(states,timeout=max(1,end-self.now()))
            if self.daily_has(screen,key):return screen
            self.pause(.25)
        raise Halt('무료 열쇠 수령 후 입장 횟수가 갱신되지 않았습니다.')
    def daily_tap(self,screen,key=None,point=None,*,work=False):
        self.daily_check_day()
        # Verify the actionable marker again; never trust stale button colors.
        fresh=self.screen()
        if fresh.state!=screen.state:raise Halt('일일 작업: 화면이 바뀌어 클릭을 보류합니다.')
        if key:
            name='daily_'+key
            if name not in screen.matches or name not in fresh.matches:raise Halt('일일 작업 버튼 확인 실패: '+key)
            point=fresh.matches[name].center
        if point is None:raise Halt('일일 작업 클릭 위치가 없습니다.')
        self.device.click(point)
        if work or key in WORK_BUTTONS:self.daily_performed=True
        self.pause(.65)
    def daily_main(self):
        screen=self.daily_wait(DAILY_PAGES|{'main','menu'})
        for _ in range(4):
            if screen.state=='main':return screen
            if screen.state=='menu':self.daily_tap(screen,point=(915,28))
            elif screen.state=='daily_sweep':self.daily_tap(screen,'sweep_close')
            elif screen.state=='daily_donate':self.daily_tap(screen,'donate_close')
            elif screen.state=='daily_relic':self.daily_tap(screen,'relic_close')
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
        self.daily_tap(main,point=points[key]);return self.daily_wait(states)
    def daily_combat(self,return_states,timeout=240,on_result=None):
        end=self.now()+timeout;last=None;count=0;skipped=False;overlays={};result=False
        while self.now()<end:
            self.daily_check_day();screen=self.screen()
            if self.dismiss_overlay(screen,overlays):
                self.pause(.25);continue
            overlays={};count=count+1 if last==screen.state else 1;last=screen.state
            if count<2:self.pause(.25);continue
            if screen.state=='daily_result':
                if not result and on_result:on_result()
                result=True
            elif screen.state=='daily_clear':self.daily_tap(screen,'battle_leave')
            elif screen.state=='daily_battle' and not skipped:
                key='raid_skip' if self.daily_has(screen,'raid_skip') else 'battle_skip'
                self.daily_tap(screen,key);skipped=True
            elif screen.state in return_states:
                return screen,result
            self.pause(.3)
        raise Halt('전투 종료 화면 확인 시간 초과 / 같은 전투를 임의로 다시 시작하지 않습니다.')
    def collect_daily(self,task):
        if not hasattr(self,'daily_ledger'):raise Halt('일일 완료 기록 연결이 없습니다.')
        self.daily_task=task;self.daily_day=korea_day();self.daily_reward_seen=False;self.daily_performed=False
        if self.daily_done('_complete'):return self.record_task(task,DAILY_ALREADY[task])
        {'daily_pass':self.daily_pass,'daily_dungeons':self.daily_dungeons,'daily_guild':self.daily_guild}[task]()
        self.daily_check_day();self.daily_mark('_complete')
        return self.record_task(task,'collected' if self.daily_performed else DAILY_ALREADY[task])
    def daily_pass(self):
        pages={'daily_pass_'+k for k in ('ad','keys','gear')}
        self.daily_open('pass',pages)
        for key,y in [('ad',90),('keys',148),('gear',204)]:
            title='패스 수령: '+{'ad':'광고 제거','keys':'던전 멤버십','gear':'장비 멤버십'}[key]
            if self.daily_done(key):self.progress(title+' / 이미 완료');continue
            self.progress(title)
            screen=self.daily_wait(pages)
            if screen.state!='daily_pass_'+key:
                self.daily_tap(screen,point=(68,y));screen=self.daily_wait({'daily_pass_'+key})
            for attempt in range(3):
                screen=self.daily_ready({'daily_pass_'+key},['pass_'+key+'_done','pass_'+key+'_active'])
                if self.daily_has(screen,'pass_'+key+'_done'):
                    self.progress(title+(' / 이미 완료' if attempt==0 else ' / 수령 완료'))
                    self.daily_mark(key);break
                if self.daily_has(screen,'pass_'+key+'_active'):
                    self.daily_tap(screen,'pass_'+key+'_active')
                else:raise Halt('패스 수령: 보유 여부 또는 수령 버튼 확인이 필요합니다.')
            else:raise Halt('패스 수령 완료를 확인하지 못했습니다.')
        self.daily_main()
    def daily_find_dungeon(self,key):
        screen=self.daily_wait({'daily_dungeons'})
        for direction in (-1,1):
            for _ in range(4):
                if self.daily_has(screen,'card_'+key):
                    self.daily_tap(screen,'card_'+key);return self.daily_wait({'daily_room_'+key})
                self.daily_check_day();fresh=self.screen()
                if fresh.state!='daily_dungeons':raise Halt('던전 목록이 바뀌었습니다.')
                self.device.drag((800,290),(240,290)) if direction==-1 else self.device.drag((240,290),(800,290))
                self.pause(.8);screen=self.daily_wait({'daily_dungeons'})
        raise Halt(DUNGEON_NAMES[key]+': 던전 카드를 찾지 못했습니다.')
    def daily_dungeons(self):
        self.daily_open('dungeon',{'daily_dungeons'})
        for key in DUNGEONS:
            if self.daily_done(key):self.progress('1일 던전: '+DUNGEON_NAMES[key]+' / 입장 횟수 없음');continue
            self.progress('1일 던전: '+DUNGEON_NAMES[key]+(' / 소탕' if key in SWEEP_DUNGEONS else ' / 입장'))
            page='daily_room_'+key;screen=self.daily_find_dungeon(key)
            if key in SWEEP_DUNGEONS:
                self.daily_tap(screen,'d_sweep_open');screen=self.daily_wait({'daily_sweep'})
                for _ in range(16):
                    screen=self.daily_ready({'daily_sweep'},['sweep_action','sweep_free_0','sweep_free_1'])
                    if self.daily_has(screen,'sweep_count_0') and self.daily_has(screen,'sweep_free_0'):
                        self.progress('1일 던전: '+DUNGEON_NAMES[key]+' / 입장 횟수 없음')
                        self.daily_mark(key);break
                    if self.daily_has(screen,'sweep_free_1') and self.daily_has(screen,'sweep_count_0'):
                        self.daily_tap(screen,point=(480,382),work=True)
                        self.daily_wait_marker({'daily_sweep'},'sweep_action')
                    elif self.daily_has(screen,'sweep_action'):
                        self.daily_tap(screen,'sweep_action')
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
                    if zero and self.daily_has(screen,'d_free_1'):
                        self.daily_tap(screen,point=(744,440),work=True)
                        self.daily_wait_marker({page},'d_enter');continue
                    if self.daily_has(screen,'d_enter'):
                        self.daily_tap(screen,'d_enter');screen,_=self.daily_combat({page})
                    else:raise Halt(DUNGEON_NAMES[key]+': 입장 횟수 또는 무료 열쇠 확인이 필요합니다.')
                else:raise Halt(DUNGEON_NAMES[key]+': 입장 횟수 확인이 필요합니다.')
            self.daily_tap(screen,'d_close');self.daily_wait({'daily_dungeons'})
        self.daily_main()
    def daily_guild_root(self):return self.daily_open('guild',{'daily_guild_menu','daily_guild_battle'})
    def daily_guild(self):
        for step,label in [('attendance','출석'),('donation','기부'),('relic','성물 보상'),('shop','상점 무료 코인'),('dungeon','길드 던전'),('raid','공방 약탈')]:
            if self.daily_done(step):self.progress('길드: '+label+(' / 입장 횟수 없음' if step=='dungeon' else ' / 이미 수령'))
        screen=self.daily_guild_root()
        if screen.state!='daily_guild_menu':
            self.daily_tap(screen,point=(385,75));screen=self.daily_wait({'daily_guild_menu'})
        if not self.daily_done('attendance'):
            if not self.daily_has(screen,'guild_attended'):
                self.daily_tap(screen,point=(78,478),work=True);screen=self.daily_wait({'daily_guild_menu'})
            else:self.progress('길드: 출석 / 이미 수령')
            if not self.daily_has(screen,'guild_attended'):raise Halt('길드 출석 완료 확인이 필요합니다.')
            self.daily_mark('attendance')
        if not self.daily_done('donation'):
            self.progress('길드: 무료 기부 및 루비 50 기부')
            for _ in range(5):
                screen=self.daily_wait({'daily_guild_menu','daily_donate'})
                if screen.state=='daily_guild_menu':
                    if self.daily_has(screen,'guild_donated'):
                        if _==0:self.progress('길드: 기부 / 이미 수령')
                        self.daily_mark('donation');break
                    self.daily_tap(screen,'guild_donate_open');screen=self.daily_wait({'daily_donate'})
                if self.daily_has(screen,'donate_free'):self.daily_tap(screen,'donate_free')
                elif self.daily_has(screen,'donate_50'):
                    paid=self.daily_ledger.get(self.daily_ident,self.daily_task,'donation_paid',self.daily_day) or 0
                    if paid>=3:raise Halt('길드 기부: 오늘 루비 50 기부 3회 한도에 도달했습니다.')
                    self.daily_mark('donation_paid',paid+1)
                    self.daily_tap(screen,'donate_50')
                else:raise Halt('길드 기부: 무료 또는 루비 50 버튼을 확인하지 못했습니다.')
            else:raise Halt('길드 기부 완료 확인이 필요합니다.')
        screen=self.daily_wait({'daily_guild_menu'})
        if not self.daily_done('relic'):
            self.progress('길드: 성물 보상 수령');self.daily_tap(screen,'guild_relic_open')
            screen=self.daily_ready({'daily_relic'},['relic_claim','relic_empty'])
            if self.daily_has(screen,'relic_claim'):
                self.daily_reward_seen=False;self.daily_tap(screen,'relic_claim');screen=self.daily_ready({'daily_relic'},['relic_claim','relic_empty'])
            elif self.daily_has(screen,'relic_empty'):self.progress('길드: 성물 보상 / 이미 수령')
            if not self.daily_has(screen,'relic_empty'):raise Halt('길드 성물 수령 완료 확인이 필요합니다.')
            self.daily_mark('relic');self.daily_tap(screen,'relic_close');screen=self.daily_wait({'daily_guild_menu'})
        if not self.daily_done('shop'):
            self.progress('길드: 상점 무료 코인');self.daily_tap(screen,'guild_shop_open');screen=self.daily_wait({'daily_shop'})
            if self.daily_has(screen,'shop_coin') and self.daily_has(screen,'shop_free'):
                self.daily_tap(screen,'shop_free');screen=self.daily_wait({'daily_shop'})
            elif self.daily_has(screen,'shop_cube') and self.daily_has(screen,'shop_contract'):
                self.progress('길드: 상점 무료 코인 / 이미 수령')
            if not (self.daily_has(screen,'shop_cube') and self.daily_has(screen,'shop_contract')):
                raise Halt('길드 상점 무료 코인 수령 확인이 필요합니다.')
            self.daily_mark('shop');screen=self.daily_guild_root()
        if not self.daily_done('dungeon') or not self.daily_done('raid'):
            if screen.state!='daily_guild_battle':
                self.daily_tap(screen,'guild_battle_tab');screen=self.daily_wait({'daily_guild_battle'})
        if not self.daily_done('dungeon'):
            self.progress('길드: 길드 던전');self.daily_tap(screen,'guild_dungeon_open')
            for _ in range(5):
                screen=self.daily_wait({'daily_guild_dungeon'})
                if self.daily_has(screen,'guild_count_0'):
                    self.progress('길드: 길드 던전 / 입장 횟수 없음')
                    claimed_loot=False
                    if not self.daily_has(screen,'guild_loot_zero'):
                        if not any(self.daily_has(screen,'guild_loot_'+str(n)) for n in (10,20,30)):raise Halt('길드 전리품 개수 확인이 필요합니다.')
                        self.daily_tap(screen,'guild_loot_claim');claimed_loot=True;screen=self.daily_wait({'daily_guild_dungeon'})
                    if self.daily_has(screen,'guild_loot_zero'):
                        self.progress('길드: 던전 전리품 / '+('수령 완료' if claimed_loot else '이미 수령'));self.daily_mark('dungeon');break
                    raise Halt('길드 전리품 수령 완료 확인이 필요합니다.')
                if not any(self.daily_has(screen,'guild_count_'+str(n)) for n in (1,2,3)):raise Halt('길드 던전 남은 도전 횟수 확인이 필요합니다.')
                self.daily_tap(screen,'guild_fight');self.daily_combat({'daily_guild_dungeon'})
            else:raise Halt('길드 던전 완료 확인이 필요합니다.')
            screen=self.daily_guild_root()
            if screen.state!='daily_guild_battle':self.daily_tap(screen,'guild_battle_tab');screen=self.daily_wait({'daily_guild_battle'})
        if not self.daily_done('raid'):
            self.progress('길드: 공방 약탈')
            status=self.daily_ledger.get(self.daily_ident,self.daily_task,'raid',self.daily_day)
            if status=='started':raise Halt('공방 약탈 시작 기록이 있지만 결과 확인이 없습니다. 중복 전투를 막기 위해 이번 작업을 보류합니다.')
            self.daily_tap(screen,'guild_raid_open');screen=self.daily_wait({'daily_raid_map'})
            self.daily_tap(screen,'raid_center');screen=self.daily_wait({'daily_raid_detail'})
            self.daily_mark('raid','started');self.daily_tap(screen,'raid_fight')
            screen,result=self.daily_combat({'daily_raid_map','daily_raid_detail'},on_result=lambda:self.daily_mark('raid'))
            if not result:raise Halt('공방 약탈 결과를 확인하지 못했습니다.')
        self.daily_main()
