"""Start recovery regressions: real cropped UI markers and simulated input."""
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import cv2
import numpy as np
from collector import Collector, Halt
from extra_collector import ExtraCollector
from vision import Vision, Screen, Match, MAIN_MARKERS
from start_navigation import prepare_start
from validate_overlays import composite
from validate_adb import FakeAdb
from adb_device import AdbDevice
from run_control import RunControl, ResumeRecognition

EXIT = ('exit_title', 'exit_cancel', 'exit_confirm')

class RecoveryTests(unittest.TestCase):
    def run_start(self, initial, *, wake_to='menu', back_to=None, cancel_to='main', stuck=False, stop_on=None, partial=False, cls=ExtraCollector):
        stop=threading.Event()
        d=SimpleNamespace(state=initial, time=0., actions=[], backs=0)
        def capture():
            d.time += .1
            matches={}
            if d.state=='exit_dialog':
                matches={k:Match(k,1,0,(395,361) if k=='exit_cancel' else (590,361)) for k in EXIT if not (partial and k=='exit_cancel')}
            if d.state=='main': matches['main_menu']=Match('main_menu',1,0,(925,25))
            return Screen(d.state,matches)
        def action(kind,target):
            self.assertFalse(stop.is_set())
            d.actions.append(kind)
            if not stuck:d.state=target
            if stop_on==kind:stop.set()
        def click(point):
            if d.state=='exit_dialog':
                self.assertEqual(point,(395,361),'Only Cancel may be clicked')
                action('cancel',cancel_to)
            elif d.state=='main':
                self.assertEqual(point,(925,25));action('menu','menu')
            else:raise AssertionError(('unexpected click',d.state,point))
        def back():
            self.assertNotIn(d.state,{'main','menu','sleep','exit_dialog'})
            d.backs+=1
            action('back',back_to[d.backs-1] if back_to and d.backs<=len(back_to) else 'main')
        def drag(a,b):
            self.assertEqual(d.state,'sleep');action('wake',wake_to)
        d.capture=capture;d.click=click;d.back=back;d.drag=drag
        c=cls(d,SimpleNamespace(recognize=lambda im:im),stop,lambda t:None)
        c.now=lambda:d.time
        def pause(t):
            if stop.is_set():raise Halt('Stopped')
            d.time+=t
        c.pause=pause
        try:result=c.ensure_menu(prepare_start(c))
        except Halt as exc:result=exc
        return d,result

    def test_menu_and_main_never_receive_escape(self):
        for cls in (Collector,ExtraCollector):
            for initial,actions in [('menu',[]),('main',['menu'])]:
                d,r=self.run_start(initial,cls=cls)
                self.assertEqual(r.state,'menu');self.assertEqual(d.actions,actions)

    def test_wake_to_menu_skips_back_and_menu_toggle(self):
        for cls in (Collector,ExtraCollector):
            d,r=self.run_start('sleep',cls=cls)
            self.assertEqual(r.state,'menu');self.assertEqual(d.actions,['wake'])

    def test_wake_to_main_opens_menu_without_back(self):
        d,r=self.run_start('sleep',wake_to='main')
        self.assertEqual(r.state,'menu');self.assertEqual(d.actions,['wake','menu'])

    def test_nested_unknown_pages_one_back_at_a_time(self):
        d,r=self.run_start('unknown',back_to=['unknown','training','main'])
        self.assertEqual(r.state,'menu');self.assertEqual(d.actions,['back']*3+['menu'])

    def test_known_page_starts_with_back(self):
        for page in ['ranking','training','farm_ready','boss_rank']:
            d,r=self.run_start(page)
            self.assertEqual(r.state,'menu');self.assertEqual(d.actions,['back','menu'])

    def test_sleep_with_hidden_window_recovers(self):
        d,r=self.run_start('sleep',wake_to='unknown')
        self.assertEqual(r.state,'menu');self.assertEqual(d.actions,['wake','back','menu'])

    def test_exit_dialog_initial_cancel_only(self):
        d,r=self.run_start('exit_dialog')
        self.assertEqual(r.state,'menu');self.assertEqual(d.actions,['cancel','menu'])

    def test_escape_overshoot_cancels_and_stops_escape(self):
        d,r=self.run_start('unknown',back_to=['exit_dialog'])
        self.assertEqual(r.state,'menu');self.assertEqual(d.actions,['back','cancel','menu'])

    def test_cancel_reveals_menu_without_extra_input(self):
        d,r=self.run_start('exit_dialog',cancel_to='menu')
        self.assertEqual(r.state,'menu');self.assertEqual(d.actions,['cancel'])

    def test_back_budget_and_sleep_budget(self):
        for state,kind,count in [('unknown','back',6),('sleep','wake',3),('exit_dialog','cancel',3)]:
            d,r=self.run_start(state,stuck=True)
            self.assertIsInstance(r,Halt);self.assertEqual(d.actions,[kind]*count)

    def test_partial_exit_modal_never_receives_input(self):
        d,r=self.run_start('exit_dialog',partial=True)
        self.assertIsInstance(r,Halt);self.assertEqual(d.actions,[])

    def test_stop_after_action_prevents_further_input(self):
        for state,kind in [('unknown','back'),('sleep','wake'),('exit_dialog','cancel')]:
            d,r=self.run_start(state,stop_on=kind)
            self.assertIsInstance(r,Halt);self.assertEqual(d.actions,[kind])

class ImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.v=Vision()
    def test_exit_priority_over_background_main_and_menu(self):
        for background in [MAIN_MARKERS,('menu_farm','menu_wood','menu_mine')]:
            for width in (640,960,1280,1920):
                im=composite(self.v,*background,*EXIT)
                im=cv2.resize(im,(width,width*9//16))
                s=self.v.recognize(im)
                self.assertEqual(s.state,'exit_dialog');self.assertTrue(all(k in s.matches for k in EXIT))
                self.assertLess(s.matches['exit_cancel'].center[0],480)
    def test_partial_modal_does_not_fall_through_to_main(self):
        for names in [('exit_title',),('exit_cancel','exit_confirm')]:
            s=self.v.recognize(composite(self.v,*MAIN_MARKERS,*names))
            self.assertEqual(s.state,'exit_dialog')
            self.assertFalse(all(k in s.matches for k in EXIT))
    def test_plain_background_not_exit(self):
        for names in [MAIN_MARKERS,('menu_farm','menu_wood','menu_mine'),()]:
            self.assertNotEqual(self.v.recognize(composite(self.v,*names)).state,'exit_dialog')
    def test_color_brightness_and_small_offset(self):
        im=composite(self.v,*EXIT)
        for gain in (.8,1.0,1.2):
            for dx,dy in [(0,0),(3,2),(-3,-2)]:
                frame=cv2.warpAffine(np.clip(im.astype(float)*gain,0,255).astype('uint8'),np.float32([[1,0,dx],[0,1,dy]]),(960,540))
                s=self.v.recognize(frame)
                self.assertEqual(s.state,'exit_dialog');self.assertTrue(all(k in s.matches for k in EXIT))

class BindingTests(unittest.TestCase):
    def device(self,package='com.nns.genesis',state='unknown'):
        a=FakeAdb();a.package=package
        d=AdbDevice(a,'127.0.0.1:16384')
        v=SimpleNamespace(recognize=lambda im:Screen(state,{}))
        return a,d,v
    def test_unrecognized_page_in_verified_game_can_recover(self):
        a,d,v=self.device();d.bind_game(v);d.back()
        self.assertIn(['-s',d.serial,'shell','input','keyevent','KEYCODE_BACK'],a.calls)
    def test_unrecognized_other_app_cannot_bind(self):
        for pkg in ['com.android.launcher','com.example.game','com.nns.genesis.fake']:
            a,d,v=self.device(pkg)
            with self.assertRaises(Halt):d.bind_game(v)
            self.assertFalse(any('input' in x for x in a.calls))
    def test_back_requires_fresh_capture_same_package_and_no_stop(self):
        for mode in ['stale','different_app','stop']:
            a,d,v=self.device();d.bind_game(v)
            if mode=='stale':d.last_capture-=10
            if mode=='different_app':a.package='com.android.launcher'
            if mode=='stop':a.stop.set()
            with self.assertRaises(Halt):d.back()
            self.assertFalse(any('input' in x for x in a.calls))
    def test_pause_generation_invalidates_back(self):
        a,d,v=self.device();a.stop=RunControl();d.bind_game(v)
        a.stop.pause();a.stop.resume()
        with self.assertRaises(ResumeRecognition):d.back()
        self.assertFalse(any('input' in x for x in a.calls))
    def test_exit_is_bindable_without_unknown_fallback(self):
        a,d,v=self.device('com.example.game','exit_dialog');d.bind_game(v)
        self.assertEqual(d.package,a.package)

if __name__=='__main__':unittest.main()
