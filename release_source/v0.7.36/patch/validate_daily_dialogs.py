"""Free coin confirmation, clear layouts, and guarded modal input."""
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock
import cv2
import numpy as np
from collector import Halt
from daily_state import DailyLedger,korea_day
from extra_collector import ExtraCollector
from vision import Vision,Screen,Match

MODAL=('shop_confirm_title','shop_confirm_item','shop_confirm_close','shop_confirm_free')

def page(state,*names):
    return Screen(state,{'daily_'+n:Match('daily_'+n,1,0,(480,408)) for n in names})

class DialogVisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.v=Vision()
    def frame(self,*names):
        im=np.full((540,960,3),70,np.uint8)
        for name in names:
            x,y,r,b=self.v.daily.specs[name]['box'];ref=self.v.daily.templates[name][0]
            # Labels live on continuous panels, not isolated cutouts whose
            # artificial borders introduce new edges during resizing.
            im[y-3:b+3,x-3:r+3]=cv2.copyMakeBorder(ref,3,3,3,3,cv2.BORDER_REPLICATE)
        return im
    def test_coin_modal_at_three_sizes_and_native_exposure(self):
        for gain,offset in (([1,1,1],[0,0,0]),([1.22,1.17,1.12],[22,2,-4])):
            im=np.clip(self.frame(*MODAL).astype(float)*gain+offset,0,255).astype(np.uint8)
            for w in (640,960,1280):
                s=self.v.recognize(cv2.resize(im,(w,w*9//16)))
                self.assertEqual(s.state,'daily_shop_confirm')
                self.assertIn('daily_shop_confirm_free',s.matches)
    def test_modal_requires_item_identity_and_close_not_free_alone(self):
        for missing in MODAL[:3]:
            s=self.v.recognize(self.frame(*(n for n in MODAL if n!=missing)))
            self.assertNotEqual(s.state,'daily_shop_confirm')
    def test_paid_price_is_never_a_free_button(self):
        im=self.frame(*MODAL[:3]);cv2.putText(im,'3000',(454,416),cv2.FONT_HERSHEY_SIMPLEX,.5,(220,220,220),1)
        s=self.v.recognize(im)
        self.assertEqual(s.state,'daily_shop_confirm');self.assertNotIn('daily_shop_confirm_free',s.matches)
    def test_both_leave_layouts_use_text_center(self):
        for name in ('battle_leave','battle_leave_pair'):
            im=self.frame('battle_clear',name)
            for w in (640,960,1280):
                s=self.v.recognize(cv2.resize(im,(w,w*9//16)))
                self.assertEqual(s.state,'daily_clear')
                x,y=s.matches['daily_battle_leave'].center
                self.assertLess(abs(x-(481 if name=='battle_leave' else 398)),2)
                self.assertLess(abs(y-474),2)
    def test_clear_without_leave_and_leave_without_clear_are_not_actionable(self):
        for names in (('battle_clear',),('battle_leave',),('battle_leave_pair',)):
            self.assertNotEqual(self.v.recognize(self.frame(*names)).state,'daily_clear')

class GuildCoinFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.c=ExtraCollector(Mock(),Mock(),threading.Event(),Mock())
        c=self.c;c.daily_ledger=DailyLedger(Path(self.tmp.name)/'daily.json')
        c.daily_ident='vm';c.daily_day=korea_day();c.daily_task='daily_guild';c.daily_step='shop'
        c.daily_guild_page=Mock(return_value=page('daily_guild_menu','guild_shop_open'))
        self.shop=page('daily_shop','shop_coin','shop_free')
        self.modal=page('daily_shop_confirm',*MODAL)
        self.done=page('daily_shop','shop_cube','shop_contract')
    def test_confirmation_is_clicked_once_then_completion_is_proved(self):
        c=self.c;c.daily_wait=Mock(side_effect=[self.shop,self.modal,self.done])
        c.daily_ready=Mock(return_value=self.modal);c.daily_tap=Mock()
        c.daily_guild_shop()
        self.assertEqual([call.args[1] for call in c.daily_tap.call_args_list],['guild_shop_open','shop_free','shop_confirm_free'])
        self.assertTrue(c.daily_done('shop'))
    def test_missing_free_button_never_confirms_or_marks_done(self):
        c=self.c;c.daily_wait=Mock(side_effect=[self.shop,self.modal]);c.daily_tap=Mock()
        c.daily_ready=Mock(side_effect=Halt('free label missing'))
        with self.assertRaises(Halt):c.daily_guild_shop()
        self.assertEqual(c.daily_tap.call_count,2);self.assertFalse(c.daily_done('shop'))
    def test_unchanged_shop_is_not_marked_done(self):
        c=self.c;c.daily_wait=Mock(side_effect=[self.shop,self.modal,self.shop]);c.daily_tap=Mock()
        c.daily_ready=Mock(return_value=self.modal)
        with self.assertRaises(Halt):c.daily_guild_shop()
        self.assertFalse(c.daily_done('shop'))
    def test_item_or_free_label_changes_on_fresh_capture_block_input(self):
        c=self.c
        for missing in MODAL:
            c.screen=Mock(return_value=page('daily_shop_confirm',*(n for n in MODAL if n!=missing)))
            with self.assertRaises(Halt):
                c.daily_tap(self.modal,'shop_confirm_free',required=MODAL[:3])
        c.device.click.assert_not_called()
    def test_already_claimed_shop_never_opens_confirmation(self):
        c=self.c;c.daily_wait=Mock(return_value=self.done);c.daily_tap=Mock()
        c.daily_guild_shop()
        self.assertEqual(c.daily_tap.call_count,1);self.assertTrue(c.daily_done('shop'))

if __name__=='__main__':unittest.main()
