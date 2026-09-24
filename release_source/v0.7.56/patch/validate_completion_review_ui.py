"""Dungeon completion review stays accessible and runs only the chosen account."""
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock,patch
from action_state import ActionState,account_scope
from daily_state import ManualQuestLedger,korea_day
from history import History
import validate_history_lifecycle
import validate_fleet


class CompletionReviewUITests(unittest.TestCase):
    setUp=validate_history_lifecycle.HistoryLifecycleTests.setUp
    tearDown=validate_history_lifecycle.HistoryLifecycleTests.tearDown

    def review_button(self):
        return next(w for w in reversed(self.widgets) if '던전 완료 재확인' in w.args)

    def test_completed_dungeons_have_accessible_review_action(self):
        a=self.a;a.history.record('vm','daily_dungeons','already_complete');a.launch=Mock()
        a.history_dialog('vm',task_filter='daily_dungeons');win=a.history_window
        self.assertEqual(a.history_retry_button.kw['state'],'disabled')
        button=self.review_button();self.assertEqual(button.kw['state'],'normal');button.args[2]()
        a.select_player.assert_called_once_with('vm')
        a.launch.assert_called_once_with('verify_daily',{'vm':['daily_dungeons']})
        self.assertFalse(win.winfo_exists())

    def test_failed_dungeons_also_have_review_action(self):
        a=self.a;a.history.record('vm','daily_dungeons','failed');a.history_dialog('vm')
        self.assertEqual(self.review_button().kw['state'],'normal')

    def test_busy_review_is_disabled_and_stale_callback_is_blocked(self):
        a=self.a;a.history.record('vm','daily_dungeons','already_complete');a.history_dialog('vm')
        callback=self.review_button().args[2];a.launch=Mock();a.busy=Mock(return_value=True)
        a.history_render();self.assertEqual(self.review_button().kw.get('state'),'disabled')
        callback();a.launch.assert_not_called();self.assertIn('실행',a.status.get())
        a.select_player.assert_not_called();self.assertTrue(a.history_window.winfo_exists())

    def test_update_gate_blocks_review(self):
        a=self.a;a.launch=Mock()
        for applying in (False,True):
            with self.subTest(applying=applying):
                a.update_pending.clear();a.update_applying=applying
                if not applying:a.update_pending.set()
                a.review_dungeon_completion('vm')
                a.launch.assert_not_called();self.assertIn('업데이트',a.status.get())
        a.select_player.assert_not_called()

    def test_removed_player_cannot_launch_review(self):
        a=self.a;a.launch=Mock();a.players.pop('vm');a.review_dungeon_completion('vm')
        a.select_player.assert_not_called();a.launch.assert_not_called()


class CompletionReviewFleetTests(unittest.TestCase):
    def app(self):return validate_fleet.ManualLaunchTests().app()

    def test_review_targets_one_disabled_player_ignoring_regular_selection(self):
        a=self.app();a.players['c']['minutes']='unused'
        with patch('fleet_collection.run_fleet') as run:
            a.launch('verify_daily',{'c':['daily_dungeons','farm']})
        jobs,repeat,*_=run.call_args.args
        self.assertFalse(repeat);self.assertEqual([j['id'] for j in jobs],['c'])
        self.assertEqual(jobs[0]['rooms'],['daily_dungeons'])
        self.assertEqual(a.players['c']['selected'],{'mine':True})

    def test_missing_review_target_never_starts_other_players(self):
        a=self.app()
        with patch('fleet_collection.run_fleet') as run,patch('fleet_collection.messagebox.showerror'):
            a.launch('verify_daily')
        run.assert_not_called()

    def test_review_launch_honors_update_gate(self):
        a=self.app();a.update_pending.set()
        with patch('fleet_collection.run_fleet') as run:a.launch('verify_daily',{'b':['daily_dungeons']})
        run.assert_not_called();a.capture_profile.assert_not_called()

    def test_collector_review_flag_preserves_completion_pending_and_action_state(self):
        a=self.app();a.log=Mock();a.players['b']['daily_profile']='hero'
        scope=account_scope('b','hero')
        with tempfile.TemporaryDirectory() as tmp,ExitStack() as stack:
            root=Path(tmp);a.history=History(root/'history.json');a.history.record('b','daily_dungeons','already_complete')
            ledger=ManualQuestLedger(root/'daily_manual.json')
            ledger.mark(scope,'daily_dungeons','equipment')
            ledger.checkpoint(scope,'daily_dungeons','treasure','uncertain',pending='sweep')
            ledger.mark('other','daily_dungeons','rune')
            state=ActionState(root/'action_state.json',scope);state.reserve('farm')
            state.fail('farm','fixture','menu','unknown');state.fail('farm','fixture','menu','unknown')
            ledger_before=(root/'daily_manual.json').read_bytes();state_before=(root/'action_state.json').read_bytes()
            stack.enter_context(patch('app.DATA',root))
            lookup=stack.enter_context(patch('fleet_collection.CatalogLookup'))
            lookup.return_value.read.return_value={'s':{'instance_id':'b','name':'VM'}}
            stack.enter_context(patch('fleet_collection.Adb'))
            device=stack.enter_context(patch('fleet_collection.AdbDevice'))
            stack.enter_context(patch('fleet_collection.Vision'));stack.enter_context(patch('fleet_collection.save_execution_trace'))
            begin=stack.enter_context(patch.object(ManualQuestLedger,'begin_run'))
            reset=stack.enter_context(patch.object(ActionState,'reset'))
            run=stack.enter_context(patch('fleet_collection.cycle_with_recovery',return_value={'daily_dungeons':'already_complete'}))
            a.launch('verify_daily',{'b':['daily_dungeons']})
            run.assert_called_once();begin.assert_not_called();reset.assert_not_called()
            c,rooms,*_=run.call_args.args
            self.assertEqual(rooms,['daily_dungeons']);self.assertTrue(c.daily_verification_only)
            self.assertFalse(hasattr(c,'dungeon_resume_requests'))
            self.assertEqual(c.daily_ident,scope);self.assertEqual(c.manual_retry_tasks,{'daily_dungeons'})
            self.assertFalse(getattr(c,'manual_retry_rooms',set()))
            self.assertTrue(c.daily_ledger.done(scope,'daily_dungeons','equipment'))
            self.assertEqual(c.daily_ledger.detail(scope,'daily_dungeons','treasure')['pending'],'sweep')
            self.assertTrue(c.action_state.pending('farm'));self.assertTrue(c.action_state.blocked('farm'))
            device.return_value.tap.assert_not_called()
            self.assertEqual((root/'daily_manual.json').read_bytes(),ledger_before)
            self.assertEqual((root/'action_state.json').read_bytes(),state_before)

    def test_new_daily_and_retry_runs_arm_only_inherited_dungeon_requests(self):
        for mode in ('daily','retry'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp,ExitStack() as stack:
                a=self.app();a.log=Mock()
                for ident,p in a.players.items():p['enabled']=ident=='b'
                root=Path(tmp);a.history=History(root/'history.json');a.history.record('b','daily_dungeons','deferred')
                ledger=ManualQuestLedger(root/'daily_manual.json')
                ledger.checkpoint('b','daily_dungeons','equipment','uncertain',pending='sweep_action')
                old=ledger.detail('b','daily_dungeons','equipment')['input_request']['id']
                stack.enter_context(patch('app.DATA',root))
                lookup=stack.enter_context(patch('fleet_collection.CatalogLookup'))
                lookup.return_value.read.return_value={'s':{'instance_id':'b','name':'VM'}}
                for name in ('Adb','AdbDevice','Vision','save_execution_trace'):stack.enter_context(patch('fleet_collection.'+name))
                run=stack.enter_context(patch('fleet_collection.cycle_with_recovery',return_value={}))
                a.launch(mode,{'b':['daily_dungeons']})
                run.assert_called_once();c=run.call_args.args[0]
                self.assertEqual(c.dungeon_resume_requests['equipment'][1]['id'],old)
                c.daily_task='daily_dungeons';c.daily_step='equipment';c.daily_day=korea_day()
                c.daily_retire_inherited_pending();c.daily_checkpoint('uncertain',pending='sweep_action')
                c.arm_dungeon_resume()
                self.assertFalse(c.daily_can_resume_pending())

if __name__=='__main__':unittest.main()
