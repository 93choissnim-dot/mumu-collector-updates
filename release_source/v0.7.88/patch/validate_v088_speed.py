"""Free-claim capture reuse and confirmed completion, with real input guards."""
from unittest.mock import patch
import unittest

from collector import Halt, ScreenChanged
from run_control import ResumeRecognition
from vision import Screen, Match
import validate_v070_input as guards
import validate_extra as extras


class FreePrecheckTests(unittest.TestCase):
    def flow(self, task='farm'):
        h=guards.FinalInputTests();h.setUp();self.addCleanup(h.doCleanups)
        c=h.collector;c.action_state=h.state;c.now=lambda:100.
        name='ready_farm' if task=='farm' else 'x_rank_active'
        h.page='farm_ready' if task=='farm' else 'ranking'
        h.matches={name:Match(name,1,0,(780,499))}
        c.forget_observations();c.screen();screen=c.screen()
        return h,c,screen,name

    def test_confirmed_free_claim_saves_one_capture(self):
        for task in ('farm','ranking'):
            with self.subTest(task=task):
                h,c,s,name=self.flow(task)
                with patch.object(c,'screen',wraps=c.screen) as capture:
                    c.free_claim_tap(s,name,task)
                self.assertEqual(capture.call_count,1)
                self.assertEqual(len(h.inputs),1)
                self.assertTrue(c.action_state.pending(task))

    def test_fresh_capture_follows_reservation_and_evidence(self):
        h,c,s,name=self.flow();order=[]
        reserve=c.action_state.reserve;capture=c.screen;frame=c.trace.frame
        def save(*a,**kw):reserve(*a,**kw);order.append('reserve')
        def evidence(*a,**kw):frame(*a,**kw);order.append('evidence')
        def read():order.append('capture');return capture()
        with patch.object(c.action_state,'reserve',save),patch.object(c.trace,'frame',evidence),patch.object(c,'screen',read):
            c.free_claim_tap(s,name,'farm')
        self.assertEqual(order,['reserve','evidence','capture'])

    def test_stale_single_wrong_generation_and_wrong_identity_fall_back(self):
        for condition in ('stale','single','generation','identity','conflict','done'):
            with self.subTest(condition=condition):
                h,c,s,name=self.flow('ranking')
                if condition=='stale':c.now=lambda:101.
                if condition=='single':c._observations=c._observations[-1:]
                if condition=='generation':c.stop.pause();c.stop.resume()
                if condition=='identity':s=Screen(s.state,dict(s.matches))
                if condition in ('conflict','done'):
                    old=c._observations[0][2]
                    old.matches['x_rank_'+('empty' if condition=='conflict' else 'done')]=Match('opposite',1,0,(780,499))
                with patch.object(c,'screen',wraps=c.screen) as capture:
                    c.free_claim_tap(s,name,'ranking')
                self.assertEqual(capture.call_count,2)

    def test_ordinary_and_nonwhitelisted_free_claims_keep_two_captures(self):
        for task in (None,'wood','mine','excavation','worldboss'):
            with self.subTest(task=task):
                h,c,s,name=self.flow()
                with patch.object(c,'screen',wraps=c.screen) as capture:
                    if task is None:c.tap(s,name)
                    else:c.free_claim_tap(s,name,task,'cerberus' if task=='worldboss' else 'claim')
                self.assertEqual(capture.call_count,2)

    def mutate_after_reserve(self, change, expected=Halt, task='farm'):
        h,c,s,name=self.flow(task);reserve=c.action_state.reserve
        def save(*a,**kw):reserve(*a,**kw);change(h,c,name)
        with patch.object(c.action_state,'reserve',save),self.assertRaises(expected):
            c.free_claim_tap(s,name,task)
        self.assertEqual(h.inputs,[])
        return c

    def test_page_changed_after_reserve_blocks_input(self):
        self.mutate_after_reserve(lambda h,c,n:setattr(h,'page','daily_shop_confirm'),ScreenChanged)

    def test_unknown_after_reserve_blocks_input(self):
        self.mutate_after_reserve(lambda h,c,n:setattr(h,'page','unknown'),ScreenChanged)

    def test_button_disappeared_after_reserve_blocks_input(self):
        self.mutate_after_reserve(lambda h,c,n:h.matches.pop(n),ScreenChanged)

    def test_conflicting_markers_after_reserve_block_input(self):
        for task,opposite in (('farm','empty_farm'),('ranking','x_rank_empty'),('ranking','x_rank_done')):
            with self.subTest(opposite=opposite):
                self.mutate_after_reserve(lambda h,c,n:h.matches.update({opposite:Match(opposite,1,0,(780,499))}),task=task)

    def test_account_change_after_reserve_blocks_input(self):
        self.mutate_after_reserve(lambda h,c,n:setattr(c.action_state,'scope','other'),ScreenChanged)

    def test_stop_after_reserve_blocks_input(self):
        c=self.mutate_after_reserve(lambda h,c,n:c.stop.set())
        self.assertTrue(c.action_state.pending('farm'))

    def test_pause_resume_after_reserve_blocks_input(self):
        c=self.mutate_after_reserve(lambda h,c,n:(c.stop.pause(),c.stop.resume()),ResumeRecognition)
        self.assertTrue(c.action_state.pending('farm'))

    def test_page_changed_during_evidence_blocks_input(self):
        h,c,s,name=self.flow()
        with patch.object(c.trace,'frame',lambda *a:setattr(h,'page','daily_shop_confirm')):
            with self.assertRaises(ScreenChanged):c.free_claim_tap(s,name,'farm')
        self.assertEqual(h.inputs,[])

    def test_new_button_position_after_reserve_is_used(self):
        h,c,s,name=self.flow();reserve=c.action_state.reserve
        def save(*a,**kw):reserve(*a,**kw);h.matches[name]=Match(name,1,0,(810,490))
        with patch.object(c.action_state,'reserve',save):c.free_claim_tap(s,name,'farm')
        self.assertEqual(h.inputs,[('farm_ready',(810,490))])

    def test_storage_failure_never_dispatches(self):
        h,c,s,name=self.flow()
        with patch.object(c.action_state,'reserve',side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):c.free_claim_tap(s,name,'farm')
        self.assertEqual(h.inputs,[])

    def test_transport_uncertainty_retains_pending_and_other_history(self):
        h,c,s,name=self.flow();c.action_state.reserve('mine');before=c.action_state.get('mine')
        with patch.object(c.device,'click',side_effect=Halt('lost acknowledgement')) as click:
            with self.assertRaises(Halt):c.free_claim_tap(s,name,'farm')
        self.assertEqual(click.call_count,1);self.assertTrue(c.action_state.pending('farm'))
        self.assertEqual(c.action_state.get('mine'),before)


class ConfirmedWaitTests(unittest.TestCase):
    def flow(self,task='ranking',settlement='confirmed'):
        d=extras.Device(task);d.state={'ranking':'ranking','worldboss':'boss_rank','excavation':'excavation'}[task]
        class Vision:
            def recognize(self,image):return d.screen()
        c=extras.ExtraCollector(d,Vision(),d.stop,lambda _:None);c.now=lambda:d.clock
        waits=[]
        def pause(n):waits.append(n);d.clock+=n
        c.pause=pause;c.trace.task=task
        if task=='worldboss':c.boss_slot='cerberus'
        post=c.post_input
        def observed(*a,**kw):
            post(*a,**kw)
            if settlement=='single':c._observations=c._observations[-1:]
            elif settlement=='stale':d.clock+=1
            elif settlement=='unknown':
                c.forget_observations();s=Screen('unknown',{});c.last_screen=s
                c.remember_observation(s,None);c.remember_observation(s,None)
            elif settlement=='conflict':
                prefix={'ranking':'x_rank','worldboss':'x_boss','excavation':'x_dig'}[task]
                for _,_,s in c._observations:s.matches[prefix+'_active']=Match(prefix+'_active',1,0,(400,400))
        c.post_input=observed
        if settlement=='active':d.lost=99
        result=c.claim_extra(task,c.screen())
        return c,d,waits,result

    def test_twice_confirmed_empty_skips_one_second_wait(self):
        for task in ('ranking','worldboss','excavation'):
            with self.subTest(task=task):
                c,d,waits,result=self.flow(task)
                self.assertEqual(result,'collected');self.assertEqual(d.claims,1)
                self.assertNotIn(1,waits)
                self.assertFalse(c.action_state.pending(task,'cerberus' if task=='worldboss' else 'claim'))

    def test_single_stale_unknown_conflicting_and_active_keep_wait(self):
        for state in ('single','stale','unknown','conflict','active'):
            with self.subTest(state=state):
                c,d,waits,result=self.flow(settlement=state)
                self.assertIn(1,waits);self.assertEqual(d.claims,1)
                self.assertEqual(result,'deferred' if state=='active' else 'collected')
                self.assertEqual(bool(c.action_state.pending('ranking')),state=='active')


if __name__=='__main__':unittest.main()
