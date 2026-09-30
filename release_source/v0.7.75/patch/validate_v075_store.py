"""Attributed reward proof survives a crash; visible store cards avoid movement."""
import unittest
from unittest.mock import patch
from validate_v072_free_daily import RouteHarness
from daily_state import DailyLedger,LedgerError
from collector import Halt
from vision import Screen,Match

class StoreRecoveryTests(RouteHarness,unittest.TestCase):
    def flow(self):
        return self.make('daily_store','cube_ad',[
            self.screen('free_store_confirm_cube_ad',confirm_cube_ad=(480,387),dialog_close=(631,86)),
            Screen('reward',{'reward_close':Match('reward_close',1,0,(640,520))}),
            self.screen('free_store',cube_absent=(359,85),selected_general=(73,30),tab_general=(100,267),home=(919,28))])
    def interrupted(self):
        c,d=self.flow();click=d.click
        def crash(point):
            before=d.index;click(point)
            if before==1:raise Halt('simulated process exit after reward close')
        d.click=crash
        with self.assertRaises(Halt):c.free_store_step('cube_ad')
        self.assertEqual(d.index,2);self.assertTrue(c.daily_detail().get('pending'))
        return c,d
    def resumed(self,c):
        new,d=self.make('daily_store','cube_ad',[self.screen('free_store',cube_absent=(359,85),selected_general=(73,30),tab_general=(100,267),home=(919,28))])
        new.daily_ledger=DailyLedger(c.daily_ledger.path);d.drag=lambda *_:None
        return new,d
    def test_observed_reward_is_durable_before_close(self):
        c,d=self.interrupted();new,nd=self.resumed(c)
        new.free_store_step('cube_ad')
        self.assertTrue(new.daily_done('cube_ad'));self.assertFalse(new.daily_detail().get('pending'))
        self.assertEqual(nd.clicks,[])
    def test_proof_storage_failure_keeps_reward_open(self):
        c,d=self.flow();save=c.daily_checkpoint
        def failed(status,**fields):
            if 'store_reward_proof' in fields:raise LedgerError('disk full')
            return save(status,**fields)
        c.daily_checkpoint=failed
        with self.assertRaises(LedgerError):c.free_store_step('cube_ad')
        self.assertEqual(d.index,1);self.assertEqual(len(d.clicks),1)
    def test_unrelated_reward_cannot_resolve_old_pending(self):
        c,d=self.flow();c.daily_checkpoint('uncertain',pending='free_confirm_cube_ad')
        d.index=1
        c.daily_wait({'free_store'})
        self.assertNotIn('store_reward_proof',c.daily_detail())
        new,nd=self.resumed(c)
        with self.assertRaises(Halt):new.free_store_step('cube_ad')
        self.assertFalse(new.daily_done('cube_ad'))
    def test_wrong_request_or_day_proof_is_not_used(self):
        for field,value in [('request_id','different'),('day','2000-01-01'),('step','ruby'),('account','other')]:
            with self.subTest(field=field):
                c,d=self.interrupted();proof=dict(c.daily_detail().get('store_reward_proof',{}));proof[field]=value
                c.daily_checkpoint('uncertain',store_reward_proof=proof)
                new,nd=self.resumed(c)
                with self.assertRaises(Halt):new.free_store_step('cube_ad')
                self.assertFalse(new.daily_done('cube_ad'))
    def test_visible_card_in_selected_tab_has_no_navigation_input(self):
        for key,tab in [('ruby','currency'),('ruby_ad','currency'),('cube_ad','general')]:
            with self.subTest(key=key):
                c,d=self.make('daily_store',key,[self.screen('free_store',**{'open_'+key:(359,232),'selected_'+tab:(73,30),'tab_'+tab:(100,83)})])
                drags=[];d.drag=lambda *args:drags.append(args)
                found=c.free_store_find(key)
                self.assertTrue(c.daily_has(found,'free_open_'+key));self.assertEqual(drags,[]);self.assertEqual(d.clicks,[])
