"""Interruption, stale input and adversarial recognition regression gates."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch
import cv2
import numpy as np
from action_state import ActionState,account_scope
from collector import Collector,Halt
from daily_state import DailyLedger,LedgerError
from extra_collector import ExtraCollector
from run_control import RunControl,ResumeRecognition
from vision import Vision,Screen,Match
import validate_autumn
from validate_overlays import composite
from diagnostics import save_collection_failure,export_diagnostics
from recognition_common import TransitionWatch


class SafetyTests(unittest.TestCase):
    def test_fresh_popup_prevents_common_button_click(self):
        c=Collector(Mock(),Mock(),threading.Event(),Mock())
        old=Screen('ranking',{'x_rank_active':Match('x_rank_active',1,0,(843,114))})
        c.last_screen=old;c.screen=Mock(return_value=Screen('reward',{}))
        with self.assertRaises(Halt):c.click_match('ranking','x_rank_active',old)
        c.device.click.assert_not_called()
    def test_conflicting_button_states_never_click(self):
        c=Collector(Mock(),Mock(),threading.Event(),Mock())
        s=Screen('farm_wait',{k:Match(k,1,0,(774,500)) for k in ('ready_farm','empty_farm')})
        c.screen=Mock(return_value=s)
        with self.assertRaises(Halt):c.tap(s,'ready_farm')
        c.device.click.assert_not_called()
    def test_corrupt_pending_record_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'action.json';path.write_text(json.dumps({'vm':{'autumn':{'pending':[]}}}))
            with self.assertRaises(LedgerError):ActionState(path,'vm')
    def test_missing_button_does_not_reserve_input(self):
        c=Collector(Mock(),Mock(),threading.Event(),Mock());reserve=Mock()
        old=Screen('ranking',{'x_rank_active':Match('x_rank_active',1,0,(843,114))})
        c.screen=Mock(return_value=Screen('ranking',{}))
        with self.assertRaises(Halt):c.tap(old,'x_rank_active',before_input=reserve)
        reserve.assert_not_called();c.device.click.assert_not_called()
    def test_storage_failure_never_dispatches(self):
        c=Collector(Mock(),Mock(),threading.Event(),Mock());s=Screen('menu',{})
        c.screen=Mock(return_value=s)
        with self.assertRaises(LedgerError):c.tap(s,point=(500,500),before_input=Mock(side_effect=LedgerError('disk')))
        c.device.click.assert_not_called()
    def test_pause_during_reservation_invalidates_touch(self):
        c=Collector(Mock(),Mock(),RunControl(),Mock());s=Screen('menu',{})
        c.screen=Mock(return_value=s)
        def reserve():c.stop.pause();c.stop.resume()
        with self.assertRaises(ResumeRecognition):c.tap(s,point=(500,500),before_input=reserve)
        c.device.click.assert_not_called()
    def test_failed_acknowledgement_keeps_pending_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'action.json';c=Collector(Mock(),Mock(),threading.Event(),Mock());state=ActionState(path,'vm')
            s=Screen('autumn',{});c.screen=Mock(return_value=s);c.device.click.side_effect=Halt('lost reply')
            with self.assertRaises(Halt):c.tap(s,point=(889,494),before_input=lambda:state.reserve('autumn'))
            self.assertTrue(ActionState(path,'vm').pending('autumn'))
    def test_restart_pending_autumn_active_never_claims_again(self):
        d,c=validate_autumn.RouteTests().collector();c.action_state.reserve('autumn')
        self.assertEqual(c.cycle(['autumn']),{'autumn':'deferred'});self.assertEqual(d.claims,0)
        self.assertEqual(d.state,'menu')
    def test_restart_pending_autumn_empty_confirms_without_click(self):
        d,c=validate_autumn.RouteTests().collector(empty=True);c.action_state.reserve('autumn')
        self.assertEqual(c.cycle(['autumn']),{'autumn':'collected'});self.assertEqual(d.claims,0)
        self.assertFalse(c.action_state.pending('autumn'))
    def test_autumn_stop_after_dispatch_preserves_attempt(self):
        d,c=validate_autumn.RouteTests().collector();original=d.click
        def click(p):
            original(p)
            if d.claims:d.stop.set()
        d.click=click
        with self.assertRaises(Halt):c.cycle(['autumn'])
        self.assertEqual(d.claims,1);self.assertTrue(c.action_state.pending('autumn'))
        d.stop.clear();d.click=original;d.back=lambda:setattr(d,'state','main')
        self.assertEqual(c.cycle(['autumn']),{'autumn':'collected'})
        self.assertEqual(d.claims,1)
    def test_autumn_repeated_failure_blocks_only_that_task(self):
        d,c=validate_autumn.RouteTests().collector();c.collect_autumn=Mock(side_effect=Halt('same missing button'))
        self.assertEqual(c.cycle(['autumn']),{'autumn':'failed'})
        self.assertEqual(c.cycle(['autumn']),{'autumn':'deferred'})
        before=len(d.actions);self.assertEqual(c.cycle(['autumn']),{'autumn':'deferred'})
        self.assertEqual(len(d.actions),before);self.assertEqual(c.collect_autumn.call_count,2)
        self.assertFalse(c.action_state.blocked('ranking'))
    def test_manual_retry_resets_failure_but_never_pending(self):
        state=ActionState();state.reserve('autumn')
        state.fail('autumn','inspect','autumn','missing');state.fail('autumn','inspect','autumn','missing')
        self.assertTrue(state.blocked('autumn'));state.reset('autumn')
        self.assertFalse(state.blocked('autumn'));self.assertTrue(state.pending('autumn'))
    def test_different_failure_does_not_count_as_same(self):
        state=ActionState();state.fail('autumn','inspect','autumn','missing')
        self.assertFalse(state.fail('autumn','entry','event_menu','missing tab'))
    def test_new_version_unblocks_detection_but_retains_pending(self):
        state=ActionState();state.reserve('autumn');state.update('autumn',version='old',blocked=True)
        self.assertFalse(state.blocked('autumn'));self.assertTrue(state.pending('autumn'))
    def test_corrupt_action_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'action.json';path.write_text('{broken')
            with self.assertRaises(LedgerError):ActionState(path)
    def test_accounts_preserve_legacy_and_separate_daily_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=DailyLedger(Path(tmp)/'daily.json');ident='a'*24
            self.assertEqual(account_scope(ident,''),ident)
            ledger.mark(ident,'daily_pass');other=account_scope(ident,'부캐')
            self.assertTrue(ledger.done(account_scope(ident,''),'daily_pass'))
            self.assertFalse(ledger.done(other,'daily_pass'))
            ledger.mark(other,'daily_pass');self.assertTrue(ledger.done(other,'daily_pass'))
            self.assertEqual(account_scope(ident,' 부캐 '),other)
            self.assertNotEqual(other,account_scope('b'*24,'부캐'))
    def test_bulk_settings_never_copy_account_identity(self):
        from profile_edits import copy_settings
        draft={'a':{'minutes':60,'daily_profile':'본캐'},'b':{'minutes':120,'daily_profile':'부캐'}}
        copy_settings(draft,'a',['b'],['minutes','daily_profile'])
        self.assertEqual(draft['b'],{'minutes':60,'daily_profile':'부캐'})
    def test_extra_task_failure_has_bounded_sequence_archive(self):
        import zipfile
        with tempfile.TemporaryDirectory() as tmp:
            c=Collector(Mock(),Mock(),threading.Event(),Mock());c.trace.task='autumn'
            im=np.full((540,960,3),90,np.uint8);s=Screen('autumn',{})
            for _ in range(12):c.trace.frame(im,s)
            save_collection_failure(tmp,'a'*24,im,s,'missing','autumn',trace=c.trace)
            files=list(Path(tmp).glob('*_evidence.zip'));self.assertEqual(len(files),1)
            with zipfile.ZipFile(files[0]) as z:self.assertEqual(len([n for n in z.namelist() if n.endswith('.jpg')]),6)
    def test_stable_unknown_target_stops_early(self):
        w=TransitionWatch(0,25);im=np.zeros((540,960,3),np.uint8)
        for t in range(10):w.observe(im,t,(760,462,943,524))
        self.assertTrue(w.expired(9));self.assertFalse(w.expired(7))
    def test_changing_target_has_hard_deadline(self):
        w=TransitionWatch(0,25)
        for t in range(25):w.observe(np.full((540,960,3),t*5,np.uint8),t)
        self.assertFalse(w.expired(24));self.assertTrue(w.expired(25))


class IconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.v=Vision()
    def test_pass_cannot_enter_from_adjacent_event_alone(self):
        s=self.v.recognize(composite(self.v,'main_menu','main_character','main_pet','top_event'))
        c=Collector(Mock(),Mock(),threading.Event(),Mock());clock=[0.]
        c.now=lambda:clock[0];c.pause=lambda t:clock.__setitem__(0,clock[0]+t)
        c.screen=Mock(return_value=s)
        with self.assertRaises(Halt):c.top_bar_tap(s,'pass')
        c.device.click.assert_not_called()
    def test_disappearing_pass_blocks_fresh_click(self):
        old=self.v.recognize(composite(self.v,'main_menu','main_character','main_pet','top_pass'))
        fresh=self.v.recognize(composite(self.v,'main_menu','main_character','main_pet','top_event'))
        c=Collector(Mock(),Mock(),threading.Event(),Mock());c.screen=Mock(return_value=fresh)
        with self.assertRaises(Halt):c.top_bar_tap(old,'pass')
        c.device.click.assert_not_called()
    def test_pass_uses_recognized_position_without_neighbor(self):
        im=composite(self.v,'main_menu','main_character','main_pet')
        ref,(x,y,r,b)=self.v.top_bar.references['pass'];im[y:b,x+3:r+3]=ref
        s=self.v.recognize(im);self.assertIn('top_pass',s.matches);self.assertNotIn('top_event',s.matches)
        c=Collector(Mock(),Mock(),threading.Event(),Mock());c.screen=Mock(return_value=s);c.pause=Mock()
        c.top_bar_tap(s,'pass')
        c.device.click.assert_called_once_with((602.,28.))
    def test_each_icon_and_rendering_variants(self):
        v=self.v
        for key in ('pass','event','worldboss'):
            base=composite(v,'main_menu','main_character','main_pet','top_'+key)
            for gain,offset in ((1,0),(1.12,5),(.9,0)):
                for width in (960,1280,1920):
                    im=np.clip(base.astype(float)*gain+offset,0,255).astype(np.uint8)
                    s=v.recognize(cv2.resize(im,(width,width*9//16)))
                    self.assertIn('top_'+key,s.matches,(key,gain,width))
    def test_swapped_icons_are_rejected(self):
        v=self.v
        for key in ('pass','event','worldboss'):
            for other in ('pass','event','worldboss'):
                if key==other:continue
                im=composite(v,'main_menu','main_character','main_pet')
                _,(x,y,r,b)=v.top_bar.references[key];im[y:b,x:r]=cv2.resize(v.top_bar.references[other][0],(r-x,b-y))
                self.assertNotIn('top_'+key,v.recognize(im).matches,(key,other))
    def test_overlay_and_removed_icons_cannot_authorize_entry(self):
        v=self.v
        for key in ('pass','event','worldboss'):
            self.assertNotIn('top_'+key,v.recognize(composite(v,'main_menu','main_character','main_pet')).matches)
            s=v.recognize(composite(v,'main_menu','main_character','main_pet','top_'+key,'exit_title','exit_cancel','exit_confirm'))
            self.assertEqual(s.state,'exit_dialog');self.assertNotIn('top_'+key,s.matches)


if __name__=='__main__':unittest.main()
