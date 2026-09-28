"""Exhausted guild entries authorize one claim without loot-count evidence."""
from pathlib import Path
import tempfile,threading,unittest
import cv2,numpy as np
from collector import Halt
from daily_state import DailyLedger,korea_day
from extra_collector import ExtraCollector
from vision import Match,Screen,Vision
from run_control import ResumeRecognition

class GuildLootRuleTests(unittest.TestCase):
    def route(self,*,loot=None,outcome='reward',entries=0,changed_entry=False,stop=False,
              blocked=False,pending=False,resume=False,stale_reward=False):
        class Device:
            clock=0;opened=False;claims=0;closed=False;reads=0;current=None;interrupted=False
            def capture(d):
                d.clock+=.08
                if resume and d.claims and not d.interrupted:
                    d.interrupted=True;raise ResumeRecognition()
                if not d.opened:state='daily_guild_battle';keys=['guild_dungeon_open']
                elif d.claims and outcome=='reward' and not d.closed:
                    state='reward';keys=['reward_close']
                else:
                    d.reads+=1;state='daily_guild_dungeon'
                    count=1 if changed_entry and d.reads>=3 else entries
                    keys=['guild_count_'+str(count),'guild_loot_claim']
                    if loot:keys.append(loot)
                    if d.claims and outcome=='zero':keys=['guild_count_0','guild_loot_zero']
                    if stop and d.reads>=3:d.stop.set()
                centers={'guild_dungeon_open':(100,100),'guild_loot_claim':(700,400),'reward_close':(640,520)}
                d.current=Screen(state,{k if k=='reward_close' else 'daily_'+k:Match(k,1,0,centers.get(k,(200,200))) for k in keys})
                return np.zeros((540,960,3),np.uint8)
            def click(d,point):
                assert not d.stop.is_set()
                if not d.opened:assert point==(100,100);d.opened=True
                elif d.current.state=='reward':assert point==(640,520);d.closed=True
                else:
                    assert point==(700,400);d.claims+=1
                    assert d.claims==1,'duplicate loot claim'
        d=Device();d.stop=threading.Event()
        class Recognizer:
            def recognize(self,image):return d.current
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'daily.json';c=ExtraCollector(d,Recognizer(),d.stop,lambda _:None)
            c.now=lambda:d.clock;c.pause=lambda n:setattr(d,'clock',d.clock+n)
            c.daily_ledger=DailyLedger(path);c.daily_ident='test';c.daily_day=korea_day()
            c.daily_task='daily_guild';c.daily_step='dungeon';c.daily_reward_seen=stale_reward;c.daily_performed=False
            c.daily_guild_page=lambda **_:c.daily_wait({'daily_guild_battle'})
            if pending:c.daily_checkpoint('uncertain',pending='guild_loot_claim')
            if blocked:c.daily_checkpoint('blocked',reason='일일 작업 버튼 확인 시간 초과: guild_loot_zero, guild_loot_10, guild_loot_20, guild_loot_30, guild_loot_available',failures=2,guild_loot_rule_revision=64)
            error=None
            try:
                if blocked:c.daily_run_step('dungeon','길드 던전',c.daily_guild_dungeon)
                else:c.daily_guild_dungeon()
            except ResumeRecognition:
                c.daily_ledger=DailyLedger(path);d.opened=False;c.forget_observations()
                try:c.daily_guild_dungeon()
                except Halt as exc:error=exc
            except Halt as exc:error=exc
            return d,c.daily_done('dungeon'),c.daily_detail(),error

    def test_native_fresh_guard_claims_without_loot_number(self):
        v=Vision()
        original=cv2.imdecode(np.fromfile(Path(__file__).parent/'assets/diagnostic_guild_claim_soft.png',np.uint8),1)
        x,y,r,b=v.daily.specs['guild_loot_zero']['box'];original[y:b,x:r]=110
        x,y,r,b=v.daily.specs['guild_count_0']['box'];original[y:b,x:r]=v.daily.templates['guild_count_0'][0]
        initial=v.recognize(original)
        self.assertEqual(initial.state,'daily_guild_dungeon')
        self.assertEqual({k for k in initial.matches if 'loot' in k},{'daily_guild_loot_claim'})
        for changed in (False,True):
            fresh=original.copy()
            if changed:fresh[y:b,x:r]=110
            class Device:
                def capture(self):return fresh
                def click(self,point):clicks.append(point)
            clicks=[]
            with tempfile.TemporaryDirectory() as tmp:
                c=ExtraCollector(Device(),v,threading.Event(),lambda _:None)
                c.pause=lambda _:None;c.daily_ledger=DailyLedger(Path(tmp)/'daily.json')
                c.daily_ident='native';c.daily_day=korea_day();c.daily_task='daily_guild';c.daily_step='dungeon'
                accepted=c.daily_committed_tap(initial,'guild_loot_claim',required=('guild_count_0',))
                self.assertEqual(accepted,not changed);self.assertEqual(len(clicks),int(not changed))
                self.assertEqual(c.daily_detail().get('pending'),None if changed else 'guild_loot_claim')

    def test_zero_entries_claim_without_any_loot_number_or_notification(self):
        d,done,detail,error=self.route()
        self.assertIsNone(error);self.assertTrue(done);self.assertEqual(d.claims,1)
        self.assertTrue(d.closed);self.assertIsNone(detail.get('pending'))

    def test_loot_number_never_blocks_available_claim_button(self):
        for loot in ('guild_loot_zero','guild_loot_10','guild_loot_20','guild_loot_30'):
            with self.subTest(loot=loot):
                d,done,_,error=self.route(loot=loot)
                self.assertIsNone(error);self.assertTrue(done);self.assertEqual(d.claims,1)

    def test_remaining_entry_prevents_claim(self):
        d,done,_,error=self.route(entries=1)
        self.assertIsNotNone(error);self.assertFalse(done);self.assertEqual(d.claims,0)

    def test_fresh_entry_change_prevents_claim(self):
        d,done,_,error=self.route(changed_entry=True)
        self.assertIsNotNone(error);self.assertFalse(done);self.assertEqual(d.claims,0)

    def test_stop_prevents_claim(self):
        d,done,_,error=self.route(stop=True)
        self.assertIsNotNone(error);self.assertFalse(done);self.assertEqual(d.claims,0)

    def test_stale_reward_does_not_confirm_unchanged_claim(self):
        d,done,detail,error=self.route(outcome='unchanged',stale_reward=True)
        self.assertIsNotNone(error);self.assertFalse(done);self.assertEqual(d.claims,1)
        self.assertEqual(detail.get('pending'),'guild_loot_claim')

    def test_restart_never_replays_unconfirmed_claim(self):
        d,done,detail,error=self.route(outcome='unchanged',resume=True)
        self.assertIsNotNone(error);self.assertFalse(done);self.assertEqual(d.claims,1)
        self.assertEqual(detail.get('pending'),'guild_loot_claim')

    def test_resume_preserves_claim_reward_seen_during_navigation(self):
        d,done,detail,error=self.route(resume=True,outcome='reward')
        self.assertIsNone(error);self.assertTrue(done);self.assertEqual(d.claims,1)
        self.assertTrue(d.closed);self.assertIsNone(detail.get('pending'))

    def test_old_pending_claim_is_not_repeated(self):
        d,done,detail,error=self.route(pending=True,outcome='unchanged')
        self.assertIsNotNone(error);self.assertFalse(done);self.assertEqual(d.claims,0)
        self.assertEqual(detail.get('pending'),'guild_loot_claim')

    def test_old_loot_count_block_is_reopened(self):
        d,done,_,error=self.route(blocked=True)
        self.assertIsNone(error);self.assertTrue(done);self.assertEqual(d.claims,1)

    def test_zero_after_claim_still_confirms_without_reward_popup(self):
        d,done,detail,error=self.route(outcome='zero')
        self.assertIsNone(error);self.assertTrue(done);self.assertEqual(d.claims,1)
        self.assertIsNone(detail.get('pending'))

if __name__=='__main__':unittest.main()
