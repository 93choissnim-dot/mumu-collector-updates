"""Price-only memberships finish without purchase inputs or false claims."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock
import cv2
import numpy as np
from collector import Halt
from daily_state import DailyLedger,korea_day
from extra_collector import ExtraCollector
from vision import Vision,Screen,Match


class PurchaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vision=Vision()
        cls.price=cv2.imread(str(Path(__file__).parent/'assets/pass_purchase.png'))[:23,:90]

    def page(self,key,amount=True,context=True):
        im=np.full((540,960,3),110,np.uint8)
        if context:
            for name in ('pass_title','pass_'+key):
                x,y,r,b=self.vision.daily.specs[name]['box']
                im[y:b,x:r]=self.vision.daily.templates[name][0]
        x=500 if key=='gear' else 690
        im[485:508,x:x+90]=self.price
        if not amount:im[485:508,x+23:x+90]=110
        return im

    def collector(self,tmp):
        c=ExtraCollector(Mock(),Mock(),threading.Event(),Mock(),on_issue=Mock())
        c.daily_ledger=DailyLedger(Path(tmp)/'daily.json');c.daily_ident='test'
        c.daily_day=korea_day();c.daily_task='daily_pass';c.daily_step='gear'
        c.daily_main=Mock();c.daily_open=Mock();c.daily_recover=Mock()
        return c

    def test_all_memberships_detect_price_but_no_claim(self):
        for key in ('ad','keys','gear'):
            with self.subTest(key=key):
                s=self.vision.recognize(self.page(key))
                self.assertEqual(s.state,'daily_pass_'+key)
                self.assertIn('daily_pass_'+key+'_purchase',s.matches)
                self.assertNotIn('daily_pass_'+key+'_active',s.matches)

    def test_currency_alone_wrong_page_or_dim_overlay_is_not_completion(self):
        for im in (self.page('gear',amount=False),self.page('gear',context=False),
                   (self.page('gear')*.55).astype(np.uint8)):
            self.assertNotIn('daily_pass_gear_purchase',self.vision.recognize(im).matches)

    def test_free_claim_and_claimed_buttons_remain_distinct_from_price(self):
        for key in ('ad','keys','gear'):
            for state in ('active','done'):
                im=self.page(key);im[465:530,425:855]=110
                name='pass_'+key+'_'+state;x,y,r,b=self.vision.daily.specs[name]['box']
                im[y:b,x:r]=self.vision.daily.templates[name][0]
                s=self.vision.recognize(im)
                self.assertIn('daily_'+name,s.matches)
                self.assertNotIn('daily_pass_'+key+'_purchase',s.matches)

    def test_each_price_step_is_durable_and_later_memberships_still_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=self.collector(tmp);visited=[]
            def observed(*args,**kwargs):
                visited.append(c.daily_step)
                return self.vision.recognize(self.page(c.daily_step))
            c.daily_wait=observed;c.daily_ready=observed;c.daily_tap=Mock()
            self.assertEqual(c.collect_daily('daily_pass'),'already_complete')
            c.device.click.assert_not_called();c.daily_tap.assert_not_called()
            self.assertEqual(set(visited),{'ad','keys','gear'})
            c.daily_ledger=DailyLedger(Path(tmp)/'daily.json')
            self.assertTrue(c.daily_done('_complete'))
            for key in ('ad','keys','gear'):self.assertTrue(c.daily_done(key))

    def test_price_reconciles_pending_claim_without_another_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=self.collector(tmp);c.daily_checkpoint('uncertain',pending='pass_gear_active')
            s=self.vision.recognize(self.page('gear'))
            c.daily_wait=Mock(return_value=s);c.daily_ready=Mock(return_value=s)
            c.daily_pass_tab('gear',204,{'daily_pass_gear'})
            self.assertTrue(c.daily_done('gear'));self.assertIsNone(c.daily_detail().get('pending'))
            c.device.click.assert_not_called()

    def test_fresh_price_blocks_stale_claim_even_with_conflicting_claim_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=self.collector(tmp);name='daily_pass_gear_active';m=Match(name,1,0,(500,495))
            old=Screen('daily_pass_gear',{name:m})
            fresh=self.vision.recognize(self.page('gear'));fresh.matches[name]=m
            c.screen=Mock(return_value=fresh)
            with self.assertRaises(Halt):c.daily_tap(old,'pass_gear_active')
            c.device.click.assert_not_called()

    def test_old_price_timeout_rechecks_without_resetting_other_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=self.collector(tmp)
            c.daily_checkpoint('blocked',reason='일일 작업 버튼 확인 시간 초과: pass_gear_done, pass_gear_active',failures=2)
            action=Mock(side_effect=lambda:c.daily_mark('gear'))
            c.daily_run_step('gear','장비 멤버십',action)
            action.assert_called_once();self.assertTrue(c.daily_done('gear'))
            c.daily_step='keys';c.daily_checkpoint('blocked',reason='other failure')
            other=Mock();c.daily_run_step('keys','던전 멤버십',other);other.assert_not_called()


if __name__=='__main__':unittest.main()
