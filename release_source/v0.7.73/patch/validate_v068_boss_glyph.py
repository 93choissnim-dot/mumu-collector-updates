"""Keep boss identity stable when scenery changes around the supply glyph."""
import threading
import unittest
from unittest.mock import Mock
import cv2
import numpy as np
from collector import ScreenChanged
from extra_collector import ExtraCollector
from vision import Vision
from validate_overlays import composite

MARKERS=('x_boss_mission','x_boss_rank_open','x_boss_supply')

class BossGlyphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.v=Vision()

    def animated_frame(self):
        im=composite(self.v,*MARKERS)
        # The chest's fixed white glyph survives; scenery, border and badge do
        # not. Build from shipped controls, without any account screenshots.
        tile=im[440:526,280:344].copy()
        y,x=np.indices(tile.shape[:2]);tile[:]=np.stack((50+x*2,80+y,100+x),axis=2).astype(np.uint8)
        tile[20:52,15:49]=self.v.templates['x_boss_supply'][0][20:52,15:49]
        im[440:526,280:344]=tile
        return im

    def test_animated_surround_keeps_boss_and_rank_navigation(self):
        s=self.v.recognize(self.animated_frame())
        self.assertEqual(s.state,'boss')
        self.assertIn('x_boss_rank_open',s.matches)
        self.assertNotIn('x_boss_active',s.matches)

    def test_independent_controls_remain_required(self):
        for missing in MARKERS:
            im=self.animated_frame();x,y,r,b=self.v.specs[missing]['box'];im[y:b,x:r]=0
            with self.subTest(missing=missing):self.assertNotEqual(self.v.recognize(im).state,'boss')

    def test_dimmed_page_is_not_navigation_evidence(self):
        im=(self.animated_frame().astype(float)*.30).astype(np.uint8)
        self.assertNotEqual(self.v.recognize(im).state,'boss')

    def test_resized_and_brightness_shifted_controls(self):
        for gain in (.9,1.,1.1):
            im=np.clip(self.animated_frame().astype(float)*gain,0,255).astype(np.uint8)
            for width in (640,960,1280):
                with self.subTest(gain=gain,width=width):
                    self.assertEqual(self.v.recognize(cv2.resize(im,(width,width*9//16))).state,'boss')

    def test_fresh_navigation_preserves_an_unresolved_reward(self):
        im=self.animated_frame();screen=self.v.recognize(im)
        device=Mock();device.capture.return_value=im
        c=ExtraCollector(device,self.v,threading.Event(),Mock())
        c.action_state.reserve('worldboss','kraken')
        pending=c.action_state.pending('worldboss','kraken')
        c.tap(screen,'x_boss_rank_open')
        self.assertEqual(device.click.call_args.args,(screen.matches['x_boss_rank_open'].center,))
        self.assertEqual(device.click.call_count,1)
        self.assertEqual(c.action_state.pending('worldboss','kraken'),pending)

    def test_fresh_navigation_guard_never_uses_a_disappeared_rank_button(self):
        im=self.animated_frame();screen=self.v.recognize(im)
        self.assertEqual(screen.state,'boss')
        x,y,r,b=self.v.specs['x_boss_rank_open']['box'];im[y:b,x:r]=0
        device=Mock();device.capture.return_value=im
        c=ExtraCollector(device,self.v,threading.Event(),Mock());c.pause=lambda seconds:None
        with self.assertRaises(ScreenChanged):c.tap(screen,'x_boss_rank_open')
        self.assertEqual(device.click.call_count,0)

if __name__=='__main__':unittest.main()
