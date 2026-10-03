"""Free summon controls stay inside the first button when prices widen."""
from pathlib import Path
import unittest
import cv2
import numpy as np
from vision import Vision
from validate_v072_free_daily import RouteHarness

class LayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.v=Vision()
    def frame(self,name,shift=0):
        p=Path(__file__).parent/'assets'/('free_daily_fixture_'+name+'.png')
        im=cv2.imdecode(np.frombuffer(p.read_bytes(),np.uint8),1)
        if shift:
            button=im[468:532,135:338].copy();im[468:532,108:338]=95
            im[468:532,135-shift:338-shift]=button
        return im
    def test_main_counts_survive_bounded_button_left_shift(self):
        for name,n in [('char_two',2),('char_zero_result',0),('skill_two',2),('skill_one_result',1),('skill_zero_result',0),('pet_two',2)]:
            for shift in (0,12,20,24):
                with self.subTest(name=name,shift=shift):
                    s=self.v.recognize(self.frame(name,shift))
                    self.assertIn('daily_free_count_'+str(n),s.matches)
                    self.assertEqual('daily_free_summon' in s.matches,n>0)
    def test_shifted_exhausted_button_never_authorizes_summon(self):
        for name in ('char_zero_result','skill_zero_result'):
            for width in (960,1280,1920):
                with self.subTest(name=name,width=width):
                    im=self.frame(name,20);s=self.v.recognize(cv2.resize(im,(width,width*9//16)))
                    self.assertIn('daily_free_count_0',s.matches);self.assertNotIn('daily_free_summon',s.matches)
    def test_low_resolution_zero_never_becomes_an_available_attempt(self):
        # The old character fixture is already below the unchanged .91 gate
        # at 640px (.902); unreadable remains safe rather than lowering it.
        for name in ('char_zero_result','skill_zero_result'):
            s=self.v.recognize(cv2.resize(self.frame(name,20),(640,360)))
            self.assertNotIn('daily_free_summon',s.matches)
            self.assertNotIn('daily_free_count_1',s.matches)
            self.assertNotIn('daily_free_count_2',s.matches)
    def test_missing_free_identity_ad_or_count_never_authorizes_touch(self):
        boxes=[(135,474,219,523),(220,483,256,513),(255,483,324,513)]
        for box in boxes:
            im=self.frame('skill_two',20);x,y,r,b=box;im[y:b,x:r]=95
            s=self.v.recognize(im);self.assertNotIn('daily_free_summon',s.matches)
    def test_counter_on_paid_second_button_is_ignored(self):
        im=self.frame('skill_zero_result',20);im[483:513,250:324]=95
        ref=self.v.free_daily.refs['count_main_zero'];h,w=ref.shape[:2];im[489:489+h,400:400+w]=ref
        s=self.v.recognize(im);self.assertFalse(any('free_count_' in k for k in s.matches));self.assertNotIn('daily_free_summon',s.matches)
    def test_dimmed_shifted_page_has_no_action_or_completion(self):
        for name in ('skill_two','skill_zero_result'):
            s=self.v.recognize((self.frame(name,20)*.45).astype(np.uint8))
            self.assertNotIn('daily_free_summon',s.matches)
            self.assertNotIn('daily_free_count_0',s.matches)

class RouteTests(RouteHarness,unittest.TestCase):
    def test_shifted_zero_finishes_skill_without_click(self):
        v=Vision();image=LayoutTests().frame('skill_zero_result',20)
        c,d=self.make('daily_summon','skill',[])
        d.capture=lambda:image.copy();c.vision=v
        c.free_summon_step('skill')
        self.assertTrue(c.daily_done('skill'));self.assertEqual(d.clicks,[])
        self.assertFalse(c.daily_detail().get('pending'))

if __name__=='__main__':unittest.main()
