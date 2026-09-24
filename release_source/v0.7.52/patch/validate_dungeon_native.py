"""Native dungeon entry regression, storing only small generic UI controls."""
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
ZERO_MARKERS={'daily_d_count_0','daily_d_count_zero1','daily_d_count_zero2'}

def frame(room='stone'):
    layout=json.loads((ASSETS/'dungeon_native_controls.json').read_text(encoding='utf-8'))
    atlas=cv2.imdecode(np.fromfile(ASSETS/'dungeon_native_controls.png',np.uint8),cv2.IMREAD_COLOR)
    im=np.full((540,960,3),110,np.uint8)
    for key in ('room_'+room,'d_close','d_enter','count_one3' if room=='stone' else 'count_one2'):
        control=layout['controls'][key]
        x,y,r,b=control['screen'];ax,ay,ar,ab=control['atlas']
        im[y-7:b+7,x-7:r+7]=cv2.copyMakeBorder(atlas[ay:ab,ax:ar],7,7,7,7,cv2.BORDER_REPLICATE)
    return im

class NativeDungeonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.v=Vision()

    def test_active_native_entry_is_recognized_at_capture_sizes(self):
        for room in ('stone','treasure'):
            for width in (640,960,1280):
                with self.subTest(room=room,width=width):
                    s=self.v.recognize(cv2.resize(frame(room),(width,width*9//16)))
                    self.assertEqual(s.state,'daily_room_'+room)
                    self.assertIn('daily_d_enter',s.matches)
                    self.assertFalse(ZERO_MARKERS.intersection(s.matches))
                    x,y=s.matches['daily_d_enter'].center
                    self.assertTrue(715<x<772 and 424<y<456)

    def test_original_entry_reference_remains_accepted(self):
        for room in ('stone','treasure'):
            im=np.full((540,960,3),110,np.uint8)
            for key in ('room_'+room,'d_close','d_enter'):
                x,y,r,b=self.v.daily.specs[key]['box'];im[y:b,x:r]=self.v.daily.templates[key][0]
            for native in (False,True):
                transformed=np.clip(im.astype(float)*[1.205,1.24,1.214]+[7,0,-2],0,255).astype(np.uint8) if native else im
                for width in (640,960,1280):
                    with self.subTest(room=room,native=native,width=width):
                        s=self.v.recognize(cv2.resize(transformed,(width,width*9//16)))
                        self.assertEqual(s.state,'daily_room_'+room)
                        self.assertIn('daily_d_enter',s.matches)

    def test_disabled_and_missing_native_entry_are_rejected(self):
        for mode in ('missing','dim','gray'):
            im=frame();crop=im[418:462,709:777]
            if mode=='missing':crop[:]=110
            elif mode=='dim':crop[:]=(crop*.45).astype(np.uint8)
            else:crop[:]=cv2.cvtColor(cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY),cv2.COLOR_GRAY2BGR)
            for width in (640,960,1280):
                with self.subTest(mode=mode,width=width):
                    s=self.v.recognize(cv2.resize(im,(width,width*9//16)))
                    self.assertEqual(s.state,'daily_room_stone')
                    self.assertNotIn('daily_d_enter',s.matches,mode)
                    self.assertFalse(ZERO_MARKERS.intersection(s.matches))

    def collector(self,im):
        clicks=[];device=SimpleNamespace(capture=lambda:im,click=clicks.append)
        c=ExtraCollector(device,self.v,threading.Event(),lambda text:None)
        c.daily_day=korea_day();c.pause=lambda seconds:None
        return c,clicks

    def test_real_fresh_guard_taps_verified_native_entry(self):
        for room in ('stone','treasure'):
            c,clicks=self.collector(frame(room))
            s=c.daily_ready({'daily_room_'+room},('d_enter',),timeout=1)
            c.daily_tap(s,'d_enter')
            self.assertEqual(len(clicks),1)
            self.assertTrue(715<clicks[0][0]<772 and 424<clicks[0][1]<456)

    def test_changed_button_or_page_sends_no_input(self):
        before=self.v.recognize(frame())
        for missing in ('button','title','close','all'):
            im=frame()
            if missing=='button':im[418:462,709:777]=110
            elif missing=='title':im[63:115,133:313]=110
            elif missing=='close':im[70:108,795:833]=110
            else:im=(im*.4).astype(np.uint8)
            c,clicks=self.collector(im)
            with self.assertRaises(ScreenChanged):c.daily_tap(before,'d_enter')
            self.assertEqual(clicks,[])

if __name__=='__main__':unittest.main()
