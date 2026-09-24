"""Behavior checks for pausing, stale touches, schedules and stop shortcuts."""
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from adb_device import Adb, AdbDevice
from collector import Collector, Halt
from extra_collector import ExtraCollector
from run_control import RunControl, ResumeRecognition
from run_support import cycle_with_recovery
from fleet_runner import run_fleet
from stop_hotkey import StopHotkey, KEYS, normalize, from_tk_event


class PauseTests(unittest.TestCase):
    def test_pause_freezes_clock_and_resume_preserves_remaining_time(self):
        clock=[100.]
        control=RunControl(lambda:clock[0])
        clock[0]=105.;control.pause()
        clock[0]=4105.
        self.assertEqual(control.clock(),105.)
        control.resume();clock[0]=4110.
        self.assertEqual(control.clock(),110.)
        control.set();self.assertTrue(control.wait(100))
        control.clear();self.assertFalse(control.is_set());self.assertFalse(control.paused)

    def test_wait_does_not_finish_paused_and_stop_wakes_it(self):
        control=RunControl();control.pause();done=threading.Event();answers=[]
        thread=threading.Thread(target=lambda:(answers.append(control.wait(.01)),done.set()),daemon=True)
        thread.start()
        try:
            self.assertFalse(done.wait(.05))
            control.set()
            self.assertTrue(done.wait(1))
            self.assertEqual(answers,[True])
        finally:
            control.set();thread.join(1)

    def test_resume_finishes_original_wait_without_cancel(self):
        control=RunControl();control.pause();done=threading.Event();answers=[]
        thread=threading.Thread(target=lambda:(answers.append(control.wait(.02)),done.set()),daemon=True)
        thread.start()
        try:
            self.assertFalse(done.wait(.04))
            control.resume()
            self.assertTrue(done.wait(1));self.assertEqual(answers,[False])
        finally:
            control.set();thread.join(1)

    def test_paused_adb_never_dispatches_input(self):
        control=RunControl();adb=Adb(sys.executable,control);control.pause()
        with patch('adb_device.subprocess.Popen') as launch:
            with self.assertRaises(ResumeRecognition):
                adb.run(['-s','127.0.0.1:16384','shell','input','tap',10,20])
            launch.assert_not_called()

    def test_pause_race_rejects_old_generation_at_dispatch(self):
        control=RunControl();adb=Adb(sys.executable,control);old=control.generation
        control.pause();control.resume()
        with patch('adb_device.subprocess.Popen') as launch:
            with self.assertRaises(ResumeRecognition):
                adb.run(['shell','input','tap',10,20],input_generation=old)
            launch.assert_not_called()

    def test_pause_after_capture_requires_recognition_before_touch(self):
        control=RunControl();adb=Mock(stop=control)
        device=AdbDevice(adb,'127.0.0.1:16384')
        device.guard_package=Mock();device.size=(960,540);device.last_capture=time.monotonic()
        control.pause();control.resume()
        with self.assertRaises(ResumeRecognition):device.click((50,50))
        adb.run.assert_not_called()

    def test_collector_deadline_excludes_long_pause(self):
        clock=[100.];control=RunControl(lambda:clock[0]);device=Mock()
        collector=Collector(device,Mock(),control,lambda _:None)
        def screen():
            if device.capture.call_count==0:
                control.pause();clock[0]+=3600;control.resume()
            device.capture()
            return SimpleNamespace(state='menu',matches={})
        collector.screen=screen
        collector.pause=lambda seconds:clock.__setitem__(0,clock[0]+seconds)
        self.assertEqual(collector.wait_for({'menu'},timeout=1).state,'menu')
        self.assertEqual(device.capture.call_count,2)

    def test_scheduler_keeps_player_order_across_pause(self):
        control=RunControl();ready=threading.Event();done=threading.Event();seen=[]
        jobs=[{'id':s,'name':s,'rooms':['farm'],'minutes':1} for s in ['a','b']]
        def execute(job,rooms):
            seen.append(job['id'])
            if job['id']=='a':control.pause();ready.set()
            return {'farm':'collected'}
        thread=threading.Thread(target=lambda:(run_fleet(jobs,False,control,threading.Event(),execute,lambda *args:None),done.set()),daemon=True)
        thread.start()
        try:
            self.assertTrue(ready.wait(1));self.assertFalse(done.wait(.05));self.assertEqual(seen,['a'])
            control.resume();self.assertTrue(done.wait(1));self.assertEqual(seen,['a','b'])
        finally:
            control.set();thread.join(1)

    def test_reacquire_skips_completed_tasks_and_retains_click_budget(self):
        control=RunControl();calls=[]
        collector=SimpleNamespace(results={},claim_counts={},last_image=None,last_screen=None,forget_observations=Mock())
        def cycle(rooms,restore):
            calls.append(list(rooms))
            if len(calls)==1:
                collector.results={'farm':'collected'};collector.claim_counts={'farm':1,'training':2}
                raise ResumeRecognition()
            self.assertEqual(collector.resume_counts,{'training':2})
            collector.results={'training':'attempted'};collector.claim_counts={'training':3}
            return collector.results
        collector.cycle=cycle
        device=Mock(package='game');device.current_package.return_value='game'
        result=cycle_with_recovery(collector,['farm','training'],False,Mock(),device,Mock(),control,lambda _:None)
        self.assertEqual(calls,[['farm','training'],['training']])
        self.assertEqual(result,{'farm':'collected','training':'attempted'})
        self.assertEqual(collector.resume_counts,{})

    def test_resume_does_not_touch_a_different_app(self):
        collector=SimpleNamespace(results={},claim_counts={},cycle=Mock(side_effect=ResumeRecognition()))
        device=Mock(package='game');device.current_package.return_value='other.app'
        with self.assertRaises(Halt):
            cycle_with_recovery(collector,['farm'],False,Mock(),device,Mock(),RunControl(),lambda _:None)
        self.assertEqual(collector.cycle.call_count,1)

    def test_resumed_training_uses_fresh_button_state(self):
        from validate_extra import Device
        for state,empty,result,claims in [('training',False,'collected',1),
                ('training',True,'collected',0),('unknown',False,'deferred',0)]:
            with self.subTest(state=state,empty=empty):
                device=Device('training',empty=empty);device.state=state
                vision=SimpleNamespace(recognize=lambda _:device.screen())
                collector=ExtraCollector(device,vision,device.stop,lambda _:None)
                collector.now=lambda:device.clock
                collector.pause=lambda n:setattr(device,'clock',device.clock+n)
                collector.resume_counts={'training':3}
                self.assertEqual(collector.claim_extra('training',None),result)
                self.assertEqual(device.claims,claims)
                self.assertIsNotNone(collector.last_image)
                self.assertEqual(collector.last_screen.state,state)



class HotkeyTests(unittest.TestCase):
    def test_default_and_invalid_saved_key(self):
        self.assertEqual(StopHotkey().value,'F8')
        self.assertEqual(StopHotkey('bad').value,'F8')
        self.assertEqual(normalize('Shift+Ctrl+F9'),'Ctrl+Shift+F9')

    def test_exact_modifiers_and_edge_detection(self):
        hotkey=StopHotkey('Ctrl+Shift+F9');down=set();pressed=lambda k:k in down
        self.assertFalse(hotkey.poll(pressed))
        down.add(KEYS['F8']);self.assertFalse(hotkey.poll(pressed));down.clear()
        down.add(KEYS['F9']);self.assertFalse(hotkey.poll(pressed))
        down.update([0x11,0x10]);self.assertTrue(hotkey.poll(pressed))
        self.assertFalse(hotkey.poll(pressed))
        down.add(0x12);self.assertFalse(hotkey.poll(pressed))
        down.clear();hotkey.poll(pressed)
        down.update([KEYS['F9'],0x11,0x10]);self.assertTrue(hotkey.poll(pressed))

    def test_key_held_while_saving_does_not_stop_a_run(self):
        hotkey=StopHotkey('F9');down={KEYS['F9']};pressed=lambda k:k in down
        self.assertFalse(hotkey.poll(pressed));self.assertFalse(hotkey.poll(pressed))
        down.clear();self.assertFalse(hotkey.poll(pressed))
        down.add(KEYS['F9']);self.assertTrue(hotkey.poll(pressed))

    def test_key_capture_supports_modifiers_and_ignores_modifier_only(self):
        self.assertEqual(from_tk_event(SimpleNamespace(keysym='k',state=0x5)),'Ctrl+Shift+K')
        self.assertEqual(from_tk_event(SimpleNamespace(keysym='Escape',state=0)),'Esc')
        self.assertIsNone(from_tk_event(SimpleNamespace(keysym='Control_L',state=0)))


if __name__=='__main__':unittest.main()
