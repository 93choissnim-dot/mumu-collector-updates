"""Guild free coin recovery uses current proof without replaying uncertain input."""
import unittest
from datetime import timedelta
from collector import Halt
from daily_state import ManualQuestLedger,korea_now
import validate_v077_routes as routes
from vision import Screen,Match

class GuildRecoveryTests(unittest.TestCase):
    flow=routes.GuildShopRecoveryTests.flow
    make=routes.GuildShopRecoveryTests.make
    def pending(self,age=2,arm=False):
        c,d=self.flow();c.daily_ledger=ManualQuestLedger(c.daily_ledger.path)
        c.daily_checkpoint('uncertain',pending='shop_confirm_free')
        detail=c.daily_detail();detail['input_request']['requested_at']=(korea_now()-timedelta(days=age)).isoformat()
        c.daily_ledger.update(c.daily_ident,c.daily_task,{'_steps':{'shop':detail}})
        if arm:c.arm_guild_resume()
        return c,d,detail['input_request']
    def test_prior_day_free_allowance_recovers_and_preserves_unknown_history(self):
        c,d,old=self.pending();c.daily_guild_shop()
        self.assertTrue(c.daily_done('shop'));self.assertEqual(len(d.clicks),4)
        h=next(x for x in c.daily_detail()['input_history'] if x['request']['id']==old['id'])
        self.assertFalse(h['resolution']['confirmed'])
        self.assertEqual(h['resolution']['kind'],'retry_authorized')
    def test_same_day_fresh_run_recovers(self):
        c,d,_=self.pending(age=0,arm=True);c.daily_guild_shop()
        self.assertTrue(c.daily_done('shop'))
    def test_same_run_unknown_input_is_not_replayed(self):
        c,d,old=self.pending(age=0)
        with self.assertRaises(Halt):c.daily_guild_shop()
        self.assertEqual(d.clicks,[]);self.assertEqual(c.daily_detail()['input_request'],old)
    def test_future_invalid_and_paid_requests_remain_blocked(self):
        for change in ('future','invalid','paid'):
            c,d,old=self.pending(age=-1 if change=='future' else 2,arm=True)
            detail=c.daily_detail()
            if change=='invalid':detail['input_request']['requested_at']='invalid'
            if change=='paid':detail['pending']=detail['input_request']['action']='paid_purchase'
            c.daily_ledger.update(c.daily_ident,c.daily_task,{'_steps':{'shop':detail}})
            with self.assertRaises(Halt):c.daily_guild_shop()
            self.assertEqual(d.clicks,[])
    def test_verification_mode_cannot_replay(self):
        c,d,_=self.pending();c.daily_verification_only=True
        with self.assertRaises(Halt):c.daily_guild_shop()
        self.assertEqual(d.clicks,[])
    def test_paid_confirmation_never_retires_previous_request(self):
        c,d,old=self.pending();recognize=c.vision.recognize
        def paid(im):
            screen=recognize(im)
            if screen.state=='daily_shop_confirm':
                return Screen(screen.state,{k:v for k,v in screen.matches.items() if k!='daily_shop_confirm_free'})
            return screen
        c.vision.recognize=paid
        with self.assertRaises(Halt):c.daily_guild_shop()
        self.assertEqual(c.daily_detail()['input_request'],old)
        self.assertEqual(len(d.clicks),2)

    def test_midnight_after_reservation_blocks_dispatch(self):
        from unittest.mock import patch
        c,d,_=self.pending();save=c.daily_checkpoint;rollover=False
        def checkpoint(status,**fields):
            nonlocal rollover
            result=save(status,**fields)
            if fields.get('pending')=='shop_confirm_free':rollover=True
            return result
        c.daily_checkpoint=checkpoint
        next_day=(korea_now()+timedelta(days=1)).date().isoformat()
        with patch('free_daily_actions.korea_day',side_effect=lambda:next_day if rollover else c.daily_day):
            with self.assertRaises(Halt):c.daily_guild_shop()
        self.assertTrue(rollover);self.assertEqual(len(d.clicks),2)

    def test_midnight_does_not_settle_yesterdays_reward_proof(self):
        from unittest.mock import patch
        c,d,_=self.pending(age=0)
        c.daily_checkpoint('uncertain',guild_shop_reward_proof=c.daily_guild_shop_reward_identity())
        next_day=(korea_now()+timedelta(days=1)).date().isoformat()
        with patch('free_daily_actions.korea_day',return_value=next_day):
            with self.assertRaises(Halt):c.daily_guild_shop_finish_proof()
        self.assertTrue(c.daily_detail().get('pending'));self.assertFalse(c.daily_done('shop'))

    def test_changed_confirmation_preserves_old_request(self):
        c,d,old=self.pending();tap=c.daily_try_tap
        def change(s,key=None,**kw):
            if key=='shop_confirm_free':return False
            return tap(s,key,**kw)
        c.daily_try_tap=change
        with self.assertRaises(Halt):c.daily_guild_shop()
        self.assertEqual(c.daily_detail()['input_request'],old)
        self.assertEqual(len(d.clicks),2)
    def test_account_change_at_boundary_preserves_old_request(self):
        c,d,old=self.pending();tap=c.daily_try_tap
        def change(s,key=None,**kw):
            if key=='shop_confirm_free':
                c.daily_ident='different-account'
            return tap(s,key,**kw)
        c.daily_try_tap=change
        with self.assertRaises(Halt):c.daily_guild_shop()
        c.daily_ident='account'
        self.assertEqual(c.daily_detail()['input_request'],old)
        self.assertEqual(len(d.clicks),2)
    def test_new_failure_cannot_reuse_inherited_permission(self):
        c,d,_=self.pending(age=0,arm=True);click=d.click
        def fail(p):
            before=d.index;click(p)
            if before==2:raise Halt('transport uncertainty')
        d.click=fail
        with self.assertRaises(Halt):c.daily_guild_shop()
        old=c.daily_detail()['input_request'];n=len(d.clicks)
        with self.assertRaises(Halt):c.daily_guild_shop()
        self.assertEqual(len(d.clicks),n);self.assertEqual(c.daily_detail()['input_request'],old)
    def test_current_claimed_grid_does_not_confirm_previous_day(self):
        c,d,old=self.pending()
        s=Screen('daily_shop',{'daily_'+k:Match('daily_'+k,1,0,(300,100)) for k in ('shop_cube','shop_contract')})
        c.daily_wait=lambda *a,**kw:s
        c.daily_guild_shop()
        self.assertTrue(c.daily_done('shop'));self.assertEqual(len(d.clicks),1)
        h=next(x for x in c.daily_detail()['input_history'] if x['request']['id']==old['id'])
        self.assertFalse(h['resolution']['confirmed'])

if __name__=='__main__':unittest.main()
