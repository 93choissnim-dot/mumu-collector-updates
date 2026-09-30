"""Synthetic regressions for current-run causes and read-only pending guidance."""
import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from execution_trace import ExecutionTrace
from history import History
from run_journal import RunJournal
from today_overview import account_overview

class TraceCauseTests(unittest.TestCase):
    def test_issue_after_result_updates_bounded_outcome_and_failed_step(self):
        trace=ExecutionTrace();trace.task='mine';trace.step='claim'
        trace.event('task_outcome',result='failed',reason='')
        trace.event('task_issue',reason='mine button not recognized')
        for _ in range(230):trace.event('screen',actual='menu')
        report=trace.snapshot()
        self.assertEqual(report['task_outcomes'][0]['reason'],'mine button not recognized')
        self.assertEqual(report['failure_steps'],[{'task':'mine','step':'claim','reason':'mine button not recognized'}])
    def test_account_scope_is_serialized_without_breaking_legacy_trace(self):
        trace=ExecutionTrace();trace.account_scope='account:profile'
        self.assertEqual(trace.snapshot().get('account_scope'),'account:profile')
        self.assertIsNone(ExecutionTrace().snapshot().get('account_scope'))

class PendingGuidanceTests(unittest.TestCase):
    def row(self,task,pending,record=None,daily=None):
        report=account_overview('a',{'name':'A','enabled':True,'selected':{task:True}},
            record or {},daily or {},{task:{'pending':pending}},'2026-09-28')
        return next(r for r in report['tasks'] if r['task']==task)
    def test_old_pending_explains_date_slot_version_and_safe_action_without_mutating(self):
        pending={'kraken':{'id':'request-one','version':'0.7.63','requested_at':'2026-09-25T18:30:00+00:00'}}
        before=copy.deepcopy(pending);row=self.row('worldboss',pending)
        self.assertEqual(row['status'],'uncertain')
        for text in ('2026-09-26 03:30 KST','크라켄','0.7.63','게임 화면','중복 입력'):
            self.assertIn(text,row['reason'])
        self.assertNotIn('kraken',row['reason'])
        self.assertEqual(pending,before)
    def test_missing_timestamp_is_explicit_and_does_not_borrow_current_date(self):
        row=self.row('mine',{'claim':{'id':'legacy'}})
        self.assertIn('요청 시각 기록 없음',row['reason'])
        self.assertIn('/ 수령:',row['reason']);self.assertNotIn('2026-09-28',row['reason'])
    def test_invalid_timestamp_is_not_presented_as_verified_date(self):
        row=self.row('mine',{'claim':{'requested_at':'invalid'}})
        self.assertIn('요청 시각 확인 불가',row['reason'])
    def test_current_cause_and_pending_guidance_are_both_visible(self):
        record={'day':'2026-09-28','tasks':['mine'],'results':{'mine':'failed'},
                'entries':{'mine':{'reason':'current screen unreadable'}}}
        row=self.row('mine',{'claim':{}},record)
        self.assertIn('current screen unreadable',row['reason']);self.assertIn('게임 화면',row['reason'])
        record['day']='2026-09-27'
        self.assertNotIn('current screen unreadable',self.row('mine',{'claim':{}},record)['reason'])

class OutcomePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name);self.history=History(self.path/'history.json')
        self.journal=RunJournal(self.path/'run_progress.json');self.journal.begin('scope-a',['mine','wood','daily_guild','daily_pass'])
        self.events=[]
    def recorder(self):
        import fleet_collection
        cls=getattr(fleet_collection,'RunOutcomes',None)
        self.assertIsNotNone(cls,'RunOutcomes must reconcile callback order before publishing summaries')
        return cls('a','scope-a',self.history,self.journal,lambda *event:self.events.append(event),lambda text:None)
    def collector(self):
        from action_state import ActionState
        trace=ExecutionTrace();trace.task='mine';trace.step='claim'
        return SimpleNamespace(trace=trace,action_state=ActionState(),daily_ledger=None)
    def test_late_cause_updates_disk_journal_history_and_trace_without_incrementing_failure(self):
        outcomes=self.recorder();collector=self.collector()
        outcomes.record('mine','failed',collector);outcomes.issue('mine','claim screen missing',collector)
        self.assertEqual(History(self.history.path).get('scope-a','mine')['reason'],'claim screen missing')
        self.assertEqual(self.history.get('scope-a','mine')['consecutive_failures'],1)
        self.assertEqual(RunJournal(self.journal.path).data['scope-a']['entries']['mine']['reason'],'claim screen missing')
        self.assertEqual(collector.trace.snapshot()['task_outcomes'][0]['reason'],'claim screen missing')
        self.assertEqual(self.events[-1][1][2]['reason'],'claim screen missing')
    def test_issue_before_result_does_not_modify_old_history_and_cannot_leak_between_tasks_or_runs(self):
        self.history.record('scope-a','mine','failed',reason='previous run',run_id='old')
        outcomes=self.recorder();collector=self.collector();outcomes.issue('mine','new mine reason',collector)
        self.assertEqual(self.history.get('scope-a','mine')['reason'],'previous run')
        outcomes.record('mine','failed',collector)
        self.assertEqual(self.history.get('scope-a','mine')['reason'],'new mine reason')
        collector.trace.task='wood';outcomes.record('wood','failed',collector)
        self.assertNotIn('mine reason',self.history.get('scope-a','wood')['reason'])
        fresh=self.recorder();other=self.collector();fresh.record('mine','failed',other)
        outcomes.issue('mine','late old run reason',collector)
        self.assertEqual(self.history.get('scope-a','mine')['run_id'],other.trace.run_id)
        self.assertNotIn('new mine reason',self.history.get('scope-a','mine')['reason'])
        self.assertNotIn('late old run reason',self.history.get('scope-a','mine')['reason'])
        self.assertNotIn('late old run reason',self.journal.data['scope-a']['entries']['mine']['reason'])
    def test_stale_daily_summary_cannot_explain_another_daily_task(self):
        outcomes=self.recorder();collector=self.collector()
        collector.daily_task='daily_guild';collector.daily_summary='old guild cause';collector.trace.task='daily_pass'
        outcomes.record('daily_pass','failed',collector)
        self.assertNotIn('old guild cause',self.history.get('scope-a','daily_pass')['reason'])
    def test_success_does_not_inherit_failure_and_late_return_issue_does_not_undo_success(self):
        outcomes=self.recorder();collector=self.collector();outcomes.issue('mine','transient failure',collector)
        outcomes.record('mine','collected',collector);outcomes.issue('mine','return failed',collector)
        self.assertEqual(self.history.get('scope-a','mine')['reason'],'')
        self.assertEqual(sum(self.history.get('scope-a','mine')['daily'].values()),1)
        self.assertEqual(collector.trace.snapshot()['task_outcomes'][0]['result'],'collected')
        self.assertEqual(collector.trace.snapshot()['task_outcomes'][0]['reason'],'')

if __name__=='__main__':unittest.main()
