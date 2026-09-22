"""Sanitized native v0.7.47 navigation regressions. No live inputs."""
from pathlib import Path
import json
import threading
import unittest
from unittest.mock import Mock
import cv2
import numpy as np
from extra_collector import ExtraCollector
from vision import Vision
from collector import Collector,Halt
from types import SimpleNamespace

ASSETS=Path(__file__).parent/'assets'
def frame(name):
    # Persist only tightly cropped generic controls, never diagnostic screens.
    layout=json.loads((ASSETS/'navigation_native_controls.json').read_text(encoding='utf-8'))
    fixture=layout['fixtures'][name]
    atlas=cv2.imdecode(np.fromfile(ASSETS/fixture['file'],np.uint8),cv2.IMREAD_COLOR)
    width,height=layout['size'];image=np.full((height,width,3),layout['background'],np.uint8)
    for control in fixture['controls'].values():
        ax,ay,ar,ab=control['atlas'];x,y,r,b=control['screen']
        image[y:b,x:r]=atlas[ay:ab,ax:ar]
    return image

class NativeNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.v=Vision()
    def test_reported_main_controls_survive_native_backgrounds(self):
        for name in ('snow','sand'):
            with self.subTest(name=name):
                s=self.v.recognize(frame(name))
                self.assertEqual(s.state,'main')
                self.assertIn('main_menu',s.matches)
    def test_pass_emblem_on_snow_is_recognized_without_background(self):
        s=self.v.recognize(frame('snow'))
        self.assertIn('top_pass',s.matches)
        self.assertLess(abs(s.matches['top_pass'].center[0]-599),3)
    def test_dimmed_chat_controls_never_authorize_main_navigation(self):
        self.assertEqual(self.v.recognize(frame('chat')).state,'unknown')
    def test_missing_or_flat_pass_emblem_never_authorizes_entry(self):
        for replacement in (24,190):
            im=frame('snow');im[:55,570:625]=replacement
            self.assertNotIn('top_pass',self.v.recognize(im).matches)
    def test_dimmed_or_missing_main_glyphs_never_authorize_navigation(self):
        for name in ('snow','sand'):
            im=frame(name)
            self.assertNotEqual(self.v.recognize((im*.4).astype(np.uint8)).state,'main')
            for x,y,r,b in ((893,4,938,50),(311,471,358,537),(427,471,476,537)):
                missing=im.copy();missing[y:b,x:r]=24
                self.assertNotEqual(self.v.recognize(missing).state,'main')
    def test_usable_menu_enters_pass_without_exposing_underlying_drawer(self):
        menu=self.v.recognize(frame('menu'));self.assertEqual(menu.state,'menu')
        c=ExtraCollector(Mock(),self.v,threading.Event(),Mock())
        c.daily_main=Mock(side_effect=AssertionError('usable menu must remain open'))
        c.daily_wait=Mock(side_effect=[menu,Mock(state='daily_pass_ad')])
        c.top_bar_tap=Mock();c.daily_tap=Mock()
        result=c.daily_open('pass',{'daily_pass_ad'})
        self.assertEqual(result.state,'daily_pass_ad')
        c.top_bar_tap.assert_called_once_with(menu,'pass',validate=c.daily_check_day)
        c.daily_tap.assert_not_called()

    def collector(self,after_click):
        clock=[0.];images=[frame('sand')];clicks=[]
        def capture():clock[0]+=.1;return images[0]
        def click(point):
            clicks.append(point);images[0]=after_click(len(clicks))
        device=SimpleNamespace(capture=capture,click=click)
        c=Collector(device,self.v,threading.Event(),Mock())
        c.now=lambda:clock[0];c.pause=lambda t:clock.__setitem__(0,clock[0]+t)
        return c,clicks
    def test_reported_unchanged_main_reopens_menu_after_fresh_confirmation(self):
        c,clicks=self.collector(lambda n:frame('sand') if n==1 else frame('menu'))
        try:result=c.ensure_menu(c.screen())
        except Halt as exc:self.fail('Known unchanged main must recover: '+str(exc))
        self.assertEqual(result.state,'menu')
        self.assertEqual(len(clicks),2)
        self.assertTrue(all(900<x<930 and 10<y<45 for x,y in clicks))
    def test_unchanged_main_retry_is_bounded(self):
        c,clicks=self.collector(lambda n:frame('sand'))
        with self.assertRaises(Halt):c.ensure_menu(c.screen())
        self.assertEqual(len(clicks),3)
    def test_unknown_chat_after_menu_touch_never_retries(self):
        c,clicks=self.collector(lambda n:frame('chat'))
        with self.assertRaises(Halt):c.ensure_menu(c.screen())
        self.assertEqual(len(clicks),1)
    def test_late_menu_before_retry_is_not_toggled_closed(self):
        c,clicks=self.collector(lambda n:frame('sand'))
        observe=c.wait_menu_open
        def late_menu():
            result=observe()
            c.device.capture=lambda:frame('menu')
            return result
        c.wait_menu_open=late_menu
        self.assertEqual(c.ensure_menu(c.screen()).state,'menu')
        self.assertEqual(len(clicks),1)

if __name__=='__main__':unittest.main()
