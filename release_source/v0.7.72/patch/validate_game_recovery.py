"""Exact app restart boundaries, deadlines and retained uncertain actions."""
import threading
import unittest
from types import SimpleNamespace
import numpy as np
from adb_device import AdbDevice
from collector import Halt

GAME='com.nns.genesis';HOME='com.android.launcher3'
class Android:
    def __init__(self):
        self.stop=threading.Event();self.focus=HOME;self.alive=False;self.calls=[];self.states=['unknown','menu','menu'];self.tick=0
    def run(self,args,timeout=10,**kw):
        args=args[2:];self.calls.append(args)
        if args[:2]==['shell','dumpsys']:return ('mCurrentFocus=Window{1 u0 '+self.focus+'/.Main}').encode()
        if args[:3]==['shell','ps','-A']:return ('USER PID NAME\nu0 1 '+(GAME if self.alive else HOME)).encode()
        if args[:4]==['shell','cmd','package','resolve-activity']:
            return ((GAME+'/.Main') if '-p' in args else HOME+'/.Home').encode()
        if args[:3]==['shell','am','start']:
            self.focus=GAME;self.alive=True;return b'Status: ok'
        raise AssertionError(args)
    def launches(self):return [c for c in self.calls if c[:3]==['shell','am','start']]

class GameRecoveryTests(unittest.TestCase):
    def setup_recovery(self):
        from game_recovery import GameRecovery
        a=Android();d=AdbDevice(a,'127.0.0.1:16384');d.package=GAME
        d.raw_capture=lambda:np.zeros((540,960,3),np.uint8)
        def recognize(_):
            state=a.states.pop(0) if len(a.states)>1 else a.states[0]
            return SimpleNamespace(state=state,matches={})
        v=SimpleNamespace(recognize=recognize)
        a.stop.wait=lambda seconds:(setattr(a,'tick',a.tick+seconds) or a.stop.is_set())
        verified=[]
        r=GameRecovery(d,v,a.stop,lambda:verified.append(a.focus),lambda _:None,clock=lambda:a.tick)
        return a,d,r,verified
    def test_proven_exit_launches_exact_package_and_waits_for_stable_screen(self):
        a,d,r,verified=self.setup_recovery();self.assertTrue(r.recover())
        self.assertEqual(len(a.launches()),1);self.assertIn(GAME+'/.Main',a.launches()[0]);self.assertEqual(d.package,GAME)
        self.assertGreaterEqual(len(verified),3);self.assertGreater(a.tick,0)
        self.assertFalse(any('input' in c for c in a.calls))
    def test_other_foreground_app_is_never_taken_over(self):
        a,d,r,_=self.setup_recovery();a.focus='com.browser.app'
        self.assertFalse(r.recover());self.assertEqual(a.launches(),[])
    def test_home_with_alive_game_does_not_restart(self):
        a,d,r,_=self.setup_recovery();a.alive=True
        self.assertFalse(r.recover());self.assertEqual(a.launches(),[])
    def test_stop_prevents_app_launch(self):
        a,d,r,_=self.setup_recovery();a.stop.set()
        with self.assertRaises(Halt):r.recover()
        self.assertEqual(a.launches(),[])
    def test_unrecognized_login_screen_times_out_without_touch(self):
        a,d,r,_=self.setup_recovery();a.states=['unknown']
        with self.assertRaisesRegex(Halt,'로그인|로딩'):r.recover()
        self.assertLessEqual(a.tick,90);self.assertEqual(len(a.launches()),1)
        self.assertFalse(any('input' in c for c in a.calls))
    def test_two_relaunch_limit_is_retained(self):
        a,d,r,_=self.setup_recovery();a.states=['menu']
        for _ in range(2):a.focus=HOME;a.alive=False;self.assertTrue(r.recover())
        a.focus=HOME;a.alive=False
        with self.assertRaisesRegex(Halt,'2회'):r.recover()
        self.assertEqual(len(a.launches()),2)
    def test_identity_change_before_launch_stops(self):
        a,d,r,_=self.setup_recovery()
        def changed():raise Halt('identity changed')
        r.verify_identity=changed
        with self.assertRaises(Halt):r.recover()
        self.assertEqual(a.launches(),[])
    def test_foreground_race_before_launch_stops(self):
        a,d,r,_=self.setup_recovery();checks=[]
        def verify():
            checks.append(True)
            if len(checks)==2:a.focus='com.browser.app'
        r.verify_identity=verify
        self.assertFalse(r.recover());self.assertEqual(a.launches(),[])

if __name__=='__main__':unittest.main()

class RecoveryIntegrationTests(unittest.TestCase):
    def test_recovery_skips_done_and_pending_rooms(self):
        from run_support import cycle_with_recovery
        from action_state import ActionState
        actions=ActionState();actions.reserve('wood');calls=[];records=[]
        c=SimpleNamespace(results={},claim_counts={},action_state=actions,daily_ledger=None,forget_observations=lambda:None)
        def cycle(rooms,restore):
            calls.append(list(rooms))
            if len(calls)==1:
                c.results={'farm':'collected','wood':'failed'}
                raise Halt('game exited')
            c.results={'mine':'collected'};return c.results
        c.cycle=cycle
        def record(task,result):c.results[task]=result;records.append((task,result))
        c.record_task=record
        d=SimpleNamespace(package=GAME,serial='127.0.0.1:16384',current_package=lambda:GAME)
        adb=SimpleNamespace(is_connected=lambda serial:True)
        recover=SimpleNamespace(recover=lambda:True)
        result=cycle_with_recovery(c,['farm','wood','mine'],False,adb,d,None,threading.Event(),lambda _:None,game_recovery=recover)
        self.assertEqual(calls,[['farm','wood','mine'],['mine']]);self.assertEqual(result,{'farm':'collected','wood':'deferred','mine':'collected'})
        self.assertIsNotNone(actions.pending('wood'))
    def test_no_relaunch_after_cancel(self):
        from run_support import cycle_with_recovery
        stop=threading.Event();stop.set();launches=[]
        def cycle(*_):raise Halt('stop')
        c=SimpleNamespace(cycle=cycle,results={},claim_counts={});d=SimpleNamespace(package=GAME)
        with self.assertRaises(Halt):cycle_with_recovery(c,['farm'],False,None,d,None,stop,lambda _:None,game_recovery=SimpleNamespace(recover=lambda:launches.append(1)))
        self.assertEqual(launches,[])
    def test_launch_uses_same_atomic_pause_guard_as_touch(self):
        from unittest.mock import patch
        from adb_device import Adb
        from run_control import RunControl,ResumeRecognition
        import sys
        stop=RunControl();adb=Adb(sys.executable,stop)
        stale=stop.generation;stop.pause();stop.resume()
        with patch('adb_device.subprocess.Popen') as create:
            with self.assertRaises(ResumeRecognition):adb.run(['-s','127.0.0.1:16384','shell','am','start','-W','-n',GAME+'/.Main'],input_generation=stale)
            create.assert_not_called()

class LateFocusRaceTests(unittest.TestCase):
    setup_recovery=GameRecoveryTests.setup_recovery
    def test_foreground_switch_during_last_process_query_prevents_launch(self):
        a,d,r,_=self.setup_recovery();run=a.run;queries=[]
        def delayed(args,**kw):
            result=run(args,**kw)
            if args[2:]==['shell','ps','-A']:
                queries.append(1)
                if len(queries)==2:a.focus='com.browser.app'
            return result
        a.run=delayed
        self.assertFalse(r.recover());self.assertEqual(a.launches(),[])
