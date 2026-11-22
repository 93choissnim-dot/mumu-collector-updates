"""Reproduce a previous-day loot receipt blocking today's guild entries."""
import unittest
from datetime import timedelta
from unittest.mock import patch
from collector import Halt
from daily_state import ManualQuestLedger,korea_now
from vision import Screen,Match
from validate_v072_free_daily import RouteHarness

def screen(state,keys):
    points={'guild_dungeon_open':(100,100),'guild_fight':(850,490),'guild_loot_claim':(760,348),'sweep_close':(661,145)}
    return Screen(state,{('reward_close' if k=='reward_close' else 'daily_'+k):Match(k,1,0,points.get(k,(300,100))) for k in keys})

class GuildLifecycleTests(RouteHarness,unittest.TestCase):
    def flow(self,age=1,count=3,loot=True,action='guild_loot_claim',verify=False):
        states=[screen('daily_guild_battle',['guild_dungeon_open'])]
        states += [screen('daily_guild_dungeon',['guild_count_'+str(n),'guild_fight','guild_loot_zero']) for n in range(count,0,-1)]
        states += [screen('daily_guild_dungeon',['guild_count_0','guild_loot_claim' if loot else 'guild_loot_zero'])]
        if loot:states += [screen('reward',['reward_close']),screen('daily_guild_dungeon',['guild_count_0','guild_loot_zero'])]
        c,d=self.make('daily_guild','dungeon',states)
        c.daily_ledger=ManualQuestLedger(c.daily_ledger.path);c.daily_verification_only=verify
        c.daily_checkpoint('uncertain',pending=action)
        detail=c.daily_detail();detail['input_request']['requested_at']=(korea_now()-timedelta(days=age)).isoformat()
        c.daily_ledger.update(c.daily_ident,c.daily_task,{'_steps':{'dungeon':detail}})
        old=detail['input_request'].copy()
        c.daily_guild_page=lambda **kw:c.daily_wait({'daily_guild_battle'})
        def combat(*a,on_result=None,**kw):
            result=c.daily_wait({'daily_guild_dungeon'});c.daily_combat_evidence='daily_result'
            if on_result:on_result()
            return result,True
        c.daily_combat=combat
        return c,d,old,states
    def test_old_loot_does_not_block_three_current_entries(self):
        c,d,old,_=self.flow();c.daily_guild_dungeon()
        self.assertTrue(c.daily_done('dungeon'))
        self.assertEqual(sum(p==(850,490) for _,p in d.clicks),3)
        self.assertEqual(sum(p==(760,348) for _,p in d.clicks),1)
        h=next(h for h in c.daily_detail()['input_history'] if h['request']['id']==old['id'])
        self.assertFalse(h['resolution']['confirmed']);self.assertEqual(h['resolution']['source'],'expired_daily_allowance')
    def test_old_loot_with_zero_entries_can_claim_current_reward(self):
        c,d,old,_=self.flow(count=0);c.daily_guild_dungeon()
        self.assertTrue(c.daily_done('dungeon'));self.assertEqual(len(d.clicks),3)
        h=next(h for h in c.daily_detail()['input_history'] if h['request']['id']==old['id'])
        self.assertFalse(h['resolution']['confirmed'])
    def test_current_empty_loot_never_confirms_yesterday(self):
        c,d,old,_=self.flow(count=0,loot=False);c.daily_guild_dungeon()
        h=next(h for h in c.daily_detail()['input_history'] if h['request']['id']==old['id'])
        self.assertFalse(h['resolution']['confirmed']);self.assertEqual(len(d.clicks),1)
    def test_same_day_pending_loot_never_authorizes_entry(self):
        c,d,old,_=self.flow(age=0)
        with self.assertRaisesRegex(Halt,'전리품'):c.daily_guild_dungeon()
        self.assertEqual(len(d.clicks),1);self.assertEqual(c.daily_detail()['input_request'],old)
    def test_malformed_future_paid_and_readonly_remain_preserved(self):
        for mode in ('invalid','future','paid','readonly'):
            c,d,old,_=self.flow(age=-1 if mode=='future' else 1,action='paid_purchase' if mode=='paid' else 'guild_loot_claim',verify=mode=='readonly')
            if mode=='invalid':
                detail=c.daily_detail();detail['input_request']['requested_at']='invalid';old=detail['input_request'].copy()
                c.daily_ledger.update(c.daily_ident,c.daily_task,{'_steps':{'dungeon':detail}})
            with self.assertRaises(Halt):c.daily_guild_dungeon()
            self.assertEqual(c.daily_detail()['input_request'],old);self.assertEqual(len(d.clicks),1)
    def test_ambiguous_counter_cannot_retire_history(self):
        c,d,old,states=self.flow();states[1]=screen('daily_guild_dungeon',['guild_count_2','guild_count_3','guild_fight'])
        with self.assertRaises(Halt):c.daily_guild_dungeon()
        self.assertEqual(c.daily_detail()['input_request'],old);self.assertEqual(len(d.clicks),1)
    def test_guild_reward_dismiss_does_not_touch_underlying_sweep(self):
        c,d,_,_=self.flow(count=0);c.daily_ledger.update(c.daily_ident,c.daily_task,{'_steps':{'dungeon':{}}})
        c.daily_guild_dungeon()
        self.assertIn((480,100),[p for _,p in d.clicks]);self.assertNotIn((640,520),[p for _,p in d.clicks])
    def test_accidental_sweep_is_closed_without_sweeping_or_reclaiming(self):
        c,d,_,states=self.flow(age=0,count=0,loot=False)
        states[1:]=[screen('daily_sweep',['sweep_title','sweep_close','sweep_action']),screen('daily_guild_dungeon',['guild_count_0','guild_loot_zero'])]
        d.index=1
        claimed,_=c.daily_claim_guild_loot()
        self.assertTrue(claimed);self.assertEqual([p for _,p in d.clicks],[(661,145)])
    def test_midnight_after_reservation_prevents_guild_entry(self):
        c,d,_,_=self.flow();save=c.daily_checkpoint;rolled=False
        def reserve(status,**fields):
            nonlocal rolled
            result=save(status,**fields)
            if fields.get('pending')=='guild_fight':rolled=True
            return result
        c.daily_checkpoint=reserve;tomorrow=(korea_now()+timedelta(days=1)).date().isoformat()
        with patch('daily_actions.korea_day',side_effect=lambda:tomorrow if rolled else c.daily_day):
            with self.assertRaises(Halt):c.daily_guild_dungeon()
        self.assertTrue(rolled);self.assertEqual(len(d.clicks),1)

    def test_wait_page_uses_same_safe_guild_reward_point(self):
        c,d,_,states=self.flow(count=0)
        d.index=len(states)-2
        c.wait_page({'daily_guild_dungeon'})
        self.assertEqual([p for _,p in d.clicks],[(480,100)])
    def test_reappearing_sweep_close_is_bounded(self):
        c,d,_,states=self.flow(age=0,count=0,loot=False)
        states[1:]=[screen('daily_sweep',['sweep_title','sweep_close','sweep_action'])]
        d.index=1
        with self.assertRaises(Halt):c.daily_claim_guild_loot(timeout=60)
        self.assertEqual([p for _,p in d.clicks],[(661,145)]*3)
    def test_mismatched_request_action_is_not_retired(self):
        c,d,old,_=self.flow();detail=c.daily_detail();detail['input_request']['action']='guild_fight'
        c.daily_ledger.update(c.daily_ident,c.daily_task,{'_steps':{'dungeon':detail}})
        with self.assertRaises(Halt):c.daily_guild_dungeon()
        self.assertEqual(c.daily_detail()['input_request'],detail['input_request']);self.assertEqual(len(d.clicks),1)
    def test_midnight_after_loot_reservation_prevents_claim(self):
        c,d,_,_=self.flow(count=0);save=c.daily_checkpoint;rolled=False
        def reserve(status,**fields):
            nonlocal rolled
            result=save(status,**fields)
            if fields.get('pending')=='guild_loot_claim':rolled=True
            return result
        c.daily_checkpoint=reserve;tomorrow=(korea_now()+timedelta(days=1)).date().isoformat()
        with patch('daily_actions.korea_day',side_effect=lambda:tomorrow if rolled else c.daily_day):
            with self.assertRaises(Halt):c.daily_guild_dungeon()
        self.assertTrue(rolled);self.assertEqual(len(d.clicks),1)

if __name__=='__main__':unittest.main()
