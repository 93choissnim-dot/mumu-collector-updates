"""Replay real ADB zero-count glyphs, retaining only non-personal page ROIs."""
from pathlib import Path
import unittest
import tempfile
import cv2
import numpy as np
from autumn_vision import AutumnVision
from vision import Vision


class NativeAutumnTests(unittest.TestCase):
    def setUp(self):
        assets=Path(__file__).parent/'assets'
        self.v=AutumnVision(assets)
        self.frame=cv2.imdecode(np.fromfile(assets/'autumn_native_empty_fixture.png',np.uint8),cv2.IMREAD_COLOR)
        self.assertIsNotNone(self.frame)

    def test_reported_empty_is_recognized_without_claim(self):
        screen=Vision().recognize(self.frame)
        self.assertEqual(screen.state,'autumn')
        self.assertIn('autumn_empty',screen.matches)
        self.assertIn('autumn_zero',screen.matches)
        self.assertNotIn('autumn_active',screen.matches)

    def test_blank_nonzero_and_damaged_counts_are_not_empty(self):
        for kind in ('blank','one','eight','ten','damaged'):
            with self.subTest(kind=kind):
                im=self.frame.copy()
                # Pixel-derived digits from the same rendered (0/10) counter.
                if kind=='blank':im[494:519,771:824]=50
                elif kind=='one':
                    one=im[499:513,796:804].copy()
                    im[499:513,780:792]=im[498:499,780:792]
                    im[499:513,782:790]=one
                elif kind=='eight':im[505:507,784:789]=im[501:503,784:789].copy()
                elif kind=='ten':
                    counter=im[498:515,775:820].copy()
                    wider=np.concatenate((counter[:,:6],counter[:,21:29],counter[:,6:]),axis=1)
                    im[498:515,771:824]=wider
                else:im[501:512,786:789]=50
                _,matches=self.v.recognize(im)
                self.assertNotIn('autumn_zero',matches)
                self.assertNotIn('autumn_empty',matches)
                self.assertNotIn('autumn_active',matches)

    def test_notice_or_missing_identity_prevents_empty(self):
        for kind in ('notice','title','home','dark'):
            with self.subTest(kind=kind):
                im=self.frame.copy()
                if kind=='notice':im[473:485,922:934]=(30,30,210)
                elif kind=='dark':im=(im*.5).astype(np.uint8)
                else:
                    x,y,r,b=self.v.specs['autumn_'+kind]['box'];im[y-4:b+4,x-4:r+4]=110
                _,matches=self.v.recognize(im)
                self.assertNotIn('autumn_empty',matches)
                self.assertNotIn('autumn_active',matches)

    def test_reported_zero_survives_small_exposure_and_position_changes(self):
        for shift,gain,offset in ((0,1.,0),(-2,.96,2),(2,1.02,-2)):
            with self.subTest(shift=shift):
                im=np.roll(self.frame,shift,axis=1)
                im=np.clip(im.astype(float)*gain+offset,0,255).astype(np.uint8)
                _,matches=self.v.recognize(im)
                self.assertIn('autumn_empty',matches)
                self.assertNotIn('autumn_active',matches)

    def test_real_zero_clears_durable_pending_without_another_claim(self):
        from action_state import ActionState
        from validate_autumn import RouteTests
        d,c=RouteTests().collector(empty=True)
        recognize=c.vision.recognize
        full=Vision()
        c.vision.recognize=lambda im:full.recognize(self.frame) if d.state=='autumn' else recognize(im)
        click=d.click
        d.click=lambda point:click((919,28) if d.state=='autumn' and point==(919.5,31.) else point)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'actions.json'
            c.action_state=ActionState(path,'vm');c.action_state.reserve('autumn')
            self.assertEqual(c.cycle(['autumn']),{'autumn':'collected'})
            self.assertEqual(d.claims,0)
            self.assertFalse(ActionState(path,'vm').pending('autumn'))
            self.assertEqual(c.cycle(['autumn']),{'autumn':'skipped'})
            self.assertEqual(d.claims,0)


if __name__=='__main__':unittest.main()
