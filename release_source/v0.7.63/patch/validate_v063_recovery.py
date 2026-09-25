"""Dispatch failures, modal resampling, and delayed guild reward handoff."""
import unittest
from unittest.mock import patch,Mock
from types import SimpleNamespace
from collector import Halt,ScreenChanged
from validate_network_recovery import recovery,network_frame

class NetworkDispatchTests(unittest.TestCase):
    def test_guard_failure_before_dispatch_can_retry_fresh_popup(self):
        a,d,r,taps=recovery();guard=d.guard_package
        d.guard_package=Mock(side_effect=Halt('focus query failed before dispatch'))
        with self.assertRaises(Halt):r.recover()
        self.assertEqual(taps,[])
        self.assertFalse(r.startup.get('network_unconfirmed'))
        d.guard_package=guard
        self.assertTrue(r.recover());self.assertEqual(len(taps),1)
    def test_possible_delivery_failure_retains_pending_confirmation(self):
        a,d,r,taps=recovery(stuck=True);click=d.click
        def uncertain(point):
            click(point)
            raise Halt('ADB result unknown after dispatch')
        d.click=uncertain
        with self.assertRaises(Halt):r.recover()
        self.assertTrue(r.startup.get('network_unconfirmed'))
        with self.assertRaises(Halt):r.recover()
        self.assertEqual(len(taps),1)
    def test_valid_padding_variant_beats_inactive_first_candidate(self):
        import network_notice as n
        original=n.match;confirm_calls=[]
        def match(panel,template,x,y):
            answer=original(panel,template,x,y)
            if x==245:
                confirm_calls.append(1)
                if len(confirm_calls)==1:return None
            return answer
        # An inward mask edge produces several valid normalizations of one modal.
        im=network_frame();im[130:131,250:710]=(120,145,160);im[405:406,250:710]=(120,145,160)
        with patch.object(n,'match',side_effect=match):result=n.network_confirm(im)
        self.assertIsNotNone(result);self.assertGreaterEqual(len(confirm_calls),2)

class WatchStatusTests(unittest.TestCase):
    def test_disable_during_failed_rescan_keeps_off_status(self):
        from game_watch import GameWatch
        events=[];w=GameWatch(events.append);w.enable(True);w.failures['a']='A / 복구 보류: old'
        def prepare(job,stop):
            w.enable(False);raise Halt('cancelled')
        w.scan([{'id':'a','enabled':True}],prepare)
        self.assertFalse(w.enabled);self.assertEqual(events[-1],'꺼짐')
    def test_healthy_job_cannot_hide_other_devices_recovery_failure(self):
        from game_watch import GameWatch
        tick=[0];events=[];watch=GameWatch(events.append,clock=lambda:tick[0]);watch.enable(True)
        jobs=[{'id':'a','name':'A','enabled':True},{'id':'b','name':'B','enabled':True}]
        def prepare(job,stop):
            if job['id']=='a':raise Halt('확인 전 화면 검증 실패')
            return SimpleNamespace(startup={},device=SimpleNamespace(package=None),attempts=0,recover=lambda:False)
        watch.scan(jobs,prepare);self.assertIn('A',events[-1]);self.assertIn('보류',events[-1])
        tick[0]=20;watch.scan(jobs,prepare);self.assertIn('A',events[-1])
        tick[0]=70
        watch.scan(jobs,lambda job,stop:SimpleNamespace(startup={},device=SimpleNamespace(package=None),attempts=0,recover=lambda:False))
        self.assertNotIn('보류',events[-1])

class DonationReturnTests(unittest.TestCase):
    def test_late_reward_during_close_is_reobserved_without_another_donation(self):
        from validate_daily_execution import DailyExecutionTests,screen
        fixture=DailyExecutionTests();fixture.setUp();self.addCleanup(fixture.tearDown)
        c=fixture.c;c.daily_task='daily_guild';c.daily_step='donation';c.daily_guild_page=Mock()
        c.daily_wait=Mock(side_effect=[screen('daily_donate','donate_50'),screen('daily_donate','donate_50'),screen('daily_guild_menu')])
        c.daily_tap=Mock(side_effect=[ScreenChanged('late reward'),None]);c.pause=Mock()
        c.daily_guild_donation()
        self.assertTrue(c.daily_done('donation'))
        self.assertEqual([x.args[1] for x in c.daily_tap.call_args_list],['donate_close','donate_close'])

class EntryHandoffTests(unittest.TestCase):
    def test_entry_is_rechecked_after_grant_and_never_repeated_after_timeout(self):
        from validate_daily_execution import DailyExecutionTests,screen
        fixture=DailyExecutionTests();fixture.setUp();self.addCleanup(fixture.tearDown)
        c=fixture.c;tick=[0.];calls=[]
        c.pause=lambda n:tick.__setitem__(0,tick[0]+n)
        c.daily_find_dungeon=Mock(return_value=screen('daily_room_treasure'))
        free=screen('daily_room_treasure','d_free_1','d_count_0')
        ready=screen('daily_room_treasure','d_enter','d_free_0')
        c.daily_ready=Mock(side_effect=[free,ready]);c.daily_wait_marker=Mock(return_value=ready)
        c.daily_try_tap=Mock(return_value=True)
        def enter(observed,key):
            self.assertGreaterEqual(tick[0],1.25)
            calls.append(key);c.daily_checkpoint('uncertain',pending=key);return True
        c.daily_committed_tap=enter;c.daily_combat=Mock(side_effect=Halt('전투 시작 시간 초과'))
        with self.assertRaises(Halt):c.daily_dungeon('treasure')
        self.assertEqual(calls,['d_enter']);self.assertEqual(c.daily_detail()['pending'],'d_enter')
        c.daily_ready=Mock(return_value=ready)
        with self.assertRaises(Halt):c.daily_dungeon('treasure')
        self.assertEqual(calls,['d_enter'])

if __name__=='__main__':unittest.main()
