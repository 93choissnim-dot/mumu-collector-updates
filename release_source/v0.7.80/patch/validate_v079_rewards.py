"""Reward animation races, durable confirmation and bounded old free retries."""
import tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from action_state import ActionState
from collector import Halt,ScreenChanged
from daily_state import LedgerError
from extra_collector import ExtraCollector
from vision import Screen,Match
from adb_device import InputNotSent
import validate_reward_recovery as prior

class RewardTests(unittest.TestCase):
    def flow(self,task='worldboss',crash=False):
        page='boss_rank' if task=='worldboss' else task
        prefix={'worldboss':'x_boss','ranking':'x_rank','excavation':'x_dig'}[task]
        def screen(state,key=None):return Screen(state,{key:Match(key,1,0,(400,400))} if key else {})
        class Device:
            clock=0.;claims=0;reward_reads=0;clicks=[]
            def capture(d):
                d.clock+=.1
                if not d.claims:return screen(page,prefix+'_active')
                d.reward_reads+=1
                if d.reward_reads==5:
                    if crash:raise Halt('crash after observed reward')
                    return screen('unknown')
                if d.reward_reads>=6:return screen(page,prefix+'_empty')
                return screen('reward','reward_close')
            def click(d,point):
                d.clicks.append(point)
                if point==(400,400):d.claims+=1
        d=Device();d.clicks=[]
        c=ExtraCollector(d,SimpleNamespace(recognize=lambda x:x),threading.Event(),lambda _:None)
        c.now=lambda:d.clock;c.pause=lambda n:setattr(d,'clock',d.clock+n)
        c.trace.task=task;c.boss_slot='void'
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        c.action_state=ActionState(Path(folder.name)/'actions.json','test-account')
        return c,d
    def test_automatic_reward_transition_finishes_without_second_claim(self):
        for task in ('worldboss','ranking','excavation'):
            with self.subTest(task=task):
                c,d=self.flow(task)
                self.assertEqual(c.claim_extra(task,c.screen()),'collected')
                self.assertEqual(d.claims,1)
                self.assertNotIn((640,520),d.clicks)
                e=c.action_state.get(task)
                self.assertFalse(e.get('pending'))
                self.assertEqual(e['input_resolution']['source'],'free_reward_confirmed')
    def test_reward_confirmation_survives_crash_before_close(self):
        c,d=self.flow(crash=True)
        with self.assertRaises(Halt):c.claim_extra('worldboss',c.screen())
        saved=ActionState(c.action_state.path,c.action_state.scope)
        self.assertFalse(saved.pending('worldboss','void'))
        self.assertEqual(saved.get('worldboss')['input_resolution']['source'],'free_reward_confirmed')
        self.assertEqual(d.claims,1)
    def test_failed_confirmation_save_keeps_pending_and_does_not_close(self):
        c,d=self.flow();original=c.action_state.confirm
        def fail(*a,**kw):raise LedgerError('disk full')
        c.action_state.confirm=fail
        with self.assertRaises(LedgerError):c.claim_extra('worldboss',c.screen())
        self.assertTrue(ActionState(c.action_state.path,c.action_state.scope).pending('worldboss','void'))
        self.assertNotIn((640,520),d.clicks)
    def test_unrelated_reward_does_not_resolve_existing_request(self):
        c,d=self.flow();c.action_state.reserve('worldboss','void');old=c.action_state.pending('worldboss','void')
        d.claims=1
        c.wait_page({'boss_rank'})
        self.assertEqual(c.action_state.pending('worldboss','void'),old)
    def test_local_input_rejection_retires_only_new_reservation(self):
        helper=prior.RewardRecoveryTests();d,c=helper.extra('ranking')
        d.click=lambda _:(_ for _ in ()).throw(InputNotSent('not sent'))
        with self.assertRaises(InputNotSent):c.claim_extra('ranking',d.screen())
        self.assertFalse(c.action_state.pending('ranking'))
        self.assertEqual(c.action_state.get('ranking')['input_resolution']['kind'],'not_sent')
    def test_transport_uncertainty_keeps_pending(self):
        helper=prior.RewardRecoveryTests();d,c=helper.extra('ranking')
        d.click=lambda _:(_ for _ in ()).throw(Halt('transport uncertain'))
        with self.assertRaises(Halt):c.claim_extra('ranking',d.screen())
        self.assertTrue(c.action_state.pending('ranking'))

    def test_proof_is_bound_to_account_task_slot_and_exact_request(self):
        for mismatch in ('scope','task','slot','request'):
            with self.subTest(mismatch=mismatch):
                c,d=self.flow();c.action_state.reserve('worldboss','void')
                req=c.action_state.pending('worldboss','void')
                identity=['test-account','worldboss','void',req['id']]
                identity[{'scope':0,'task':1,'slot':2,'request':3}[mismatch]]='other'
                c.free_reward_request=tuple(identity)
                c.before_overlay_dismiss(Screen('reward',{'reward_close':Match('reward_close',1,0,(640,520))}))
                self.assertEqual(c.action_state.pending('worldboss','void'),req)

    def test_changed_button_after_reservation_sends_nothing_and_retires_it(self):
        helper=prior.RewardRecoveryTests();d,c=helper.extra('ranking')
        reserve=c.action_state.reserve
        def change(*a,**kw):reserve(*a,**kw);d.empty=True
        c.action_state.reserve=change
        self.assertEqual(c.claim_extra('ranking',d.screen()),'skipped')
        self.assertEqual(d.claims,0)
        self.assertFalse(c.action_state.pending('ranking'))
        self.assertEqual(c.action_state.get('ranking')['input_resolution']['kind'],'not_sent')

    def test_persistent_reward_has_bounded_close_inputs_and_durable_receipt(self):
        c,d=self.flow();capture=d.capture
        def stay():
            if d.claims:d.clock+=.1;return Screen('reward',{'reward_close':Match('reward_close',1,0,(640,520))})
            return capture()
        d.capture=stay
        with self.assertRaises(Halt):c.claim_extra('worldboss',c.screen())
        self.assertEqual(d.claims,1)
        self.assertEqual(d.clicks.count((640,520)),3)
        self.assertFalse(c.action_state.pending('worldboss','void'))
        self.assertIsNone(c.free_reward_request)

    def test_newly_accumulated_reward_after_modal_does_not_trigger_another_claim(self):
        c,d=self.flow();capture=d.capture
        def accumulate():
            s=capture()
            if s.state=='boss_rank' and d.claims:return Screen('boss_rank',{'x_boss_active':Match('x_boss_active',1,0,(400,400))})
            return s
        d.capture=accumulate
        self.assertEqual(c.claim_extra('worldboss',c.screen()),'collected')
        self.assertEqual(d.claims,1)

    def test_reward_vanishes_before_first_close_guard_still_records_receipt(self):
        c,d=self.flow();capture=d.capture
        def early():
            s=capture()
            if d.claims and d.reward_reads>=4:
                return Screen('boss_rank',{'x_boss_active':Match('x_boss_active',1,0,(400,400))})
            return s
        d.capture=early
        self.assertEqual(c.claim_extra('worldboss',c.screen()),'collected')
        self.assertEqual(d.claims,1)
        self.assertNotIn((640,520),d.clicks)
        self.assertFalse(c.action_state.pending('worldboss','void'))
        self.assertEqual(c.action_state.get('worldboss')['input_resolution']['source'],'free_reward_confirmed')

class MigrationTests(unittest.TestCase):
    def pending(self,task='worldboss',lost=0,version='0.7.77',**changes):
        helper=prior.RewardRecoveryTests();d,c=helper.extra(task,lost=lost)
        slot='void' if task=='worldboss' else 'claim';c.boss_slot=slot
        c.action_state.reserve(task,slot);e=c.action_state.get(task)
        e['pending'][slot].update(dict(version=version,requested_at='2026-10-01T18:07:11+09:00')|changes)
        c.action_state.update(task,**e)
        return c,d,slot,e['pending'][slot]['id']
    def test_previous_affected_free_requests_recover_once_and_preserve_old_uncertainty(self):
        for task in ('worldboss','ranking','excavation'):
            for version in ('0.7.77','0.7.78'):
                c,d,slot,old=self.pending(task,version=version)
                self.assertEqual(c.claim_extra(task,d.screen()),'collected')
                self.assertEqual(d.claims,1)
                history=c.action_state.get(task)['input_history']
                entry=next(h for h in history if h['request']['id']==old)
                self.assertFalse(entry['resolution']['confirmed'])
    def test_failed_migration_does_not_rearm_on_next_run(self):
        c,d,slot,old=self.pending(lost=99)
        self.assertEqual(c.claim_extra('worldboss',d.screen()),'deferred')
        self.assertEqual(c.claim_extra('worldboss',d.screen()),'deferred')
        self.assertEqual(d.claims,1)
        self.assertNotEqual(c.action_state.pending('worldboss',slot)['id'],old)
    def test_invalid_unknown_wrong_action_future_and_current_requests_do_not_rearm(self):
        for changes in ({'version':'0.7.79'},{'version':'0.7.80'},{'action':'paid'},
                        {'requested_at':'bad'},{'requested_at':'2030-01-01T00:00:00+09:00'}):
            options=dict(changes);version=options.pop('version','0.7.77')
            c,d,slot,old=self.pending(version=version,**options)
            self.assertEqual(c.claim_extra('worldboss',d.screen()),'deferred')
            self.assertEqual(d.claims,0)
            self.assertEqual(c.action_state.pending('worldboss',slot)['id'],old)

if __name__=='__main__':unittest.main()
