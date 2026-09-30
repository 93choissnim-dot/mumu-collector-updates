"""Account-isolated history and fail-closed nested daily checkpoints."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from action_state import ActionState,account_scope
from daily_state import LedgerError,ManualQuestLedger
from execution_trace import ExecutionTrace
from history import History
from run_journal import RunJournal
from task_outcomes import RunOutcomes


class AccountHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.data=Path(self.temp.name);self.history=History(self.data/'history.json')
        self.player={'enabled':True,'name':'VM','daily_profile':'A','serial':'serial',
                     'selected':{'mine':True},'minutes':60}
        self.app=SimpleNamespace(history=self.history,players={'vm':self.player})
    def outcomes(self,profile):
        return RunOutcomes('vm',account_scope('vm',profile),self.history,None,lambda *args:None,lambda _:None)
    def test_named_accounts_keep_failures_successes_and_late_causes_separate(self):
        trace=ExecutionTrace();trace.task='mine';trace.step='claim'
        collector=SimpleNamespace(trace=trace,action_state=ActionState(),daily_ledger=None)
        a=self.outcomes('A');a.record('mine','failed',collector,reason='A failed')
        self.outcomes('B').record('mine','collected')
        a.issue('mine','A late cause',collector)
        a_entry=self.history.get(account_scope('vm','A'),'mine')
        self.assertEqual(a_entry.get('reason'),'A late cause')
        self.assertEqual(a_entry['consecutive_failures'],1)
        self.assertEqual(self.history.get(account_scope('vm','B'),'mine')['result'],'collected')
        self.assertEqual(self.history.get('vm','mine'),{})
    def test_history_ui_never_inherits_other_named_or_unknown_legacy_account(self):
        from ui_history import HistoryUI
        self.history.record('vm','mine','failed');self.history.record('serial','wood','failed')
        entries=HistoryUI.history_entries(self.app,'vm')
        self.assertEqual(entries['mine'],{});self.assertEqual(entries['wood'],{})
        self.outcomes('A').record('mine','failed',reason='A failed')
        self.assertEqual(HistoryUI.history_entries(self.app,'vm')['mine']['reason'],'A failed')
        self.player['daily_profile']='B'
        self.assertEqual(HistoryUI.history_entries(self.app,'vm')['mine'],{})
        self.player['daily_profile']=''
        self.assertEqual(HistoryUI.history_entries(self.app,'vm')['mine']['result'],'failed')
        self.assertEqual(HistoryUI.history_entries(self.app,'vm')['wood']['result'],'failed')
    def test_named_account_totals_and_serial_card_are_scoped(self):
        from fleet_ui import FleetUI
        self.history.record('vm','mine','collected');self.history.record('serial','wood','collected')
        self.outcomes('A').record('mine','failed')
        self.outcomes('B').record('mine','collected')
        self.assertEqual(self.history.player_stats('vm','A',alternate='serial')['today'],0)
        self.assertEqual(self.history.player_stats('vm','B',alternate='serial')['today'],1)
        self.assertEqual(self.history.player_stats('vm','',alternate='serial')['today'],2)
        self.app.history_key=lambda serial:'vm'
        self.assertEqual(FleetUI.player_history(self.app,'serial','mine')['result'],'failed')
    def test_worker_retry_rejects_unknown_account_failures_before_scheduling(self):
        from fleet_collection import FleetCollection
        self.history.record('vm','mine','failed')
        self.app.busy=lambda:False;self.app.capture_profile=lambda:None;self.app.config={}
        self.app.save=lambda:None;self.app.fleet_states={};self.app.device_reports={}
        self.app.count_label=SimpleNamespace(configure=lambda **kw:None)
        self.app.adb_path=SimpleNamespace(get=lambda:'adb');self.app.run_worker=lambda *args,**kw:None
        with patch('fleet_collection.messagebox.showerror') as error:
            FleetCollection.launch(self.app,'retry',{'vm':['mine']})
        self.assertEqual(self.app.fleet_states,{})
        self.assertIn('재시도할 실패 작업',error.call_args.args[1])


class NestedLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.data=Path(self.temp.name);self.path=self.data/'daily_manual.json'
    def test_invalid_nested_records_fail_closed_and_preserve_bytes(self):
        invalid=[{'_steps':[]},{'_steps':{'equipment':[]}},
                 {'_steps':{'equipment':{'status':[]}}},
                 {'_steps':{'equipment':{'failures':'2'}}},
                 {'_steps':{'equipment':{'pending':[]}}},
                 {'_steps':{'equipment':{'input_request':[]}}},
                 {'_steps':{'equipment':{'input_history':[[]]}}},
                 {'_steps':{'equipment':{'input_history':[{'request':[], 'resolution':{}}]}}}]
        for entry in invalid:
            with self.subTest(entry=entry):
                content=json.dumps({'vm':{'manual':{'daily_dungeons':entry}}})
                self.path.write_text(content)
                with self.assertRaises(LedgerError):ManualQuestLedger(self.path)
                self.assertEqual(self.path.read_text(),content)
    def test_continuation_surfaces_corrupt_step_as_ledger_error(self):
        from session_workflow import continuation
        journal=RunJournal(self.data/'run_progress.json');journal.begin('vm',['daily_dungeons'])
        self.path.write_text(json.dumps({'vm':{'manual':{'daily_dungeons':{'_steps':{'equipment':[]}}}}}))
        with self.assertRaises(LedgerError):
            continuation(self.data,{'vm':{'enabled':True,'daily_selected':{'daily_dungeons':True}}})
    def test_legacy_pending_and_archived_inputs_remain_usable(self):
        ledger=ManualQuestLedger(self.path)
        ledger.update('vm','daily_dungeons',{'equipment':'done','_steps':{'summon':{'pending':'sweep','status':'uncertain'}}})
        reloaded=ManualQuestLedger(self.path);reloaded.begin_run('vm')
        self.assertEqual(reloaded.detail('vm','daily_dungeons','summon')['pending'],'sweep')
        reloaded.checkpoint('vm','daily_dungeons','summon','done',pending=None)
        self.assertEqual(ManualQuestLedger(self.path).detail('vm','daily_dungeons','summon')['last_input']['origin'],'legacy_unknown')


class CompletionDayAndWaitingTests(unittest.TestCase):
    def row(self,record,day='2026-09-29',pending=None):
        from today_overview import account_overview
        result=account_overview('vm',{'selected':{'worldboss':True}},record,{},
                                {'worldboss':{'pending':pending or {}}},day)
        return next(row for row in result['tasks'] if row['task']=='worldboss')
    def test_midnight_completion_displays_on_completion_day_only(self):
        record={'day':'2026-09-28','tasks':['worldboss'],'results':{'worldboss':'collected'},
                'entries':{'worldboss':{'result':'collected','checked_at':'2026-09-28T15:02:00+00:00','reason':'after midnight'}}}
        self.assertEqual(self.row(record)['status'],'done')
        self.assertEqual(self.row(record)['reason'],'after midnight')
        self.assertNotEqual(self.row(record,'2026-09-28')['status'],'done')
    def test_old_run_without_completion_timestamp_is_not_new_day_completion(self):
        record={'day':'2026-09-28','tasks':['worldboss'],'results':{'worldboss':'collected'}}
        self.assertEqual(self.row(record)['status'],'unrun')
    def test_season_waiting_persists_reason_without_failure_or_success(self):
        from history import NO_AUTO_RETRY,ISSUES,TERMINAL_RESULTS
        with tempfile.TemporaryDirectory() as directory:
            history=History(Path(directory)/'history.json')
            outcomes=RunOutcomes('vm','vm',history,None,lambda *args:None,lambda _:None)
            trace=ExecutionTrace();trace.task='worldboss'
            collector=SimpleNamespace(trace=trace,action_state=ActionState(),daily_ledger=None,
                wait_reasons={'worldboss':'시즌 정산 대기 / 시즌 보상이 없습니다.'})
            outcomes.record('worldboss','waiting',collector)
            entry=history.get('vm','worldboss')
            self.assertIn('시즌 정산',entry['reason'])
            self.assertEqual(entry['consecutive_failures'],0);self.assertEqual(entry['daily'],{})
            self.assertIn('waiting',NO_AUTO_RETRY);self.assertNotIn('waiting',ISSUES|TERMINAL_RESULTS)
    def test_season_waiting_preserves_old_pending_guidance(self):
        pending={'kraken':{'requested_at':'2026-09-20T01:00:00+09:00','version':'0.7.68'}}
        record={'day':'2026-09-29','tasks':['worldboss'],'results':{'worldboss':'waiting'},
                'entries':{'worldboss':{'reason':'시즌 정산 대기'}}}
        row=self.row(record,pending=pending)
        self.assertEqual(row['status'],'waiting');self.assertEqual(row['pending'],pending)
        self.assertIn('시즌 정산',row['reason']);self.assertIn('2026-09-20',row['reason'])


class PendingResolutionPresentationTests(unittest.TestCase):
    def test_free_claim_issues_and_waiting_have_resolution_and_visible_cause(self):
        import validate_history_lifecycle as fixture
        harness=fixture.HistoryLifecycleTests();harness.setUp()
        self.addCleanup(harness.tearDown)
        app=harness.a
        app.history.record('vm','worldboss','waiting',reason='시즌 정산 대기 / 보상 화면 확인')
        app.history_dialog('vm')
        self.assertTrue(any('시즌 정산 대기 / 보상 화면 확인' in item.args for item in harness.widgets))
        buttons=[item for item in harness.widgets if '보류 해결' in item.args]
        self.assertEqual(len(buttons),2)
        resolved=[];app.resolve_history_pending=lambda ident,task:resolved.append((ident,task))
        for button in buttons:button.args[2]()
        self.assertEqual(set(resolved),{('vm','farm'),('vm','worldboss')})


if __name__=='__main__':unittest.main()
