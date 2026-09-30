"""Cooperative watch must not hide unresolved recovery or block scheduled work."""
import unittest,threading
from game_watch import GameWatch
from game_recovery import GameRecovery
import validate_game_recovery as fixtures
from validate_network_recovery import recovery
from fleet_runner import run_fleet
from run_control import RunControl
from collector import Halt

class CooperativeRecoveryTests(unittest.TestCase):
    def setup_watch(self):
        a,d,r,_=fixtures.GameRecoveryTests().setup_recovery();a.states=['unknown'];events=[]
        w=GameWatch(events.append,clock=lambda:a.tick);w.enable(True)
        def prepare(job,control):
            control.wait=lambda seconds:(setattr(a,'tick',a.tick+seconds) or control.is_set())
            a.stop=control
            fresh=GameRecovery(d,r.vision,control,lambda:None,lambda _:None,clock=lambda:a.tick)
            return fresh
        return a,d,r,w,events,prepare
    def test_timeout_then_unknown_never_reports_check_complete(self):
        a,d,r,w,events,prepare=self.setup_watch();jobs=[{'id':'a','enabled':True}]
        w.scan(jobs,prepare);a.tick=91;w.scan(jobs,prepare)
        self.assertTrue(w.failures)
        a.tick=152;w.scan(jobs,prepare)
        self.assertNotIn('감시 점검 완료',events[-1]);self.assertTrue(w.failures)
    def test_poll_returns_without_sleeping_and_resumes_with_new_object(self):
        a,d,r,w,events,prepare=self.setup_watch();jobs=[{'id':'a','enabled':True}]
        w.scan(jobs,prepare);self.assertEqual(a.tick,0);self.assertEqual(len(a.launches()),1)
        a.states=['menu'];a.tick=1;w.scan(jobs,prepare)
        a.tick=2;w.scan(jobs,prepare)
        self.assertIn('재접속 완료',events[-1]);self.assertFalse(w.startups['a']['pending'])
        self.assertEqual(len(a.launches()),1)
    def test_scheduler_does_not_wait_ninety_seconds_for_other_game(self):
        a,d,r,w,events,prepare=self.setup_watch();w.next_check['a']=59
        parent=RunControl(clock=lambda:a.tick)
        parent.wait=lambda seconds:(setattr(a,'tick',a.tick+seconds) or parent.is_set())
        calls=[]
        def execute(job,rooms):
            calls.append(a.tick)
            if len(calls)==2:parent.set()
            return {'farm':'collected'}
        run_fleet([{'id':'b','name':'B','rooms':['farm'],'minutes':1}],True,parent,threading.Event(),execute,lambda *_:None,
                  idle=lambda:w.scan([{'id':'a','enabled':True}],prepare,parent))
        self.assertEqual(calls,[0,60])
    def test_network_confirmation_not_repeated_between_poll_objects(self):
        a,d,r,taps=recovery(stuck=True)
        self.assertTrue(callable(getattr(r,'poll',None)),'poll API missing')
        self.assertIsNone(r.poll());self.assertEqual(len(taps),1)
        fresh=GameRecovery(d,r.vision,a.stop,lambda:None,lambda _:None,clock=lambda:a.tick);fresh.startup=r.startup
        a.tick=1;self.assertIsNone(fresh.poll());self.assertEqual(len(taps),1)
        a.tick=91
        with self.assertRaises(Halt):fresh.poll()
        self.assertEqual(len(taps),1)
    def test_verified_normal_after_timeout_clears_failure(self):
        a,d,r,w,events,prepare=self.setup_watch();jobs=[{'id':'a','enabled':True}]
        w.scan(jobs,prepare);a.tick=91;w.scan(jobs,prepare)
        a.states=['menu'];a.tick=152;w.scan(jobs,prepare);a.tick=153;w.scan(jobs,prepare)
        self.assertFalse(w.failures);self.assertIn('재접속 완료',events[-1])
    def test_stop_between_polls_sends_no_more_input(self):
        a,d,r,w,events,prepare=self.setup_watch();jobs=[{'id':'a','enabled':True}]
        w.scan(jobs,prepare);w.enable(False);a.tick=1;w.scan(jobs,prepare)
        self.assertEqual(len(a.launches()),1)

class PollBoundaryTests(unittest.TestCase):
    setup_watch=CooperativeRecoveryTests.setup_watch
    def test_other_app_does_not_clear_unresolved_recovery(self):
        a,d,r,w,events,prepare=self.setup_watch();jobs=[{'id':'a','enabled':True}]
        w.scan(jobs,prepare);a.tick=91;w.scan(jobs,prepare)
        a.focus='com.browser.app';a.tick=152;w.scan(jobs,prepare)
        self.assertTrue(w.failures);self.assertNotIn('감시 점검 완료',events[-1])
        self.assertEqual(len(a.launches()),1)
    def test_poll_keeps_manager_lookup_between_idle_workers(self):
        from ui_game_watch import GameWatchUI
        from types import SimpleNamespace
        from unittest.mock import patch
        app=SimpleNamespace()
        with patch('mumu_names.CatalogLookup') as lookup:
            GameWatchUI.watch_prepare(app,'adb.exe')
            GameWatchUI.watch_prepare(app,'adb.exe')
        self.assertEqual(lookup.call_count,1)

class HandoffRegressionTests(unittest.TestCase):
    def test_home_with_live_process_keeps_polling_without_backoff(self):
        a,d,r,w,events,prepare=CooperativeRecoveryTests().setup_watch();jobs=[{'id':'a','enabled':True}]
        w.scan(jobs,prepare);a.focus=fixtures.HOME;a.alive=True;a.tick=1;w.scan(jobs,prepare)
        self.assertFalse(w.failures);self.assertEqual(w.next_check['a'],2);self.assertEqual(len(a.launches()),1)
    def test_parent_idle_handoffs_keep_remaining_timeout(self):
        for direction in ('parent_to_idle','idle_to_parent'):
            with self.subTest(direction=direction):
                a,d,r,_=fixtures.GameRecoveryTests().setup_recovery();a.states=['unknown'];a.tick=0
                parent=RunControl(clock=lambda:a.tick);parent.pause();a.tick=120;parent.resume();a.tick=1000
                w=GameWatch(lambda _:None,clock=lambda:a.tick);w.enable(True)
                def prepare(control):
                    control._clock=lambda:a.tick
                    return GameRecovery(d,r.vision,control,lambda:None,lambda _:None,clock=control.clock)
                first,second=(parent,None) if direction=='parent_to_idle' else (None,parent)
                self.assertIsNone(w.perform('a',prepare,first,incremental=True))
                a.tick+=1
                self.assertIsNone(w.perform('a',prepare,second,incremental=True))
                control_clock=(parent.continuous_clock() if second is parent and hasattr(parent,'continuous_clock') else parent.clock()) if second else a.tick
                self.assertAlmostEqual(w.startups['a']['deadline']-control_clock,89)
    def test_continuous_clock_survives_clear_and_excludes_pauses(self):
        tick=[0];control=RunControl(clock=lambda:tick[0]);control.pause();tick[0]=120;control.resume()
        self.assertTrue(callable(getattr(control,'continuous_clock',None)))
        self.assertEqual(control.continuous_clock(),0)
        control.clear();self.assertEqual(control.clock(),120);self.assertEqual(control.continuous_clock(),0)
        control.pause();tick[0]=140;control.clear();self.assertEqual(control.continuous_clock(),0)
