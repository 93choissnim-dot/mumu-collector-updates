"""Regression for the two v0.7.6 native-ADB ranking failures.

The test canvas uses existing public page templates and the approved button crop.
No diagnostic screen or additional diagnostic-derived fixture is distributed.
Input events are simulated; no MuMu or desktop access is performed.
"""
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from collector import Halt
from extra_collector import ExtraCollector
from validate_photometric import variations
from vision import Vision


class NativeRankingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).parent
        cls.v=Vision()
        profile=cls.v.button_profiles.profiles['ranking']
        cls.frame=np.full((540,960,3),115,np.uint8)
        def place(box,raw):
            x1,y1,x2,y2=box
            cls.frame[y1-7:y2+7,x1-7:x2+7]=cv2.copyMakeBorder(raw,7,7,7,7,cv2.BORDER_REPLICATE)
        for anchor in profile['anchors']:
            place(anchor['box'],cv2.imread(str(cls.root/'assets'/anchor['file'])))
        variant=profile['active_variants'][0]
        raw=cv2.imread(str(cls.root/'assets'/variant['file']))
        normalized=np.clip((raw.astype(np.float32)-variant['offset'])/variant['gain'],0,255).astype(np.uint8)
        place(profile['box'],normalized)

    def test_fixture_reproduces_previous_missing_button(self):
        old=Vision()
        old.button_profiles.profiles['ranking']['variants']['active']=[]
        screen=old.recognize(self.frame)
        self.assertEqual(screen.state,'ranking')
        self.assertNotIn('x_rank_active',screen.matches)
        self.assertEqual(screen.diagnostics['_button_calibration']['ranking']['status'],'button_missing')

    def test_native_button_survives_capture_variations(self):
        for change,im in variations(self.frame):
            for width in (640,960,1280):
                with self.subTest(change=change,width=width):
                    screen=self.v.recognize(cv2.resize(im,(width,width*9//16)))
                    self.assertEqual(screen.state,'ranking')
                    self.assertIn('x_rank_active',screen.matches)
                    self.assertNotIn('x_rank_empty',screen.matches)

    def empty_frame(self):
        # Simulated post-claim frame from the existing disabled reference,
        # brought into the fixture's independently measured exposure space.
        frame=self.frame.copy()
        profile=self.v.button_profiles.profiles['ranking']
        d=self.v.recognize(frame).diagnostics['_button_calibration']['ranking']
        raw=cv2.imread(str(self.root/'assets'/profile['empty_file']))
        raw=np.clip(raw.astype(np.float32)*d['gain']+d['offset'],0,255).astype(np.uint8)
        x1,y1,x2,y2=profile['box'];frame[y1:y2,x1:x2]=raw
        return frame

    def test_disabled_button_stays_disabled_in_native_context(self):
        for change,frame in variations(self.empty_frame()):
            screen=self.v.recognize(frame)
            self.assertIn('x_rank_empty',screen.matches,change)
            self.assertNotIn('x_rank_active',screen.matches,change)

    def test_button_requires_independent_page_context(self):
        profile=self.v.button_profiles.profiles['ranking']
        for anchor in profile['anchors']:
            frame=self.frame.copy();x1,y1,x2,y2=anchor['box'];frame[y1:y2,x1:x2]=115
            screen=self.v.recognize(frame)
            self.assertNotIn('x_rank_active',screen.matches)

    def test_dimmed_and_erased_native_buttons_never_become_claimable(self):
        frame=self.frame.copy();frame[66:90,880:938]=115
        for im in [frame,(self.frame*.5).astype(np.uint8)]:
            screen=self.v.recognize(im)
            self.assertNotIn('x_rank_active',screen.matches)

    def test_actual_recognizer_drives_one_claim_and_confirms_disabled(self):
        active=self.frame;empty=self.empty_frame()
        class Device:
            def __init__(self):self.clicks=[];self.clock=0
            def capture(self):
                self.clock+=.1
                return (empty if self.clicks else active).copy()
            def click(self,point):self.clicks.append(point)
        device=Device();stop=threading.Event()
        collector=ExtraCollector(device,self.v,stop,lambda text:None)
        def pause(seconds):device.clock+=seconds
        collector.pause=pause
        with patch('extra_collector.time.monotonic',lambda:device.clock):
            result=collector.claim_extra('ranking',collector.screen())
        self.assertEqual(result,'collected')
        self.assertEqual(device.clicks,[(909.0,78.0)])
        self.assertLess(device.clock,10)


if __name__=='__main__':unittest.main()
