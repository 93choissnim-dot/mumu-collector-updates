"""Native workshop entry regression using only generic, tightly cropped controls."""
import json
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
import cv2
import numpy as np
from collector import ScreenChanged
from daily_state import korea_day
from extra_collector import ExtraCollector
from vision import Vision

ASSETS=Path(__file__).parent/'assets'

def frame():
    layout=json.loads((ASSETS/'raid_native_controls.json').read_text(encoding='utf-8'))
    atlas=cv2.imdecode(np.fromfile(ASSETS/'raid_native_controls.png',np.uint8),cv2.IMREAD_COLOR)
    im=np.full((540,960,3),110,np.uint8)
    for control in layout['controls'].values():
        x,y,r,b=control['screen'];ax,ay,ar,ab=control['atlas']
        im[y-7:b+7,x-7:r+7]=cv2.copyMakeBorder(atlas[ay:ab,ax:ar],7,7,7,7,cv2.BORDER_REPLICATE)
    return im

class NativeRaidTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.v=Vision()

    def test_reported_detail_and_enabled_fight_are_recognized(self):
        s=self.v.recognize(frame())
        self.assertEqual(s.state,'daily_raid_detail')
        self.assertIn('daily_raid_fight',s.matches)
        self.assertTrue(800<s.matches['daily_raid_fight'].center[0]<860)

    def test_native_controls_survive_capture_size_changes(self):
        for width in (640,960,1280):
            with self.subTest(width=width):
                s=self.v.recognize(cv2.resize(frame(),(width,width*9//16)))
                self.assertEqual(s.state,'daily_raid_detail')
                self.assertIn('daily_raid_fight',s.matches)

    def test_missing_independent_page_label_cannot_authorize_entry(self):
        for box in ((73,0,458,56),(567,56,633,96)):
            im=frame();x,y,r,b=box;im[y:b,x:r]=110
            self.assertNotEqual(self.v.recognize(im).state,'daily_raid_detail')

    def test_disabled_or_missing_fight_remains_unclickable(self):
        for mode in ('missing','dim','gray'):
            im=frame();crop=im[460:525,727:940]
            if mode=='missing':crop[:]=110
            elif mode=='dim':crop[:]=(crop*.45).astype(np.uint8)
            else:crop[:]=cv2.cvtColor(cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY),cv2.COLOR_GRAY2BGR)
            s=self.v.recognize(im)
            self.assertEqual(s.state,'daily_raid_detail')
            self.assertNotIn('daily_raid_fight',s.matches,mode)

    def test_dimmed_page_never_authorizes_entry(self):
        s=self.v.recognize((frame()*.4).astype(np.uint8))
        self.assertNotEqual(s.state,'daily_raid_detail')
        self.assertNotIn('daily_raid_fight',s.matches)

    def test_header_in_wrong_region_is_not_workshop_detail(self):
        im=frame();im[250:292,157:217]=im[7:49,157:217];im[:56,:458]=110
        self.assertNotEqual(self.v.recognize(im).state,'daily_raid_detail')

    def collector(self,im):
        clicks=[]
        device=SimpleNamespace(capture=lambda:im,click=clicks.append)
        c=ExtraCollector(device,self.v,threading.Event(),lambda text:None)
        c.daily_day=korea_day();c.pause=lambda seconds:None
        return c,clicks

    def test_real_fresh_screen_guard_sends_fight_to_reported_button(self):
        c,clicks=self.collector(frame())
        s=c.daily_wait({'daily_raid_detail'},timeout=1)
        c.daily_tap(s,'raid_fight')
        self.assertEqual(len(clicks),1)
        self.assertTrue(800<clicks[0][0]<860 and 470<clicks[0][1]<520)

    def test_button_disappearing_after_observation_sends_no_input(self):
        before=self.v.recognize(frame());im=frame();im[460:525,727:940]=110
        c,clicks=self.collector(im)
        with self.assertRaises(ScreenChanged):c.daily_tap(before,'raid_fight')
        self.assertEqual(clicks,[])

if __name__=='__main__':unittest.main()
