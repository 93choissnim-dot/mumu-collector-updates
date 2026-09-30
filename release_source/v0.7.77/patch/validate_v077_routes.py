"""Real ledger/routes and privacy-cropped native shop regression cases."""
import base64,json,tempfile,unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
import cv2,numpy as np
from collector import Halt,ScreenChanged
from adb_device import InputNotSent
from daily_state import DailyLedger,ManualQuestLedger,korea_now
from extra_collector import ExtraCollector
from vision import Screen,Match,Vision
from validate_v072_free_daily import RouteHarness

ROOT=Path(__file__).resolve().parent
def fixture(key):
    data=json.loads((ROOT/'assets/v077_shop_cases.json').read_text())
    return cv2.imdecode(np.frombuffer(base64.b64decode(data[key]),np.uint8),1)

class ShopVisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.vision=Vision()
    def test_visible_native_ad_ruby_is_available(self):
        s=self.vision.recognize(fixture('store'))
        self.assertEqual(s.state,'free_store')
        self.assertIn('daily_free_open_ruby_ad',s.matches)
        self.assertNotIn('daily_free_open_ruby',s.matches)
    def test_claimed_guild_shop_is_recognized(self):
        s=self.vision.recognize(fixture('guild'))
        self.assertEqual(s.state,'daily_shop')
        self.assertIn('daily_shop_cube',s.matches)
        self.assertTrue({'daily_shop_contract','daily_shop_exchange'}&s.matches.keys())
        self.assertNotIn('daily_shop_free',s.matches)
    def test_card_missing_free_button_cannot_open(self):
        im=fixture('store');im[420:490,480:690]=0
        s=self.vision.recognize(im)
        self.assertNotIn('daily_free_open_ruby_ad',s.matches)
    def test_dimmed_card_cannot_authorize_free_input(self):
        im=fixture('store');im[55:497,250:925]=(im[55:497,250:925]*.45).astype(np.uint8)
        s=self.vision.recognize(im)
        self.assertNotIn('daily_free_open_ruby_ad',s.matches)
    def test_paid_title_above_does_not_hide_free_card_below(self):
        im=fixture('store');im[92:114,548:623]=im[317:339,548:623]
        s=self.vision.recognize(im)
        self.assertIn('daily_free_open_ruby_ad',s.matches)

class RouteTests(RouteHarness,unittest.TestCase):
    def donate(self,mode):
        c,d=self.make('daily_guild','donation',[])
        c.daily_ledger=ManualQuestLedger(c.daily_ledger.path)
        c.daily_ledger.update(c.daily_ident,c.daily_task,{'donation_paid':2,'donation_verified':2})
        c.daily_guild_page=lambda:None
        screen=Screen('daily_donate',{'daily_donate_50':Match('daily_donate_50',1,0,(518,470))})
        c.daily_wait=lambda *a,**k:screen
        def boundary(*a,before_input,**kw):
            before_input()
            if mode=='changed':return False
            raise mode('boundary')
        c.daily_try_tap=boundary
        with self.assertRaises(Halt):c.daily_guild_donation()
        saved=ManualQuestLedger(c.daily_ledger.path)
        return saved.detail(c.daily_ident,c.daily_task,c.daily_step),saved.get(c.daily_ident,c.daily_task,'donation_paid')
    def test_late_screen_rejection_does_not_spend_or_leave_pending(self):
        detail,paid=self.donate('changed')
        self.assertEqual(paid,2);self.assertFalse(detail.get('pending'))
        self.assertEqual(detail['input_resolution']['kind'],'not_sent')
    def test_local_adb_rejection_does_not_spend_or_leave_pending(self):
        detail,paid=self.donate(InputNotSent)
        self.assertEqual(paid,2);self.assertFalse(detail.get('pending'))
    def test_ambiguous_transport_failure_keeps_reservation(self):
        detail,paid=self.donate(Halt)
        self.assertEqual(paid,3);self.assertEqual(detail['pending'],'donate_50')
    def summon(self,age=1,count=2,action='free_summon',stamp=None):
        s=self.screen
        states=[s('free_summon_character',count,summon=(230,500),identity_character=(840,125)),
                s('free_summon_result_character',1,result_close=(370,495)),
                s('free_summon_character',1,summon=(230,500),identity_character=(840,125)),
                s('free_summon_result_character',0,result_close=(370,495)),
                s('free_summon_character',0,identity_character=(840,125))]
        c,d=self.make('daily_summon','character',states)
        c.daily_ledger=ManualQuestLedger(c.daily_ledger.path)
        c.daily_checkpoint('uncertain',pending=action,before_count=2)
        detail=c.daily_detail();detail['input_request']['requested_at']=stamp if stamp is not None else (korea_now()-timedelta(days=age)).isoformat()
        c.daily_ledger.update(c.daily_ident,c.daily_task,{'_steps':{'character':detail}})
        return c,d
    def test_prior_day_pending_retired_unconfirmed_with_fresh_two_allowance(self):
        c,d=self.summon();old=c.daily_detail()['input_request']['id']
        c.free_summon_step('character')
        self.assertTrue(c.daily_done('character'));self.assertEqual(len(d.clicks),4)
        history=c.daily_detail()['input_history'];first=next(h for h in history if h['request']['id']==old)
        self.assertFalse(first['resolution']['confirmed'])
        self.assertEqual(first['resolution']['source'],'fresh_daily_allowance')
    def test_same_day_future_unknown_or_wrong_action_is_not_rearmed(self):
        for kwargs in ({'age':0},{'age':-1},{'stamp':'invalid'},{'action':'paid_summon'},{'stamp':'2026-09-29T23:00:00'}):
            with self.subTest(kwargs=kwargs):
                c,d=self.summon(**kwargs)
                with self.assertRaises(Halt):c.free_summon_step('character')
                self.assertEqual(d.clicks,[]);self.assertTrue(c.daily_detail().get('pending'))
    def test_prior_day_partial_allowance_is_not_previous_day_completion(self):
        c,d=self.summon(count=1)
        with self.assertRaises(Halt):c.free_summon_step('character')
        self.assertEqual(d.clicks,[]);self.assertTrue(c.daily_detail().get('pending'))
    def test_count_decrease_does_not_confirm_unknown_or_wrong_origin(self):
        for kwargs in ({'stamp':'invalid'},{'stamp':'2026-09-29T23:00:00'},
                       {'age':0,'action':'paid_summon'},{'stamp':''}):
            with self.subTest(kwargs=kwargs):
                c,d=self.summon(count=1,**kwargs)
                old=c.daily_detail()['input_request']
                with self.assertRaises(Halt):c.free_summon_step('character')
                self.assertEqual(d.clicks,[])
                self.assertEqual(c.daily_detail()['input_request'],old)
                self.assertFalse(c.daily_detail().get('input_history'))
    def test_committed_input_rejection_retires_only_current_request(self):
        c,d=self.make('daily_guild','shop',[])
        def reject(*a,before_input,**kw):before_input();return False
        c.daily_try_tap=reject
        self.assertFalse(c.daily_committed_tap(Screen('daily_shop_confirm',{}),'shop_confirm_free'))
        self.assertFalse(c.daily_detail().get('pending'))
    def test_stationary_store_scroll_is_bounded(self):
        s=self.screen('free_store',selected_currency=(100,80))
        c,d=self.make('daily_store','ruby_ad',[s]);moves=[]
        d.drag=lambda *args:moves.append(args)
        with self.assertRaises(Halt):c.free_store_find('ruby_ad')
        self.assertLessEqual(len(moves),4)

class GuildShopRecoveryTests(RouteHarness,unittest.TestCase):
    def flow(self):
        def s(state,**keys):return Screen(state,{'daily_'+k:Match('daily_'+k,1,0,p) for k,p in keys.items()})
        menu=s('daily_guild_menu',guild_shop_open=(200,200))
        c,d=self.make('daily_guild','shop',[
            menu,s('daily_shop',shop_coin=(350,90),shop_free=(360,235)),
            s('daily_shop_confirm',shop_confirm_free=(480,390),shop_confirm_title=(480,90),
              shop_confirm_item=(480,180),shop_confirm_close=(630,90)),
            Screen('reward',{'reward_close':Match('reward_close',1,0,(640,520))}),
            s('daily_shop',shop_cube=(360,75))])
        c.daily_guild_page=lambda:menu
        return c,d
    def test_actual_reward_completes_even_if_post_grid_labels_change(self):
        c,d=self.flow();c.daily_guild_shop()
        self.assertTrue(c.daily_done('shop'));self.assertEqual(len(d.clicks),4)
        self.assertEqual(c.daily_detail()['input_resolution']['source'],'guild_shop_reward_confirmed')
    def test_reward_proof_survives_crash_during_close(self):
        c,d=self.flow();click=d.click
        def crash(point):
            before=d.index;click(point)
            if before==3:raise Halt('process exited')
        d.click=crash
        with self.assertRaises(Halt):c.daily_guild_shop()
        c.daily_ledger=DailyLedger(c.daily_ledger.path)
        c.daily_guild_page=lambda:(_ for _ in ()).throw(AssertionError('proof requires no navigation'))
        c.daily_guild_shop();self.assertTrue(c.daily_done('shop'))
    def test_unrelated_reward_does_not_set_proof(self):
        c,d=self.flow();c.daily_checkpoint('uncertain',pending='shop_confirm_free');d.index=3
        c.daily_wait({'daily_shop'})
        self.assertNotIn('guild_shop_reward_proof',c.daily_detail())
        with self.assertRaises(Halt):c.daily_guild_shop()
        self.assertFalse(c.daily_done('shop'))
    def test_proof_save_failure_leaves_reward_open(self):
        from daily_state import LedgerError
        c,d=self.flow();save=c.daily_checkpoint
        def fail(status,**fields):
            if 'guild_shop_reward_proof' in fields:raise LedgerError('disk full')
            return save(status,**fields)
        c.daily_checkpoint=fail
        with self.assertRaises(LedgerError):c.daily_guild_shop()
        self.assertEqual(d.index,3)

if __name__=='__main__':unittest.main()
