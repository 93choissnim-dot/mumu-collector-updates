"""Failure/hold accounting and pre-launch pending-resolution regressions."""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock,patch
from action_state import ActionState,account_scope
from daily_state import ManualQuestLedger
from history import History
import validate_history_lifecycle


class HistoryCountTests(unittest.TestCase):
    def test_holds_do_not_create_failures_across_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'history.json';h=History(path)
            h.record('vm','training','failed')
            h.record('vm','training','deferred');h=History(path)
            h.record('vm','training','deferred')
            e=h.get('vm','training')
            self.assertEqual(e['consecutive_failures'],1)
            self.assertEqual(e['consecutive_holds'],2)
            self.assertEqual(h.stats('vm')['failed_tasks'],0)
            self.assertEqual(h.stats('vm')['held_tasks'],1)
            self.assertEqual(h.stats('vm')['issue_tasks'],1)
            h.record('vm','training','failed')
            self.assertEqual(h.get('vm','training')['consecutive_failures'],2)
            self.assertEqual(h.get('vm','training')['consecutive_holds'],0)
            h.record('vm','training','already_complete')
            self.assertEqual(h.get('vm','training')['consecutive_failures'],0)
            self.assertEqual(h.get('vm','training')['consecutive_holds'],0)

    def test_legacy_mixed_count_is_preserved_without_inventing_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'history.json'
            path.write_text(json.dumps({'vm':{'training':{'result':'deferred','consecutive_failures':17}}}))
            h=History(path);h.record('vm','training','deferred')
            e=History(path).get('vm','training')
            self.assertEqual(e['legacy_consecutive_issues'],17)
            self.assertEqual(e['consecutive_failures'],0)
            self.assertEqual(e['consecutive_holds'],1)
            h.record('vm','training','failed')
            self.assertEqual(h.get('vm','training')['legacy_consecutive_issues'],17)
            self.assertEqual(h.get('vm','training')['consecutive_failures'],1)


class PendingHistoryTests(unittest.TestCase):
    setUp=validate_history_lifecycle.HistoryLifecycleTests.setUp
    tearDown=validate_history_lifecycle.HistoryLifecycleTests.tearDown
    def pending_donation(self,scope='vm'):
        ledger=ManualQuestLedger(Path(self.tmp.name)/'daily_manual.json')
        ledger.checkpoint(scope,'daily_guild','donation','uncertain',pending='donation_paid')
        self.a.history.record('vm','daily_guild','deferred')

    def test_pending_donation_retry_opens_resolution_without_game_launch(self):
        self.pending_donation();a=self.a;a.launch=Mock();a.history_dialog('vm')
        win=a.history_window
        with patch('retry_resolution.show_resolution') as resolve:
            a.retry_failed('vm',['daily_guild'])
        resolve.assert_called_once_with(a,'vm','daily_guild')
        a.launch.assert_not_called();a.select_player.assert_not_called()
        self.assertTrue(win.winfo_exists())

    def test_retry_all_resolves_pending_before_launching_any_task(self):
        self.pending_donation();a=self.a;a.launch=Mock()
        with patch('retry_resolution.show_resolution') as resolve:a.retry_failed('vm')
        resolve.assert_called_once_with(a,'vm','daily_guild');a.launch.assert_not_called()

    def test_repeatable_training_pending_does_not_block_retry(self):
        a=self.a;a.players['vm']['daily_profile']='hero';a.players['vm']['selected']['training']=True
        state=ActionState(Path(self.tmp.name)/'action_state.json',account_scope('vm','hero'));state.reserve('training')
        a.history.record('vm','training','deferred');a.launch=Mock()
        with patch('retry_resolution.show_resolution') as resolve:a.retry_failed('vm',['training'])
        resolve.assert_not_called();a.launch.assert_called_once_with('retry',{'vm':['training']})
        self.assertIsNotNone(ActionState(state.path,state.scope).pending('training'))

    def test_another_account_pending_does_not_block_retry(self):
        self.pending_donation(account_scope('vm','other'));a=self.a;a.launch=Mock()
        with patch('retry_resolution.show_resolution') as resolve:a.retry_failed('vm',['daily_guild'])
        resolve.assert_not_called();a.launch.assert_called_once_with('retry',{'vm':['daily_guild']})

    def test_repeatable_raid_pending_does_not_route_to_resolution(self):
        a=self.a;a.history.record('vm','daily_guild','deferred');a.launch=Mock()
        with patch('retry_resolution.pending_choices',return_value=[{'step':'raid'}]),patch('retry_resolution.show_resolution') as resolve:
            a.retry_failed('vm',['daily_guild'])
        resolve.assert_not_called();a.launch.assert_called_once_with('retry',{'vm':['daily_guild']})

    def test_free_daily_pass_pending_can_reconcile_without_forced_resolution(self):
        a=self.a;a.history.record('vm','daily_pass','deferred');a.launch=Mock()
        ledger=ManualQuestLedger(Path(self.tmp.name)/'daily_manual.json')
        ledger.checkpoint('vm','daily_pass','ad','uncertain',pending='pass_claim')
        with patch('retry_resolution.show_resolution') as resolve:a.retry_failed('vm',['daily_pass'])
        resolve.assert_not_called();a.launch.assert_called_once_with('retry',{'vm':['daily_pass']})

    def test_free_guild_pending_can_reconcile_without_forced_resolution(self):
        a=self.a;a.history.record('vm','daily_guild','deferred');a.launch=Mock()
        ledger=ManualQuestLedger(Path(self.tmp.name)/'daily_manual.json')
        for step in ('attendance','relic','shop'):
            ledger.checkpoint('vm','daily_guild',step,'uncertain',pending='free_claim')
        with patch('retry_resolution.show_resolution') as resolve:a.retry_failed('vm',['daily_guild'])
        resolve.assert_not_called();a.launch.assert_called_once_with('retry',{'vm':['daily_guild']})

    def test_ticket_consuming_dungeon_pending_requires_resolution(self):
        a=self.a;a.launch=Mock();ledger=ManualQuestLedger(Path(self.tmp.name)/'daily_manual.json')
        for task,step in [('daily_guild','dungeon'),('daily_dungeons','equipment')]:
            with self.subTest(task=task):
                a.history.record('vm',task,'deferred')
                ledger.checkpoint('vm',task,step,'uncertain',pending='dungeon_start')
                with patch('retry_resolution.show_resolution') as resolve:a.retry_failed('vm',[task])
                resolve.assert_called_once_with(a,'vm',task);a.launch.assert_not_called()

    def test_free_claim_retry_does_not_inspect_resource_pending(self):
        a=self.a;a.launch=Mock()
        with patch('retry_resolution.pending_choices') as choices,patch('retry_resolution.show_resolution') as resolve:
            a.retry_failed('vm',['farm'])
        choices.assert_not_called();resolve.assert_not_called()
        a.launch.assert_called_once_with('retry',{'vm':['farm']})

    def test_unreadable_pending_records_block_launch_with_reason(self):
        a=self.a;a.history.record('vm','daily_guild','failed');a.launch=Mock()
        (Path(self.tmp.name)/'daily_manual.json').write_text('{broken')
        a.retry_failed('vm',['daily_guild'])
        a.launch.assert_not_called();self.assertIn('기록',a.status.get())

    def test_update_gate_precedes_pending_inspection(self):
        self.pending_donation();a=self.a;a.launch=Mock();a.update_pending.set()
        with patch('retry_resolution.pending_choices') as choices,patch('retry_resolution.show_resolution') as resolve:
            a.retry_failed('vm',['daily_guild'])
        choices.assert_not_called();resolve.assert_not_called();a.launch.assert_not_called()
        self.assertIn('업데이트',a.status.get())

    def test_history_labels_distinguish_holds_and_legacy_mixed_counts(self):
        a=self.a
        a.history.data['vm']['training']={'result':'deferred','consecutive_failures':17}
        a.history.record('vm','daily_guild','deferred')
        a.history_dialog('vm')
        texts='\n'.join(str(w.args[1]) for w in self.widgets if len(w.args)>1)
        self.assertIn('이전 실패/보류 혼합 기록 17회',texts)
        self.assertNotIn('연속 실패 17회',texts)
        self.assertIn('연속 보류 1회',texts)
        summary='\n'.join(str(w.kw.get('text','')) for w in self.widgets)
        self.assertIn('실패 1건',summary);self.assertIn('보류 2건',summary)

    def test_pending_origin_shows_request_metadata_and_unknown_legacy_origin(self):
        ledger=ManualQuestLedger(Path(self.tmp.name)/'daily_manual.json')
        with patch('daily_state.korea_now',return_value=datetime.fromisoformat('2026-09-22T12:34:56+09:00')),patch('daily_state.VERSION','0.7.49'):
            ledger.checkpoint('vm','daily_guild','donation','uncertain',pending='donation_paid')
        # Seed an older pending entry whose original request was never recorded.
        ledger.update('vm','daily_guild',{'_steps':{
            'donation':ledger.detail('vm','daily_guild','donation'),
            'dungeon':{'status':'uncertain','pending':'guild_start'}}})
        self.a.history.record('vm','daily_guild','deferred');self.a.history_dialog('vm')
        texts='\n'.join(str(w.args[1]) for w in self.widgets if len(w.args)>1)
        self.assertIn('기부 / 최초 입력 요청 09/22 12:34 / 기록 버전 0.7.49',texts)
        self.assertIn('길드 던전 / 최초 입력 요청 기록 없음 / 기록 버전 기록 없음',texts)

if __name__=='__main__':unittest.main()
