"""Watch cancellation, launch budget, scheduler ownership and download identity."""
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from run_control import RunControl,ResumeRecognition
from collector import Halt
import validate_game_recovery as fixtures
GAME=fixtures.GAME;HOME=fixtures.HOME

class WatchTests(unittest.TestCase):
    def service(self):
        from game_watch import GameWatch
        self.now=0;self.events=[]
        return GameWatch(lambda text:self.events.append(text),clock=lambda:self.now)
    def test_disabled_watch_does_not_query_or_launch(self):
        w=self.service();calls=[]
        w.scan([{'id':'a','enabled':True}],lambda *args:calls.append(args))
        self.assertEqual(calls,[])
    def test_idle_watch_launches_without_collection_and_throttles(self):
        w=self.service();w.enable(True);a,d,r,_=fixtures.GameRecoveryTests().setup_recovery()
        def prepare(job,stop):a.stop=stop;r.stop=stop;return r
        w.scan([{'id':'a','enabled':True}],prepare)
        self.assertEqual(len(a.launches()),1)
        a.focus=HOME;a.alive=False
        w.scan([{'id':'a','enabled':True}],prepare)
        self.assertEqual(len(a.launches()),1)
    def test_disabled_profile_never_restarts(self):
        w=self.service();w.enable(True);calls=[]
        w.scan([{'id':'a','enabled':False}],lambda *args:calls.append(args));self.assertEqual(calls,[])
    def test_pause_and_stop_parent_refuse_launch(self):
        w=self.service();w.enable(True);parent=RunControl();parent.pause();calls=[]
        w.scan([{'id':'a','enabled':True}],lambda *args:calls.append(args),parent)
        parent.set();self.now=20
        w.scan([{'id':'a','enabled':True}],lambda *args:calls.append(args),parent)
        self.assertEqual(calls,[])
    def test_off_during_slow_query_cancels_next_input(self):
        w=self.service();w.enable(True);a,d,r,_=fixtures.GameRecoveryTests().setup_recovery()
        def prepare(job,stop):
            a.stop=stop;r.stop=stop;w.enable(False);return r
        w.scan([{'id':'a','enabled':True}],prepare)
        self.assertEqual(a.launches(),[])
    def test_launch_budget_survives_fresh_recovery_objects(self):
        w=self.service();w.enable(True);launches=[]
        def prepare(job,stop):
            a,d,r,_=fixtures.GameRecoveryTests().setup_recovery();a.states=['menu'];a.stop=stop;r.stop=stop
            original=a.run
            def run(args,**kw):
                if 'start' in args:launches.append(args)
                return original(args,**kw)
            a.run=run
            return r
        for second in (0,20,40):
            self.now=second;w.scan([{'id':'a','enabled':True}],prepare)
        self.assertEqual(len(launches),2)
    def test_parent_pause_between_verification_and_input_blocks_input(self):
        from game_watch import WatchControl
        parent=RunControl();control=WatchControl(parent);old=control.generation;parent.pause()
        with self.assertRaises((Halt,ResumeRecognition)):
            with control.input_guard(control.generation):self.fail('input dispatched while paused')
        parent.resume()
        control.checkpoint()
        with self.assertRaises((Halt,ResumeRecognition)):
            with control.input_guard(old):self.fail('stale input after resume')
    def test_scheduler_wait_hook_does_not_change_due_time(self):
        from fleet_runner import run_fleet
        from run_control import RunControl
        tick=[0];stop=RunControl(clock=lambda:tick[0]);executed=[];watched=[]
        stop.wait=lambda seconds:(tick.__setitem__(0,tick[0]+seconds) or stop.is_set())
        def execute(job,rooms):
            executed.append(tick[0])
            if len(executed)==2:stop.set()
            return {'farm':'collected'}
        def idle():watched.append(tick[0])
        run_fleet([{'id':'a','name':'A','rooms':['farm'],'minutes':1}],True,stop,threading.Event(),execute,lambda *args:None,idle=idle)
        self.assertEqual(executed,[0,60]);self.assertTrue(watched)

if __name__=='__main__':unittest.main()

class PackageRecoveryTests(unittest.TestCase):
    def test_onestore_launches_same_edition_and_checks_its_process(self):
        a,d,r,_=fixtures.GameRecoveryTests().setup_recovery();edition='com.nns.genesis.onestore';d.package=edition
        original=a.run
        def run(args,**kw):
            if args[2:6]==['shell','cmd','package','resolve-activity'] and '-p' in args:
                a.calls.append(args[2:]);return (edition+'/.Main').encode()
            if args[2:5]==['shell','am','start']:
                a.calls.append(args[2:]);a.focus=edition;a.alive=True;return b'Status: ok'
            return original(args,**kw)
        a.run=run;a.states=['menu']
        self.assertTrue(r.recover());self.assertEqual(a.launches()[0][-1],edition+'/.Main')
    def test_both_installed_without_verified_edition_does_not_guess(self):
        a,d,r,_=fixtures.GameRecoveryTests().setup_recovery();d.package=None
        original=a.run
        a.run=lambda args,**kw:b'package:/data/app/base.apk' if args[2:5]==['shell','pm','path'] else original(args,**kw)
        with self.assertRaises(Halt):r.recover()
        self.assertEqual(a.launches(),[])

class FooterStabilityTests(unittest.TestCase):
    def test_unchanged_poll_does_not_hide_and_remap_resume_bar(self):
        from ui_workflow import WorkflowUI
        class Widget:
            def __init__(self):self.maps=0;self.hides=0
            def configure(self,**kw):pass
            def grid(self,**kw):self.maps+=1
            def grid_forget(self):self.hides+=1
        a=SimpleNamespace(scope_selector=Widget(),refresh_workflow=lambda:None,workflow_plan={'safe':[1],'held':[]},workflow_error='',resume_bar=Widget(),resume_hint=Widget(),resume_button=Widget(),config={},start_button=Widget(),once_button=Widget())
        WorkflowUI.sync_workflow(a,False);before=(a.resume_bar.maps,a.resume_bar.hides)
        for _ in range(20):WorkflowUI.sync_workflow(a,False)
        self.assertEqual((a.resume_bar.maps,a.resume_bar.hides),before)

class SharedWatchTests(unittest.TestCase):
    def test_collection_recovery_obeys_same_off_switch(self):
        from game_watch import GameWatch,WatchedRecovery
        watch=GameWatch(lambda _:None);calls=[]
        proxy=WatchedRecovery(watch,'a',lambda stop:calls.append(stop),RunControl())
        self.assertFalse(proxy.recover());self.assertEqual(calls,[])
    def test_turning_off_interrupts_active_collection_recovery(self):
        from game_watch import GameWatch,WatchedRecovery
        watch=GameWatch(lambda _:None);watch.enable(True);a,d,r,_=fixtures.GameRecoveryTests().setup_recovery()
        def prepare(control):
            a.stop=control;r.stop=control;watch.enable(False);return r
        proxy=WatchedRecovery(watch,'a',prepare,RunControl())
        with self.assertRaises(Halt):proxy.recover()
        self.assertEqual(a.launches(),[])
