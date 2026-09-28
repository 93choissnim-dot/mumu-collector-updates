"""Exercise actual route, ledger, observations and fresh-input guard at device/vision boundaries."""
from pathlib import Path
import tempfile,threading,unittest
import numpy as np
from collector import Halt
from daily_state import DailyLedger,korea_day
from extra_collector import ExtraCollector
from vision import Match,Screen
from run_control import ResumeRecognition


class CompletionHandoffTests(unittest.TestCase):
    def run_guild(self,mode='flicker',*,unconfirmed=False,resume=False,blocked_reason=None,prior_pending=None):
        def screen(state,*keys):
            return Screen(state,{'daily_'+k:Match('daily_'+k,1,0,(100,100) if k=='guild_dungeon_open' else (700,400)) for k in keys})
        class Device:
            clock=0;opened=False;reads=0;claims=0;current=None;interrupted=False
            stop=threading.Event()
            def capture(d):
                d.clock+=.08
                if resume and d.claims and not d.interrupted:
                    d.interrupted=True;raise ResumeRecognition()
                if not d.opened:d.current=screen('daily_guild_battle','guild_dungeon_open')
                else:
                    d.reads+=1
                    loot=('guild_loot_30',)
                    if (mode=='flicker' and d.reads<=2) or (mode=='oscillate' and d.reads%2):loot+=('guild_loot_available',)
                    if mode=='unknown' or (mode=='transient' and d.reads<=2):loot=()
                    if mode=='zero' or (mode=='disappears' and d.reads>=3) or (d.claims and not unconfirmed):loot=('guild_loot_zero',)
                    d.current=screen('daily_guild_dungeon','guild_count_0','guild_loot_claim',*loot)
                    if mode=='stop' and d.reads==2:d.stop.set()
                return np.zeros((540,960,3),np.uint8)
            def click(d,point):
                if not d.opened:
                    assert point==(100,100);d.opened=True
                else:
                    assert point==(700,400);d.claims+=1
                    if d.claims>1:raise AssertionError('duplicate loot claim')
        d=Device();d.stop=threading.Event()
        class Recognizer:
            def recognize(self,image):return d.current
        with tempfile.TemporaryDirectory() as tmp:
            c=ExtraCollector(d,Recognizer(),d.stop,lambda _:None)
            c.now=lambda:d.clock;c.pause=lambda n:setattr(d,'clock',d.clock+n)
            c.daily_ledger=DailyLedger(Path(tmp)/'daily.json');c.daily_ident='synthetic'
            c.daily_day=korea_day();c.daily_task='daily_guild';c.daily_step='dungeon'
            c.daily_performed=False;c.daily_reward_seen=False
            c.daily_guild_page=lambda **_:c.daily_wait({'daily_guild_battle'})
            if blocked_reason:
                c.daily_checkpoint('blocked',reason=blocked_reason,failures=2,
                                   guild_dungeon_rule_revision=2,pending=prior_pending)
            error=None
            try:
                if blocked_reason:c.daily_run_step('dungeon','guild',c.daily_guild_dungeon)
                else:c.daily_guild_dungeon()
            except ResumeRecognition:
                d.opened=False;c.forget_observations()
                try:c.daily_guild_dungeon()
                except Halt as exc:error=exc
            except Halt as exc:error=exc
            d.detail=c.daily_detail()
            return d,c.daily_done('dungeon'),error

    def test_disappearing_notification_uses_confirmed_positive_count(self):
        d,done,error=self.run_guild()
        self.assertIsNone(error);self.assertTrue(done);self.assertEqual(d.claims,1)

    def test_continuously_flickering_notification_does_not_hide_stable_count(self):
        d,done,error=self.run_guild('oscillate')
        self.assertIsNone(error);self.assertTrue(done);self.assertEqual(d.claims,1)

    def test_transient_unknown_count_is_reobserved(self):
        d,done,error=self.run_guild('transient')
        self.assertIsNone(error);self.assertTrue(done);self.assertEqual(d.claims,1)

    def test_unknown_loot_does_not_block_exhausted_entry_claim(self):
        d,done,error=self.run_guild('unknown')
        self.assertIsNone(error);self.assertTrue(done);self.assertEqual(d.claims,1);self.assertLess(d.clock,35)

    def test_zero_loot_does_not_block_visible_claim_button(self):
        d,done,error=self.run_guild('zero')
        self.assertIsNone(error);self.assertTrue(done);self.assertEqual(d.claims,1)

    def test_loot_count_disappearing_before_input_does_not_block_claim(self):
        d,done,error=self.run_guild('disappears')
        self.assertIsNone(error);self.assertTrue(done);self.assertEqual(d.claims,1)

    def test_unconfirmed_claim_is_never_replayed_or_marked_done(self):
        d,done,error=self.run_guild(unconfirmed=True)
        self.assertIsNotNone(error);self.assertFalse(done);self.assertEqual(d.claims,1)

    def test_pause_after_dispatch_never_replays_unconfirmed_claim(self):
        d,done,error=self.run_guild('positive',unconfirmed=True,resume=True)
        self.assertIsNotNone(error);self.assertFalse(done);self.assertEqual(d.claims,1)
        self.assertEqual(d.detail.get('pending'),'guild_loot_claim')

    def test_pause_after_dispatch_resolves_claim_only_with_zero(self):
        d,done,error=self.run_guild('positive',resume=True)
        self.assertIsNone(error);self.assertTrue(done);self.assertEqual(d.claims,1)
        self.assertIsNone(d.detail.get('pending'))
        history=d.detail.get('input_history',[])
        self.assertTrue(any(x['request']['action']=='guild_loot_claim' and x['resolution']['confirmed'] for x in history))

    def test_diagnosed_old_blocks_reopen_without_pending(self):
        for reason in ('일일 작업 버튼 확인 시간 초과: guild_loot_available','길드 전리품 개수 확인이 필요합니다.'):
            with self.subTest(reason=reason):
                d,done,error=self.run_guild('positive',blocked_reason=reason)
                self.assertIsNone(error);self.assertTrue(done);self.assertEqual(d.claims,1)

    def test_pending_and_unrelated_blocks_are_not_reopened(self):
        for reason,pending in [('길드 전리품 개수 확인이 필요합니다.','guild_fight'),('길드 전리품 수령 완료 확인이 필요합니다.',None)]:
            d,done,error=self.run_guild('positive',blocked_reason=reason,prior_pending=pending)
            self.assertFalse(done);self.assertEqual(d.claims,0);self.assertFalse(d.opened)
            self.assertEqual(d.detail.get('pending'),pending)

    def test_stop_prevents_claim(self):
        d,done,error=self.run_guild('stop')
        self.assertIsNotNone(error);self.assertFalse(done);self.assertEqual(d.claims,0)


if __name__=='__main__':unittest.main()
