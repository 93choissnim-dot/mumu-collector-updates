"""Session boundaries, journal preservation and conservative continuation."""
import json
from pathlib import Path
import tempfile
import unittest
from run_journal import RunJournal
from daily_state import ManualQuestLedger,LedgerError,korea_day
from action_state import ActionState,account_scope

class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.data=Path(self.temp.name)
        self.journal=RunJournal(self.data/'run_progress.json')
        self.players={'a':{'enabled':True,'selected':{'farm':True,'wood':True},'daily_selected':{'daily_dungeons':True},'name':'A'}}
    def test_new_scope_keeps_unfinished_other_scope(self):
        self.journal.begin('a',['daily_dungeons','farm']);self.journal.result('a','farm','collected')
        self.journal.begin('a',['wood'])
        self.assertEqual(set(self.journal.remaining('a')),{'daily_dungeons','wood'})
    def test_resume_does_not_reset_completed_or_held_results(self):
        self.journal.begin('a',['farm','wood','daily_dungeons']);self.journal.result('a','farm','collected');self.journal.result('a','daily_dungeons','deferred')
        self.assertTrue(callable(getattr(self.journal,'continue_run',None)),'resume must preserve its original journal')
        self.journal.continue_run('a',['wood'])
        self.assertEqual(self.journal.data['a']['results'],{'farm':'collected','daily_dungeons':'deferred'})
    def test_classifies_pending_and_attempted_separately_from_unstarted(self):
        from session_workflow import continuation
        self.journal.begin('a',['farm','wood','daily_dungeons'])
        ActionState(self.data/'action_state.json','a').reserve('wood')
        self.journal.result('a','daily_dungeons','attempted')
        plan=continuation(self.data,self.players)
        self.assertEqual(plan['targets'],{'a':['farm']})
        self.assertEqual({r['task'] for r in plan['held']},{'wood','daily_dungeons'})
    def test_old_day_disabled_and_changed_profile_excluded(self):
        from session_workflow import continuation
        self.journal.begin('a',['farm'],day='2000-01-01')
        self.assertFalse(continuation(self.data,self.players)['targets'])
        self.journal.begin('a',['farm']);self.players['a']['daily_profile']='different'
        self.assertFalse(continuation(self.data,self.players)['targets'])
        self.players['a']['daily_profile']='';self.players['a']['enabled']=False
        self.assertFalse(continuation(self.data,self.players)['targets'])
    def test_pending_daily_step_blocks_aggregate_even_without_result(self):
        from session_workflow import continuation
        self.journal.begin('a',['daily_dungeons','farm'])
        # A persisted real ledger schema, no speculative fake completed result.
        ledger=ManualQuestLedger(self.data/'daily_manual.json');ledger.begin_run('a')
        ledger.checkpoint('a','daily_dungeons','equipment',pending={'action':'sweep'},status='uncertain')
        plan=continuation(self.data,self.players)
        self.assertEqual(plan['targets'],{'a':['farm']})
        self.assertEqual(plan['held'][0]['task'],'daily_dungeons')
    def test_scope_selection_and_no_daily_automatic(self):
        from session_workflow import task_scope
        p=self.players['a']
        self.assertEqual(task_scope(p,'daily'),['daily_dungeons'])
        self.assertEqual(set(task_scope(p,'all')),{'farm','wood','daily_dungeons'})
        self.assertEqual(task_scope(p,'daily',repeat=True),[])
        self.assertEqual(set(task_scope(p,'all',repeat=True)),{'farm','wood'})
    def test_unstarted_current_row_never_inherits_old_success(self):
        from session_workflow import session_entry
        row=session_entry('farm',{'tasks':['farm'],'results':{},'entries':{}},{'result':'collected','checked_at':'old'})
        self.assertEqual(row['result'],'waiting');self.assertNotIn('checked_at',row)
    def test_prior_row_is_explicitly_not_this_run(self):
        from session_workflow import session_entry
        row=session_entry('farm',{'tasks':['wood'],'results':{}},{'result':'collected'})
        self.assertTrue(row['previous'])
    def test_corrupt_unhashable_task_fails_closed_with_ledger_error(self):
        (self.data/'run_progress.json').write_text(json.dumps({'a':{'day':korea_day(),'tasks':[{}],'results':{}}}))
        with self.assertRaises(LedgerError):RunJournal(self.data/'run_progress.json')

if __name__=='__main__':unittest.main()

class DailySelectionTests(unittest.TestCase):
    def test_new_daily_selection_keeps_other_completed_steps(self):
        with tempfile.TemporaryDirectory() as d:
            ledger=ManualQuestLedger(Path(d)/'daily.json');ledger.begin_run('a')
            ledger.mark('a','daily_guild','attendance')
            ledger.begin_run('a',tasks=['daily_dungeons'])
            self.assertTrue(ledger.done('a','daily_guild','attendance'))
    def test_profile_merge_saves_daily_selection(self):
        import copy
        from profile_edits import merge_profiles
        p={'a':{'enabled':True,'minutes':60,'selected':{'farm':True},'daily_selected':{'daily_pass':True,'daily_dungeons':True,'daily_guild':True}}}
        draft=copy.deepcopy(p);draft['a']['daily_selected']['daily_guild']=False
        self.assertFalse(merge_profiles(p,p,draft)['a']['daily_selected']['daily_guild'])

class PresentationBoundaryTests(unittest.TestCase):
    def test_backlog_remains_previous_after_restart(self):
        from session_workflow import session_entry
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'run.json';j=RunJournal(p);j.begin('a',['daily_dungeons'])
            j.result('a','daily_dungeons','deferred',{'progress':{'complete':6,'total':7}});j.begin('a',['farm'])
            row=session_entry('daily_dungeons',RunJournal(p).data['a'],{'result':'deferred'})
            self.assertTrue(row.get('previous'))
    def test_old_day_or_different_profile_cannot_display_current_success(self):
        from ui_roster import RosterUI
        from types import SimpleNamespace
        from run_control import RunControl
        for day,scope in [('2000-01-01','a'),(korea_day(),'old-profile')]:
            app=SimpleNamespace(players={'a':{'enabled':True,'selected':{'farm':True},'minutes':60,'daily_profile':''}},
                fleet_states={'a':{'session_day':day,'scope':scope,'status':'확인 완료','rooms':['farm'],'results':{'farm':'collected'}}},
                device_reports={'s':{'instance_id':'a'}},unavailable_devices=set(),stop=RunControl(),busy=lambda:False,
                history_entries=lambda _: {'farm':{'result':'collected'}})
            state=RosterUI.summaries(app)['a']
            self.assertNotEqual(state['status'],'확인 완료');self.assertEqual(state['completed'],0)
    def test_current_waiting_precedes_previous_failure(self):
        from ui_state import task_display_order
        p={'selected':{'worldboss':True,'farm':True}}
        entries={'worldboss':{'result':'failed','previous':True},'farm':{'result':'waiting'}}
        self.assertEqual(task_display_order(p,entries),['farm','worldboss'])

class EmptyDailyRowsTests(unittest.TestCase):
    def test_empty_history_slots_do_not_create_daily_rows_in_regular_scope(self):
        from types import SimpleNamespace
        from ui_workflow import WorkflowUI
        from task_catalog import TASK_LABELS
        app=SimpleNamespace(players={'a':{'selected':{'farm':True}}},config={'run_scope':'regular'},current_record=lambda _: {},history_entries=lambda _: {t:{} for t in TASK_LABELS})
        self.assertNotIn('daily_pass',WorkflowUI.display_entries(app,'a'))
