"""Explicit free-claim recovery; synthetic devices never connect to a game."""
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from action_state import ActionState
from collector import Halt, ScreenChanged
from diagnostics import save_collection_failure
from extra_collector import ExtraCollector
from run_control import ResumeRecognition, RunControl
import validate_autumn
from validate_extra import Device
import validate_world_boss


class RewardRecoveryTests(unittest.TestCase):
    def extra(self, task, **options):
        d=Device(task,**options)
        d.state={'worldboss':'boss_rank'}.get(task,task)
        c=ExtraCollector(d,SimpleNamespace(recognize=lambda _:d.screen()),d.stop,lambda _:None)
        c.now=lambda:d.clock
        def pause(seconds):
            d.clock+=seconds
            if d.stop.is_set():raise Halt('stopped')
        c.pause=pause;c.trace.task=task
        return d,c

    def test_explicit_retry_rearms_each_free_extra_without_clearing_reservation(self):
        for task in ('ranking','excavation','worldboss'):
            with self.subTest(task=task):
                d,c=self.extra(task);c.manual_retry_tasks={task}
                slot='kraken' if task=='worldboss' else 'claim'
                if task=='worldboss':c.boss_slot=slot
                c.action_state.reserve(task,slot)
                click=d.click
                def checked(point):
                    self.assertTrue(c.action_state.pending(task,slot));click(point)
                d.click=checked
                self.assertEqual(c.claim_extra(task,d.screen()),'collected')
                self.assertEqual(d.claims,1);self.assertFalse(c.action_state.pending(task,slot))

    def test_autumn_explicit_retry_claims_old_active_once(self):
        d,c=validate_autumn.RouteTests().collector();c.action_state.reserve('autumn');c.manual_retry_tasks={'autumn'}
        self.assertEqual(c.cycle(['autumn']),{'autumn':'collected'})
        self.assertEqual(d.claims,1);self.assertFalse(c.action_state.pending('autumn'))

    def test_autumn_current_deferred_evidence_is_saved_before_departure(self):
        with tempfile.TemporaryDirectory() as folder:
            d,c=validate_autumn.RouteTests().collector();c.action_state.reserve('autumn')
            c.on_issue=lambda task,reason:save_collection_failure(folder,'a'*24,c.last_image,c.last_screen,reason,task,trace=c.trace)
            self.assertEqual(c.cycle(['autumn']),{'autumn':'deferred'})
            path=Path(folder)/('last_'+'a'*24+'_autumn_error.json')
            self.assertTrue(path.exists())
            report=json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(report['state'],'autumn');self.assertEqual(report['run_id'],c.trace.run_id)

    def test_retry_permission_is_consumed_on_first_claim_even_without_old_pending(self):
        for task in ('ranking','excavation'):
            with self.subTest(task=task):
                d,c=self.extra(task,lost=99);c.manual_retry_tasks={task}
                self.assertEqual(c.claim_extra(task,d.screen()),'deferred')
                self.assertEqual(c.claim_extra(task,d.screen()),'deferred')
                self.assertEqual(d.claims,1)

    def test_autumn_reconnect_does_not_rearm_consumed_permission(self):
        d,c=validate_autumn.RouteTests().collector(stuck=True);c.manual_retry_tasks={'autumn'}
        c.cycle(['autumn']);c.cycle(['autumn'])
        self.assertEqual(d.claims,1);self.assertTrue(c.action_state.pending('autumn'))

    def test_old_pending_stays_durable_after_stopped_manual_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            d,c=self.extra('ranking',stop_after=True);path=Path(folder)/'actions.json'
            c.action_state=ActionState(path,'vm');c.action_state.reserve('ranking');c.manual_retry_tasks={'ranking'}
            with self.assertRaises(Halt):c.claim_extra('ranking',d.screen())
            self.assertEqual(d.claims,1);self.assertTrue(ActionState(path,'vm').pending('ranking'))
            d.stop.clear();d.empty=False;d.stop_after=False
            self.assertEqual(c.claim_extra('ranking',d.screen()),'deferred');self.assertEqual(d.claims,1)

    def test_training_never_rearms_even_with_explicit_retry(self):
        for empty in (False,True):
            d,c=self.extra('training',empty=empty);c.manual_retry_tasks={'training'};c.action_state.reserve('training')
            issues=[];c.on_issue=lambda task,reason:issues.append((task,c.last_screen.state))
            self.assertEqual(c.claim_extra('training',d.screen()),'deferred')
            self.assertEqual(d.claims,0);self.assertTrue(c.action_state.pending('training'))
            self.assertEqual(issues,[('training','training')])

    def test_pause_during_reservation_cannot_reuse_manual_permission(self):
        d,c=self.extra('ranking');c.stop=RunControl();c.manual_retry_tasks={'ranking'}
        c.action_state.reserve('ranking');reserve=c.action_state.reserve
        def interrupted(task,slot='claim'):
            reserve(task,slot);c.stop.pause();c.stop.resume()
        c.action_state.reserve=interrupted
        with self.assertRaises(ResumeRecognition):c.claim_extra('ranking',d.screen())
        self.assertEqual(d.claims,0);self.assertTrue(c.action_state.pending('ranking'))
        c.action_state.reserve=reserve
        self.assertEqual(c.claim_extra('ranking',d.screen()),'deferred');self.assertEqual(d.claims,0)

    def test_empty_confirms_old_free_pending_without_input(self):
        for task in ('ranking','excavation'):
            d,c=self.extra(task,empty=True);c.manual_retry_tasks={task};c.action_state.reserve(task)
            self.assertEqual(c.claim_extra(task,d.screen()),'collected');self.assertEqual(d.claims,0)
            self.assertFalse(c.action_state.pending(task))

    def test_unknown_preserves_pending_and_sends_no_claim(self):
        d,c=self.extra('ranking');d.state='unknown';c.manual_retry_tasks={'ranking'};c.action_state.reserve('ranking')
        with self.assertRaises(Halt):c.claim_extra('ranking',d.screen())
        self.assertEqual(d.claims,0);self.assertTrue(c.action_state.pending('ranking'))

    def test_stale_active_retry_cannot_click_new_empty_screen(self):
        d,c=self.extra('ranking');c.manual_retry_tasks={'ranking'};c.action_state.reserve('ranking')
        tap=c.tap
        def changed(screen,name=None,point=None,**kwargs):
            d.empty=True
            return tap(screen,name,point,**kwargs)
        c.tap=changed
        with self.assertRaises(ScreenChanged):c.claim_extra('ranking',d.screen())
        self.assertEqual(d.claims,0);self.assertTrue(c.action_state.pending('ranking'))

    def test_worldboss_manual_permission_is_one_shot_for_each_slot(self):
        def prepare(d,c):
            c.manual_retry_tasks={'worldboss'}
            for slot in ('cerberus','kraken','void'):c.action_state.reserve('worldboss',slot)
        d,c,result=validate_world_boss.RouteTests().run_flow(['cerberus','kraken','void'],before_run=prepare,lost=99)
        self.assertEqual(result,{'worldboss':'deferred'})
        self.assertEqual(d.claims,{'cerberus':1,'kraken':1,'void':1})
        c.now=lambda:d.clock;d.state='boss_rank';d.current='kraken';c.boss_slot='kraken'
        self.assertEqual(c.claim_extra('worldboss',d.screen(),record=False),'deferred')
        self.assertEqual(d.claims['kraken'],1)


if __name__=='__main__':unittest.main()
