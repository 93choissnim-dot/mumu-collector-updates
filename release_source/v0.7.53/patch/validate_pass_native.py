"""Replay only non-personal membership labels and prices from native captures."""
from pathlib import Path
import tempfile
import unittest
import cv2
import numpy as np
from daily_state import DailyLedger
import validate_pass_purchase
from vision import Vision


class NativePassTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vision=Vision()
        cls.atlas=cv2.imdecode(np.fromfile(Path(__file__).parent/'assets/pass_native_fixture.png',np.uint8),1)

    def page(self,key):
        im=np.full((540,960,3),110,np.uint8)
        pieces=[((73,9,128,46),0)]
        pieces+=([((599,80,853,134),38),((600,475,855,520),143)] if key=='keys'
                 else [((151,74,402,123),93),((425,475,690,520),189)])
        for (x,y,r,b),row in pieces:im[y:b,x:r]=self.atlas[row:row+b-y,:r-x]
        return im

    def test_native_paid_pages_complete_without_claim_markers(self):
        for key in ('keys','gear'):
            with self.subTest(key=key):
                screen=self.vision.recognize(self.page(key))
                self.assertEqual(screen.state,'daily_pass_'+key)
                self.assertIn('daily_pass_'+key+'_purchase',screen.matches)
                self.assertNotIn('daily_pass_'+key+'_active',screen.matches)

    def test_dim_wrong_page_and_unrelated_price_cannot_complete(self):
        for key in ('keys','gear'):
            for kind in ('dim','excess_gain','excess_offset','mismatched_title',
                         'title_missing','heading_missing','unrelated_price'):
                with self.subTest(key=key,kind=kind):
                    im=self.page(key)
                    if kind=='dim':im=(im*.55).astype(np.uint8)
                    elif kind=='excess_gain':im=np.clip(im.astype(float)*1.5,0,255).astype(np.uint8)
                    elif kind=='excess_offset':im=np.clip(im.astype(float)+60,0,255).astype(np.uint8)
                    elif kind=='mismatched_title':im[9:46,73:128]=np.clip(im[9:46,73:128].astype(float)+60,0,255)
                    elif kind=='title_missing':im[0:50,60:140]=110
                    elif kind=='heading_missing':im[65:140,140:860]=110
                    else:
                        im[300:345,425:855]=im[475:520,425:855]
                        im[475:520,425:855]=110
                    screen=self.vision.recognize(im)
                    self.assertNotIn('daily_pass_'+key+'_purchase',screen.matches)
                    self.assertNotIn('daily_pass_'+key+'_active',screen.matches)

    def test_paid_pages_survive_native_capture_widths(self):
        for key in ('keys','gear'):
            for width in (960,1280,1920):
                with self.subTest(key=key,width=width):
                    im=cv2.resize(self.page(key),(width,width*9//16),interpolation=cv2.INTER_LINEAR)
                    screen=self.vision.recognize(im)
                    self.assertEqual(screen.state,'daily_pass_'+key)
                    self.assertIn('daily_pass_'+key+'_purchase',screen.matches)

    def test_native_prices_durably_finish_without_purchase_input(self):
        for key in ('keys','gear'):
            with self.subTest(key=key),tempfile.TemporaryDirectory() as folder:
                c=validate_pass_purchase.PurchaseTests().collector(folder);c.daily_step=key
                screen=self.vision.recognize(self.page(key))
                c.daily_wait=lambda *args,**kwargs:screen
                c.daily_ready=lambda *args,**kwargs:screen
                c.daily_pass_tab(key,204,{'daily_pass_'+key})
                c.daily_ledger=DailyLedger(Path(folder)/'daily.json')
                self.assertTrue(c.daily_done(key))
                c.device.click.assert_not_called()


if __name__=='__main__':unittest.main()
