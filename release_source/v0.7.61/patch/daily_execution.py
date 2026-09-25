"""Per-step outcomes and conservative recovery, compatible with legacy ledgers."""
import hashlib
from time import perf_counter
from collector import Halt
from daily_state import DAILY_STEPS,LedgerError,step_label

class OutcomeUnknown(Halt):
    """A resource-consuming action has no independently confirmed outcome."""

class DailyExecution:
    def daily_needs_completion_review(self,step):
        if (self.daily_task!='daily_dungeons' or
            'daily_dungeons' not in getattr(self,'manual_retry_tasks',set()) or not self.daily_done(step)):
            return False
        # An explicit retry must inspect today's available entries even if a
        # prior exhaustion observation was valid when it was recorded.
        return True
    def daily_detail(self,step=None):
        return self.daily_ledger.detail(self.daily_ident,self.daily_task,step or self.daily_step,self.daily_day)
    def daily_checkpoint(self,status,**fields):
        self.daily_ledger.checkpoint(self.daily_ident,self.daily_task,self.daily_step,status,
                                     self.daily_day,**fields)
        if hasattr(self,'trace'):self.trace.event('checkpoint',status=status,**fields)
    def daily_run_step(self,step,label,action):
        from run_control import checkpoint
        checkpoint(self.stop)
        if self.stop.is_set():raise Halt('사용자가 중지했습니다.')
        self.daily_check_day();self.daily_step=step
        if hasattr(self,'trace'):self.trace.step=step
        review=self.daily_needs_completion_review(step)
        if self.daily_done(step) and not review:
            self.progress(label+(' / 입장 횟수 없음' if self.daily_task=='daily_dungeons' or step=='dungeon' else ' / 이미 수령' if self.daily_task=='daily_guild' else ' / 이미 완료'))
            return
        prior=self.daily_detail()
        review_key=(self.daily_ident,self.daily_task,step)
        if review:
            # Preserve the old claim, but do not treat it as current evidence.
            # A retry executes through normal fresh-input guards; the separate
            # completion-review mode remains inspection-only.
            self.daily_checkpoint('pending',values={step:None,'_complete':None},
                previous_completion={'value':'done','updated_at':prior.get('updated_at'),
                                     'evidence':prior.get('completion_evidence')},
                reason='이전 완료 기록 재확인',failures=0,fingerprint='')
            if getattr(self,'daily_verification_only',False):
                reviews=getattr(self,'completion_review_steps',set())
                reviews.add(review_key);self.completion_review_steps=reviews
            prior=self.daily_detail()
        if review_key in getattr(self,'completion_review_steps',set()):
            # Resume/reconnect may restart the task after its old done flag was
            # cleared. Inspection permission survives for this collector/run.
            action=lambda:self.daily_dungeon(step,verification_only=True)
        if ((self.daily_task,step)==('daily_guild','dungeon') and prior.get('status')=='blocked'
                and prior.get('reason') in {
                    '일일 작업 버튼 확인 시간 초과: guild_count_0, guild_count_1, guild_count_2, guild_count_3',
                    '길드 전리품 개수 확인이 필요합니다.'}
                and not prior.get('pending') and prior.get('guild_dungeon_rule_revision',0)<2):
            self.daily_checkpoint('pending',failures=0,fingerprint='',guild_dungeon_rule_revision=2)
            prior=self.daily_detail()
        if (self.daily_task=='daily_pass' and prior.get('status')=='blocked'
                and prior.get('reason')=='일일 작업 버튼 확인 시간 초과: pass_'+step+'_done, pass_'+step+'_active'
                and not prior.get('pending') and prior.get('purchase_rule_revision',0)<1):
            self.daily_checkpoint('pending',failures=0,fingerprint='',purchase_rule_revision=1)
            prior=self.daily_detail()
        repaired_reason=(
            self.daily_task=='daily_dungeons' and prior.get('reason') in {
                '일일 작업 버튼 확인 시간 초과: sweep_action, sweep_free_0, sweep_free_1',
                '일일 작업 버튼 확인 시간 초과: d_enter, d_free_0, d_free_1'}
            or (self.daily_task,step)==('daily_guild','dungeon') and prior.get('reason')==
                '일일 작업: 예상 화면 daily_guild_battle / 현재 unknown / 화면 확인 시간 초과')
        if (self.daily_task=='daily_dungeons' and step in {'equipment','summon'}
                and prior.get('status')=='blocked' and not prior.get('pending')
                and prior.get('native_sweep_revision',0)<58 and prior.get('reason') in {
                    '일일 작업 버튼 확인 시간 초과: sweep_action',
                    '무료 열쇠 수령 후 소탕 화면과 버튼 확인 시간 초과'}):
            self.daily_checkpoint('pending',failures=0,fingerprint='',native_sweep_revision=58)
            prior=self.daily_detail()
        if (prior.get('status')=='blocked' and repaired_reason and not prior.get('pending')
                and prior.get('recognition_revision',0)<54):
            self.daily_checkpoint('pending',failures=0,fingerprint='',recognition_revision=54)
            prior=self.daily_detail()
        # Recheck only the old, identified relic-label failure after its rule
        # changes. Completed steps and uncertain resource inputs stay intact.
        if (self.daily_task,step)==('daily_guild','relic') and prior.get('status')=='blocked' and (
                prior.get('reason')=='일일 작업 버튼 확인 시간 초과: relic_claim, relic_empty' and
                prior.get('relic_rule_revision',0)<1 and not prior.get('pending')):
            self.daily_checkpoint('pending',failures=0,fingerprint='',relic_rule_revision=1)
            prior=self.daily_detail()
        repeatable_raid=((self.daily_task,step)==('daily_guild','raid') and (
            prior.get('pending')=='raid_fight' or
            self.daily_ledger.get(self.daily_ident,self.daily_task,step,self.daily_day)=='started'))
        if prior.get('status')=='blocked' and not repeatable_raid and not getattr(self,'daily_verification_only',False):
            self.progress(label+' / 같은 오류 반복으로 보류');return
        # Resource-consuming steps inspect uncertain outcomes; raid entry is
        # explicitly repeatable after its fresh screen and button guard.
        self.daily_checkpoint('uncertain' if prior.get('status')=='uncertain' else 'running',label=label)
        self.progress(label)
        started=perf_counter()
        work_attempts=getattr(self,'daily_work_attempts',0)
        try:
            action()
            if not self.daily_done(step):raise Halt(label+': 완료 상태를 확인하지 못했습니다.')
        except LedgerError:raise
        except Halt as exc:
            if self.stop.is_set():raise
            self.daily_check_day()
            if self.daily_done(step):
                # A missed close is a navigation failure, not lost completion.
                if self.on_issue:self.on_issue(self.daily_task,label+': 완료 후 화면 복귀 확인 필요: '+str(exc))
                self.daily_recover();return
            screen=self.last_screen
            state=getattr(screen,'state','unknown')
            reason=str(exc)
            fingerprint=hashlib.sha256((state+'|'+reason).encode()).hexdigest()[:24]
            if isinstance(exc,OutcomeUnknown) and getattr(self,'daily_work_attempts',0)==work_attempts:
                # Re-observing an unresolved old input is not another failed
                # execution. Preserve legacy counters without inflating them.
                failures=prior.get('failures',0)
            else:
                failures=prior.get('failures',0)+1 if prior.get('fingerprint')==fingerprint else 1
            status='uncertain' if isinstance(exc,OutcomeUnknown) or self.daily_detail().get('pending') else ('blocked' if failures>=2 else 'failed')
            self.daily_checkpoint(status,reason=reason,fingerprint=fingerprint,failures=failures,screen=state)
            if self.on_issue:self.on_issue(self.daily_task,label+': '+reason)
            self.progress(label+(' / 결과 확인 필요' if status=='uncertain' else ' / 확인 필요'))
            # No ESC or guessed close point on unknown, modal or combat screens.
            self.daily_recover()
        finally:
            if hasattr(self,'trace'):self.trace.event('step_end',elapsed_seconds=round(perf_counter()-started,3))
    def daily_recover(self):
        screen=self.daily_wait(self.daily_recovery_pages(),timeout=6)
        if self.daily_task=='daily_dungeons':
            if screen.state=='daily_sweep':
                self.daily_tap(screen,'sweep_close')
                screen=self.daily_wait({'daily_room_'+k for k in DAILY_STEPS['daily_dungeons']},timeout=8)
            if screen.state.startswith('daily_room_'):
                self.daily_tap(screen,'d_close')
                screen=self.daily_wait({'daily_dungeons'},timeout=8)
            if screen.state=='daily_dungeons':return
            raise Halt('던전 목록 복귀를 확인하지 못해 남은 작업을 보류합니다.')
        if self.daily_task=='daily_guild':
            # Keep recovery inside the guild so later steps remain available.
            # Returning home here can introduce unrelated offer popups.
            self.daily_guild_page();return
        self.daily_main()
    def daily_recovery_pages(self):
        if self.daily_task=='daily_dungeons':
            return {'daily_dungeons','daily_sweep'}|{'daily_room_'+k for k in DAILY_STEPS['daily_dungeons']}
        if self.daily_task=='daily_pass':return {'main','menu'}|{'daily_pass_'+k for k in ('ad','keys','gear')}
        return {'main','menu','daily_guild_menu','daily_guild_battle','daily_donate','daily_relic',
                'daily_shop','daily_shop_confirm','daily_guild_dungeon','daily_raid_map','daily_raid_detail'}
    def daily_outcome(self):
        missing=[step for step in DAILY_STEPS[self.daily_task] if not self.daily_done(step)]
        if not missing:return None
        details=[self.daily_detail(step) for step in missing]
        self.daily_summary=' / '.join((d.get('label') or step_label(self.daily_task,step))+': '+(d.get('reason') or '미실행') for step,d in zip(missing,details))
        return 'deferred' if all(d.get('status') in {'blocked','uncertain'} for d in details) else 'failed'
