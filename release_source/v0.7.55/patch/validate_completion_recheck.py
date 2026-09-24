"""Completion review is read-only; ordinary retries use current game state."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from daily_state import ManualQuestLedger,LedgerError
from daily_execution import OutcomeUnknown
from extra_collector import ExtraCollector
from vision import Screen


class CompletionRecheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        c=self.c=ExtraCollector(Mock(),Mock(),threading.Event(),Mock())
        c.daily_ledger=ManualQuestLedger(Path(self.tmp.name)/'manual.json')
        c.daily_ident='vm';c.daily_task='daily_dungeons';c.daily_step='rune';c.daily_day='manual'
        c.manual_retry_tasks={'daily_dungeons'};c.daily_verification_only=True;c.daily_recover=Mock()
        c.last_screen=Screen('daily_room_rune',{})
        c.daily_ledger.mark('vm','daily_dungeons','rune')
        c.daily_ledger.mark('vm','daily_dungeons','_complete')
    def test_old_done_is_rechecked_without_running_resource_action(self):
        c=self.c;action=Mock()
        def verify(step,*,verification_only):
            self.assertTrue(verification_only);self.assertFalse(c.daily_done(step))
            c.daily_checkpoint('done',values={step:'done'},completion_evidence={'revision':1,'kind':'no_entries','observations':2,'page':'daily_room_rune'})
        c.daily_dungeon=Mock(side_effect=verify)
        c.daily_run_step('rune','룬 동굴',action)
        action.assert_not_called();c.daily_dungeon.assert_called_once_with('rune',verification_only=True)
        self.assertTrue(c.daily_done('rune'));self.assertIn('previous_completion',c.daily_detail())
    def test_failed_recheck_cannot_leave_done_or_task_complete(self):
        c=self.c;c.daily_dungeon=Mock(side_effect=OutcomeUnknown('남은 횟수 있음'))
        c.daily_ledger.mark('vm','daily_dungeons','relic')
        c.daily_ledger.mark('other','daily_dungeons','rune')
        action=Mock();c.daily_run_step('rune','룬 동굴',action)
        self.assertFalse(c.daily_done('rune'));self.assertFalse(c.daily_done('_complete'))
        self.assertEqual(c.daily_detail()['status'],'uncertain')
        self.assertTrue(c.daily_done('relic'));self.assertTrue(c.daily_ledger.done('other','daily_dungeons','rune'))
        action.assert_not_called();c.device.click.assert_not_called()
        # A later explicit retry follows normal resource guards, not this audit.
        fresh=ExtraCollector(Mock(),Mock(),threading.Event(),Mock())
        for name in ('daily_ledger','daily_ident','daily_task','daily_day','daily_recover'):
            setattr(fresh,name,getattr(c,name))
        fresh.daily_run_step('rune','룬 동굴',lambda:fresh.daily_mark('rune'))
        self.assertTrue(fresh.daily_done('rune'))
    def test_verified_completion_is_preserved_without_requested_review(self):
        c=self.c;c.daily_verification_only=False;c.manual_retry_tasks=set();c.daily_checkpoint('done',completion_evidence={'revision':1,'kind':'no_entries','observations':2,'page':'daily_room_rune'})
        c.daily_dungeon=Mock();action=Mock();c.daily_run_step('rune','룬 동굴',action)
        action.assert_not_called();c.daily_dungeon.assert_not_called();self.assertTrue(c.daily_done('rune'))
    def test_failed_migration_write_never_navigates_or_changes_completion(self):
        c=self.c;c.daily_dungeon=Mock();action=Mock()
        with patch.object(Path,'replace',side_effect=OSError('full')),self.assertRaises(LedgerError):
            c.daily_run_step('rune','룬 동굴',action)
        self.assertTrue(c.daily_done('rune'));action.assert_not_called();c.daily_dungeon.assert_not_called()
    def test_terminal_evidence_callback_fires_without_pending_input(self):
        c=self.c;events=[];c.daily_ledger.on_input_evidence=lambda *args:events.append(args)
        proof={'revision':1,'kind':'no_entries','observations':2,'page':'daily_room_rune'}
        c.daily_checkpoint('done',values={'rune':'done'},completion_evidence=proof)
        self.assertEqual(len(events),1);self.assertEqual(events[0][0],'completed')
        self.assertEqual(events[0][3]['completion_evidence'],proof)
        c.daily_checkpoint('done',label='later observation')
        self.assertEqual(len(events),1)
    def test_full_task_completion_cannot_bypass_legacy_review(self):
        from daily_state import DAILY_STEPS
        c=self.c;c.daily_open=Mock();c.daily_main=Mock()
        for step in DAILY_STEPS['daily_dungeons']:c.daily_ledger.mark('vm','daily_dungeons',step)
        def inspect(step,*,verification_only=False):
            self.assertTrue(verification_only)
            c.daily_checkpoint('done',values={step:'done'},completion_evidence={
                'revision':1,'kind':'no_entries','observations':2,'page':'daily_room_'+step})
        c.daily_dungeon=Mock(side_effect=inspect)
        self.assertEqual(c.collect_daily('daily_dungeons'),'no_entries')
        self.assertEqual(c.daily_dungeon.call_count,7);c.daily_open.assert_called_once()
        c.daily_dungeon.reset_mock();c.daily_open.reset_mock()
        c.daily_verification_only=False;c.manual_retry_tasks=set()
        self.assertEqual(c.collect_daily('daily_dungeons'),'no_entries')
        c.daily_dungeon.assert_not_called();c.daily_open.assert_not_called()
    def test_no_entry_frame_is_preserved_and_exportable(self):
        import json,zipfile
        import numpy as np
        from diagnostics import save_input_evidence,export_diagnostics
        c=self.c;root=Path(self.tmp.name);ident='a'*24;paths=[]
        def evidence(phase,task,step,detail):
            paths.append(save_input_evidence(root,ident,ident,task,step,phase,detail,
                np.zeros((540,960,3),np.uint8),c.last_screen))
        c.daily_ledger.on_input_evidence=evidence
        c.daily_checkpoint('done',values={'rune':'done'},completion_evidence={
            'revision':1,'kind':'no_entries','observations':2,'page':'daily_room_rune'})
        self.assertEqual(len(paths),1)
        with zipfile.ZipFile(paths[0]) as z:
            meta=json.loads(z.read('evidence.json'))
            self.assertEqual(meta['phase'],'completed');self.assertEqual(meta['state'],'daily_room_rune')
            self.assertIn('screen.jpg',z.namelist())
        export_diagnostics(root,root/'export.zip')
        with zipfile.ZipFile(root/'export.zip') as z:self.assertIn(paths[0].name,z.namelist())
    def test_explicit_review_reopens_even_new_verified_completion(self):
        c=self.c;c.daily_verification_only=True;c.daily_checkpoint('done',completion_evidence={
            'revision':1,'kind':'no_entries','observations':2,'page':'daily_room_rune'})
        c.daily_dungeon=Mock(side_effect=OutcomeUnknown('남은 횟수 있음'))
        c.daily_run_step('rune','룬 동굴',Mock())
        c.daily_dungeon.assert_called_once_with('rune',verification_only=True)
        self.assertFalse(c.daily_done('rune'))
    def test_review_mode_does_not_spend_available_entries_or_free_keys(self):
        from validate_dungeon_confirmation import screen
        c=self.c;c.daily_verification_only=True;c.daily_close_room=Mock();c.daily_tap=Mock()
        c.daily_find_dungeon=Mock(return_value=screen('daily_room_rune'))
        c.daily_ready=Mock(return_value=screen('daily_room_rune','d_enter'))
        c.daily_committed_tap=Mock()
        with self.assertRaises(OutcomeUnknown):c.daily_dungeon('rune')
        c.daily_committed_tap.assert_not_called();c.device.click.assert_not_called()
    def test_interrupted_legacy_review_remains_readonly_on_resume(self):
        from run_control import ResumeRecognition
        c=self.c;c.daily_dungeon=Mock(side_effect=ResumeRecognition())
        action=Mock()
        with self.assertRaises(ResumeRecognition):c.daily_run_step('rune','룬 동굴',action)
        self.assertFalse(c.daily_done('rune'))
        c.daily_dungeon=Mock(side_effect=OutcomeUnknown('남은 횟수 있음'))
        c.daily_run_step('rune','룬 동굴',action)
        action.assert_not_called();c.daily_dungeon.assert_called_once_with('rune',verification_only=True)
    def test_explicit_review_cannot_trust_group_flag_without_step_records(self):
        from daily_state import DAILY_STEPS
        c=self.c;c.daily_verification_only=True;c.daily_open=Mock();c.daily_main=Mock()
        c.daily_ledger.update('vm','daily_dungeons',{'rune':None,'_steps':{}})
        def inspect(step,**kwargs):
            self.assertTrue(c.daily_verification_only)
            c.daily_checkpoint('done',values={step:'done'},completion_evidence={
                'revision':1,'kind':'no_entries','observations':2,'page':'daily_room_'+step})
        c.daily_dungeon=Mock(side_effect=inspect)
        self.assertEqual(c.collect_daily('daily_dungeons'),'no_entries')
        self.assertEqual(c.daily_dungeon.call_count,len(DAILY_STEPS['daily_dungeons']))
    def test_contradicted_group_only_completion_cannot_survive_review(self):
        c=self.c;c.daily_verification_only=True;c.daily_open=Mock();c.daily_main=Mock()
        c.daily_ledger.update('vm','daily_dungeons',{'rune':None,'_steps':{}})
        c.daily_dungeon=Mock(side_effect=OutcomeUnknown('남은 횟수 있음'))
        self.assertEqual(c.collect_daily('daily_dungeons'),'deferred')
        self.assertFalse(c.daily_done('_complete'))


if __name__=='__main__':unittest.main()
