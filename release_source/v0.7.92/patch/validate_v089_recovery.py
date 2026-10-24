"""Fresh-run reconciliation and acknowledged navigation regressions."""
import unittest
from unittest.mock import Mock
import numpy as np
from validate_v072_free_daily import RouteHarness
from vision import Screen,Match
from collector import Halt

class FreshFreeTests(RouteHarness,unittest.TestCase):
    def test_new_run_rechecks_remaining_free_summon_and_keeps_old_uncertainty(self):
        s=self.screen
        c,d=self.make('daily_summon','pet',[
            s('free_summon_pet',1,summon=(230,500),identity_pet=(840,125)),
            s('free_summon_pet',0,identity_pet=(840,125))])
        c.daily_checkpoint('uncertain',pending='free_summon',before_count=1)
        old=c.daily_detail()['input_request']['id']
        self.assertTrue(hasattr(c,'arm_free_resume'))
        c.arm_free_resume();c.free_summon_step('pet')
        self.assertTrue(c.daily_done('pet'));self.assertEqual(len(d.clicks),1)
        history=c.daily_detail()['input_history']
        archived=next(x for x in history if x['request']['id']==old)
        self.assertFalse(archived['resolution']['confirmed'])

    def test_new_run_permission_cannot_replay_new_failed_input(self):
        s=self.screen
        c,d=self.make('daily_summon','pet',[s('free_summon_pet',1,summon=(230,500),identity_pet=(840,125))],stuck=True)
        c.daily_checkpoint('uncertain',pending='free_summon',before_count=1)
        self.assertTrue(hasattr(c,'arm_free_resume'))
        c.arm_free_resume()
        with self.assertRaises(Halt):c.free_summon_step('pet')
        c.arm_free_resume()
        with self.assertRaises(Halt):c.free_summon_step('pet')
        self.assertEqual(len(d.clicks),1)

    def test_missing_free_label_never_retires_history(self):
        c,d=self.make('daily_summon','pet',[self.screen('free_summon_pet',1,identity_pet=(840,125))])
        c.daily_checkpoint('uncertain',pending='free_summon',before_count=1)
        self.assertTrue(hasattr(c,'arm_free_resume'));c.arm_free_resume()
        with self.assertRaises(Halt):c.free_summon_step('pet')
        self.assertEqual(d.clicks,[]);self.assertTrue(c.daily_detail()['pending'])

class CubeRecognitionTests(unittest.TestCase):
    def frame(self,counter='card_zero'):
        from free_daily_vision import FreeDailyVision
        from pathlib import Path
        v=FreeDailyVision(Path(__file__).parent/'assets')
        im=np.full((540,960,3),60,np.uint8)
        for k,x,y in [('store_header',18,13),('store_home',905,14),('card_cube',736,315),(counter,758,288)]:
            tile=v.refs[k];h,w=tile.shape[:2];im[y:y+h,x:x+w]=tile
        im[251:278,73:155]=[140,180,205]
        return v,im
    def test_visible_exhausted_cube_card_is_done(self):
        v,im=self.frame();state,m=v.recognize(im)
        self.assertEqual(state,'free_store');self.assertIn('daily_free_done_cube_ad',m)
        self.assertNotIn('daily_free_open_cube_ad',m)
    def test_available_or_unreadable_cube_is_not_done(self):
        for counter in ['card_one',None]:
            v,im=self.frame(counter or 'card_zero')
            if counter is None:im[288:308,758:840]=0
            self.assertNotIn('daily_free_done_cube_ad',v.recognize(im)[1])

class NavigationTests(RouteHarness,unittest.TestCase):
    def test_final_sleep_pass_does_not_wake_already_sleeping_game(self):
        c,d=self.make('daily_dungeons','return',[Screen('sleep',{})])
        self.assertEqual(c.cycle([],True),{})
        self.assertEqual(d.clicks,[])

    def daily(self,state,**keys):
        return Screen(state,{'daily_'+k:Match('daily_'+k,1,0,p) for k,p in keys.items()})
    def test_relic_close_reobserves_after_ignored_first_click(self):
        room=self.daily('daily_relic',relic_close=(790,86));menu=self.daily('daily_guild_menu')
        c,d=self.make('daily_guild','relic',[room,room,menu])
        self.assertTrue(hasattr(c,'daily_close_relic'));c.daily_close_relic()
        self.assertEqual(d.index,2);self.assertEqual(len(d.clicks),2)
    def test_relic_close_is_bounded(self):
        c,d=self.make('daily_guild','relic',[self.daily('daily_relic',relic_close=(790,86))],stuck=True)
        self.assertTrue(hasattr(c,'daily_close_relic'))
        with self.assertRaises(Halt):c.daily_close_relic()
        self.assertEqual(len(d.clicks),3)
    def test_free_key_retries_only_literal_free_with_zero_entries(self):
        page='daily_room_treasure'
        free=self.daily(page,d_free_1=(744,440),d_count_0=(680,392))
        enter=self.daily(page,d_enter=(744,440))
        c,d=self.make('daily_dungeons','treasure',[free,free,enter])
        self.assertTrue(hasattr(c,'daily_claim_free_key'))
        returned=c.daily_claim_free_key(page)
        self.assertIn('daily_d_enter',returned.matches);self.assertEqual(len(d.clicks),2)
    def test_unreadable_free_key_counter_sends_nothing(self):
        page='daily_room_treasure'
        c,d=self.make('daily_dungeons','treasure',[self.daily(page,d_free_1=(744,440))])
        self.assertTrue(hasattr(c,'daily_claim_free_key'))
        with self.assertRaises(Halt):c.daily_claim_free_key(page)
        self.assertEqual(d.clicks,[])
    def test_boss_overlay_before_sleep_is_observed_until_menu_returns(self):
        menu=Screen('menu',{'sleep_menu':Match('sleep_menu',1,0,(838,501))})
        c,d=self.make('daily_dungeons','return',[menu,Screen('sleep',{})])
        recognize=c.vision.recognize;reads=[0]
        def observed(im):
            reads[0]+=1
            return Screen('unknown',{}) if 3<=reads[0]<=6 else recognize(im)
        c.vision.recognize=observed
        self.assertTrue(hasattr(c,'restore_sleep_after_work'));c.restore_sleep_after_work()
        self.assertEqual(d.index,1);self.assertEqual(len(d.clicks),1)

class DonationTests(RouteHarness,unittest.TestCase):
    def test_previous_day_paid_pending_does_not_block_current_free_donation(self):
        from datetime import datetime,timedelta
        from daily_state import KST
        def page(state,**keys):return Screen(state,{'daily_'+k:Match(k,1,0,p) for k,p in keys.items()})
        c,d=self.make('daily_guild','donation',[
            page('daily_guild_menu',guild_donate_open=(100,100)),
            page('daily_donate',donate_free=(480,470),donate_close=(690,50)),
            page('daily_guild_menu',guild_donated=(100,100))])
        c.daily_guild_page=lambda:c.daily_wait({'daily_guild_menu','daily_donate'})
        c.daily_checkpoint('uncertain',pending='donate_50',values={'donation_paid':1})
        entry=c.daily_ledger.data[c.daily_ident][c.daily_day]['daily_guild']['_steps']['donation']
        entry['input_request']['requested_at']=(datetime.now(KST)-timedelta(days=1)).isoformat()
        try:c.daily_guild_donation()
        except Halt:pass
        self.assertTrue(c.daily_done('donation'))
        self.assertEqual([p for _,p in d.clicks],[(100,100),(480,470)])
        self.assertFalse(c.daily_detail()['input_history'][0]['resolution']['confirmed'])

class ReviewOrderTests(unittest.TestCase):
    def test_review_precedes_only_sleep_pass(self):
        import run_review,threading
        self.assertTrue(hasattr(run_review,'run_reviewed_cycle'))
        c=Mock();c.daily_ledger=None;c.action_state.get.return_value={};c.action_state.blocked.return_value=False
        c.manual_retry_tasks=set();calls=[]
        c.results={};c.claim_counts={'farm':2}
        def execute(tasks,restore=False):
            calls.append((list(tasks),restore))
            if not tasks:c.results={};c.claim_counts={}
            return {'farm':'failed' if len(calls)==1 else 'collected'} if tasks else {}
        result=run_review.run_reviewed_cycle(c,['farm'],execute,lambda _:None,threading.Event())
        self.assertEqual(calls,[(['farm'],False),(['farm'],False),([],True)])
        self.assertEqual(result,{'farm':'collected'})
        self.assertEqual(c.results,{'farm':'collected'})
        self.assertEqual(c.claim_counts,{'farm':2})


class RegularFreeResumeTests(unittest.TestCase):
    def facility(self,room='mine',**kwargs):
        from validate_collection import CollectionRegression
        c,d,clock,_=CollectionRegression().run_flow(**kwargs)
        c.now=clock.monotonic;d.state=room
        return c,d

    def test_current_version_pending_retries_each_facility_and_keeps_uncertain_history(self):
        for room in ('farm','wood','mine'):
            with self.subTest(room=room):
                c,d=self.facility(room);c.action_state.reserve(room)
                old=c.action_state.pending(room)['id']
                c.arm_regular_free_resume()
                c.collect_room(room,c.screen())
                self.assertEqual(d.claims[room],1)
                self.assertEqual(c.results[room],'collected')
                history=c.action_state.get(room)['input_history']
                prior=next(x for x in history if x['request']['id']==old)
                self.assertFalse(prior['resolution']['confirmed'])
                self.assertEqual(prior['resolution']['source'],'fresh_run_free_claim_retry')

    def test_retry_permission_cannot_rearm_a_new_failure_during_same_run(self):
        c,d=self.facility(post={'mine':'ready'});c.action_state.reserve('mine')
        c.arm_regular_free_resume();c.collect_room('mine',c.screen())
        new=c.action_state.pending('mine')['id']
        c.arm_regular_free_resume();c.collect_room('mine',c.screen())
        self.assertEqual(d.claims['mine'],1)
        self.assertEqual(c.action_state.pending('mine')['id'],new)
        self.assertEqual(c.results['mine'],'deferred')

    def test_unknown_current_button_preserves_old_request_without_click(self):
        c,d=self.facility(initial_modes={'mine':'wait'});c.action_state.reserve('mine')
        old=c.action_state.pending('mine').copy();c.arm_regular_free_resume()
        c.collect_room('mine',c.screen())
        self.assertEqual(d.claims['mine'],0)
        self.assertEqual(c.action_state.pending('mine'),old)

    def test_empty_current_button_reconciles_without_click(self):
        c,d=self.facility(initially_empty=True);c.action_state.reserve('mine')
        c.arm_regular_free_resume();c.collect_room('mine',c.screen())
        self.assertEqual(d.claims['mine'],0)
        self.assertFalse(c.action_state.pending('mine'))

    def test_paid_or_unknown_action_is_never_armed(self):
        c,d=self.facility()
        for task,slot in [('daily_guild','donate_50'),('daily_dungeons','enter'),('training','claim'),('mine','upgrade')]:
            c.action_state.reserve(task,slot)
        c.arm_regular_free_resume()
        for task,slot in [('daily_guild','donate_50'),('daily_dungeons','enter'),('training','claim'),('mine','upgrade')]:
            self.assertFalse(c.can_retry_regular_free(task,slot))

    def test_retry_permission_cannot_cross_account_or_ledger(self):
        from action_state import ActionState
        c,d=self.facility();c.action_state.reserve('mine');c.arm_regular_free_resume()
        original=c.action_state;c.action_state=ActionState()
        c.action_state.update('mine',**original.get('mine'))
        self.assertFalse(c.can_retry_regular_free('mine'))
        c.action_state=original;c.action_state.scope='other'
        self.assertFalse(c.can_retry_regular_free('mine'))

    def test_next_run_retries_the_persisted_failure(self):
        c,d=self.facility(post={'mine':'ready'});c.action_state.reserve('mine')
        c.arm_regular_free_resume();c.collect_room('mine',c.screen())
        fresh,device=self.facility();fresh.action_state=c.action_state
        fresh.arm_regular_free_resume();fresh.collect_room('mine',fresh.screen())
        self.assertEqual(device.claims['mine'],1)
        self.assertEqual(fresh.results['mine'],'collected')


    def test_all_extra_free_slots_retry_current_pending(self):
        from validate_extra import Device
        from extra_collector import ExtraCollector
        for task,slot in [('ranking','claim'),('excavation','claim'),('worldboss','cerberus'),('worldboss','kraken'),('worldboss','void')]:
            with self.subTest(task=task,slot=slot):
                d=Device(task);d.state={'ranking':'ranking','excavation':'excavation','worldboss':'boss_rank'}[task]
                v=Mock();v.recognize.side_effect=lambda _:d.screen()
                c=ExtraCollector(d,v,d.stop,lambda _:None);c.now=lambda:d.clock
                c.pause=lambda n:setattr(d,'clock',d.clock+n);c.boss_slot=slot
                c.action_state.reserve(task,slot);c.arm_regular_free_resume()
                self.assertEqual(c.claim_extra(task,c.screen()),'collected')
                self.assertEqual(d.claims,1);self.assertFalse(c.action_state.pending(task,slot))

    def test_autumn_current_pending_retries_once_and_cannot_rearm(self):
        from validate_autumn import RouteTests
        for stuck in (False,True):
            with self.subTest(stuck=stuck):
                d,c=RouteTests().collector(stuck=stuck)
                c.action_state.reserve('autumn');c.arm_regular_free_resume()
                c.cycle(['autumn']);self.assertEqual(d.claims,1)
                if stuck:
                    c.arm_regular_free_resume();c.cycle(['autumn'])
                    self.assertEqual(d.claims,1)
                    self.assertTrue(c.action_state.pending('autumn'))
                else:self.assertFalse(c.action_state.pending('autumn'))

    def test_request_changed_after_snapshot_cannot_authorize_retry(self):
        c,d=self.facility();c.action_state.reserve('mine');c.arm_regular_free_resume()
        c.action_state.reserve('mine',repeat_authorized=True)
        c.collect_room('mine',c.screen());self.assertEqual(d.claims['mine'],0)


    def test_request_changes_immediately_before_input_prevent_dispatch(self):
        from collector import ScreenChanged
        c,d=self.facility();c.action_state.reserve('mine');c.arm_regular_free_resume()
        self.assertTrue(c.can_retry_regular_free('mine'))
        original=c.tap
        def race(screen,name,**kwargs):
            reserve=kwargs['before_input']
            def changed():
                c.action_state.reserve('mine',repeat_authorized=True)
                reserve()
            kwargs['before_input']=changed
            return original(screen,name,**kwargs)
        c.tap=race
        with self.assertRaises(ScreenChanged):
            c.free_claim_tap(c.screen(),'ready_mine','mine',repeat_source='fresh_run_free_claim_retry')
        self.assertEqual(d.claims['mine'],0)
        self.assertFalse(c.can_retry_regular_free('mine'))

if __name__=='__main__':unittest.main()
