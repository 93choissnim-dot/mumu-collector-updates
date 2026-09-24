"""Truthful outcomes, safe resumption and small-window regressions."""
import tempfile
from pathlib import Path
import unittest
from ui_state import task_display_order,task_summary

class CompactReliabilityTests(unittest.TestCase):
    def test_issues_precede_success_without_changing_execution_selection(self):
        player={'selected':{'worldboss':True,'farm':True,'wood':True}}
        entries={'worldboss':{'result':'collected'},'farm':{'result':'failed'},'wood':{'result':'skipped'}}
        self.assertEqual(task_display_order(player,entries),['farm','worldboss','wood'])
        self.assertEqual(player['selected'],{'worldboss':True,'farm':True,'wood':True})
    def test_partial_daily_result_does_not_claim_all_done(self):
        from ui_state import entry_summary
        self.assertEqual(entry_summary('daily_dungeons',{'result':'failed','progress':{'complete':2,'total':7,'excluded':0}}),('부분 완료 2/7','warning'))
    def test_paid_exclusions_are_not_success(self):
        from ui_state import entry_summary
        self.assertEqual(entry_summary('daily_pass',{'result':'already_complete','progress':{'complete':3,'total':3,'excluded':3}}),('유료 항목 제외','muted'))
    def test_connection_summary_requires_recognized_game(self):
        from ui_state import connection_summary
        import numpy as np
        image=np.zeros((540,960,3),np.uint8)
        self.assertIn('실행 준비 완료',connection_summary({'s':{'image':image,'state':'menu','package':'game'}}))
        self.assertNotIn('실행 준비 완료',connection_summary({'s':{'image':image,'state':'unknown','package':'game'}}))
        self.assertNotIn('실행 준비 완료',connection_summary({}))
    def test_saved_size_is_validated_and_fits_work_area(self):
        from ui_layout import preferred_size,fit_size
        self.assertEqual(preferred_size({'window_size':[720,700]}),(720,700))
        self.assertEqual(preferred_size({'window_size':['bad',None]}),(680,800))
        size,minimum=fit_size((0,0,800,600),1.5,preferred_size({}), (620,430))
        self.assertLessEqual(size[0],517);self.assertLessEqual(size[1],360)
    def test_failure_reason_survives_successful_exclusion(self):
        from history import History
        with tempfile.TemporaryDirectory() as d:
            h=History(Path(d)/'history.json')
            h.record('vm','daily_pass','already_complete',reason='유료 항목 제외',progress={'complete':3,'total':3,'excluded':3})
            self.assertEqual(h.get('vm','daily_pass')['reason'],'유료 항목 제외')
            self.assertEqual(h.stats('vm')['today'],0)

class ResumeTests(unittest.TestCase):
    def test_restart_keeps_only_unfinished_same_account_same_day(self):
        from run_journal import RunJournal
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'runs.json';j=RunJournal(p)
            j.begin('account-a',['farm','mine','daily_dungeons'],'2026-09-24')
            j.result('account-a','farm','collected');j.result('account-a','mine','failed')
            new=RunJournal(p)
            self.assertEqual(new.remaining('account-a','2026-09-24'),['mine','daily_dungeons'])
            self.assertEqual(new.remaining('account-b','2026-09-24'),[])
            self.assertEqual(new.remaining('account-a','2026-09-25'),[])
    def test_corrupt_journal_blocks_resume(self):
        from run_journal import RunJournal
        from daily_state import LedgerError
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'runs.json';p.write_text('{bad')
            with self.assertRaises(LedgerError):RunJournal(p)
    def test_final_review_excludes_uncertain_and_completed_inputs(self):
        from run_review import review_candidates
        from action_state import ActionState
        a=ActionState();a.reserve('mine')
        self.assertEqual(review_candidates(['farm','mine','wood','training'],{'farm':'failed','mine':'failed','wood':'collected','training':'deferred'},a),['farm'])
    def test_daily_pending_request_blocks_automatic_reentry(self):
        from run_review import review_candidates
        from action_state import ActionState
        records={'daily_dungeons':{'_steps':{'equipment':{'status':'uncertain','pending':'sweep_action'}}}}
        self.assertEqual(review_candidates(['daily_dungeons'],{'daily_dungeons':'failed'},ActionState(),records),[])

if __name__=='__main__':unittest.main()

class FreeOnlyTests(unittest.TestCase):
    def test_paid_donation_is_excluded_without_click_or_spend(self):
        from validate_daily_execution import screen
        from extra_collector import ExtraCollector
        from daily_state import DailyLedger,korea_day
        from unittest.mock import Mock
        import threading
        with tempfile.TemporaryDirectory() as d:
            c=ExtraCollector(Mock(),Mock(),threading.Event(),lambda _:None)
            c.daily_ledger=DailyLedger(Path(d)/'daily.json');c.daily_ident='vm';c.daily_day=korea_day();c.daily_task='daily_guild';c.daily_step='donation'
            c.daily_guild_page=Mock();c.daily_wait=Mock(return_value=screen('daily_donate','donate_50'))
            c.daily_tap=Mock();c.daily_performed=False;c.last_image=None
            c.daily_guild_donation()
            self.assertFalse(c.daily_performed)
            self.assertFalse(any(call.args[1]=='donate_50' for call in c.daily_tap.call_args_list if len(call.args)>1))
            self.assertTrue(c.daily_detail().get('excluded'))
            self.assertIsNone(c.daily_detail().get('pending'))
    def test_final_review_does_not_repeat_incomplete_inputs(self):
        from run_review import final_review
        from action_state import ActionState
        from types import SimpleNamespace
        from execution_trace import ExecutionTrace
        import threading
        c=SimpleNamespace(action_state=ActionState(),trace=ExecutionTrace(),forget_observations=lambda:None)
        c.action_state.reserve('mine')
        seen=[]
        def execute(tasks):seen.extend(tasks);return {'farm':'collected'}
        result=final_review(c,['farm','mine'],{'farm':'failed','mine':'attempted'},execute,lambda _:None,threading.Event())
        self.assertEqual(seen,['farm']);self.assertEqual(result,{'farm':'collected','mine':'attempted'})
    def test_stop_prevents_final_review(self):
        from run_review import final_review
        from action_state import ActionState
        from types import SimpleNamespace
        import threading
        stop=threading.Event();stop.set();seen=[]
        final_review(SimpleNamespace(action_state=ActionState()),['farm'],{'farm':'failed'},lambda tasks:seen.extend(tasks),lambda _:None,stop)
        self.assertEqual(seen,[])

class EmptyDashboardTests(unittest.TestCase):
    def test_refresh_empty_or_first_disabled_task_has_no_stale_reason(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from ui_roster import RosterUI
        for player in (None,{'name':'VM','selected':{'farm':True}}):
            root=Mock();root.winfo_width.return_value=680;root._get_window_scaling.return_value=1
            panel=Mock();panel.winfo_width.return_value=650;panel._get_widget_scaling.return_value=1
            widget=Mock()
            app=SimpleNamespace(root=root,players={'vm':player} if player else {},view_id='vm',detail_name=Mock(),
                connection_text=Mock(),connection_badge=Mock(),detail_enabled_value=Mock(),detail_enabled=Mock(),
                summaries=lambda:{},detail_summary=[],layout_task_cards=lambda:None,history_entries=lambda _: {},
                fleet_states={},busy=lambda:False,attention_label=Mock(),detail_panel=panel,
                detail_results={'worldboss':widget},detail_times={'worldboss':Mock()},detail_task_rows={'worldboss':Mock()},
                detail_checked=Mock(),device_reports={},preview_stamp=Mock())
            RosterUI.refresh_details(app)
            self.assertIn(widget._tooltip_text,('—','사용 안 함'))

class ResumeInitializationTests(unittest.TestCase):
    def test_unstarted_daily_account_is_initialized_before_resume(self):
        from validate_fleet import ManualLaunchTests
        from daily_state import ManualQuestLedger,DAILY_STEPS
        from unittest.mock import patch
        from contextlib import ExitStack
        from history import History
        with tempfile.TemporaryDirectory() as d,ExitStack() as stack:
            data=Path(d);app=ManualLaunchTests().app();app.history=History(data/'history.json')
            ledger=ManualQuestLedger(data/'daily_manual.json')
            for task,steps in DAILY_STEPS.items():
                for step in steps:ledger.mark('b',task,step)
                ledger.mark('b',task,'_complete')
            ledger.checkpoint('b','daily_dungeons','equipment','uncertain',pending='sweep_action',values={'equipment':None,'_complete':None})
            stack.enter_context(patch('app.DATA',data))
            stack.enter_context(patch('fleet_collection.run_fleet')) # stop before either account is executed
            app.launch('daily')
            after=ManualQuestLedger(data/'daily_manual.json')
            self.assertFalse(after.done('b','daily_guild','attendance'))
            self.assertEqual(after.detail('b','daily_dungeons','equipment')['pending'],'sweep_action')

class FinalReviewScopeTests(unittest.TestCase):
    def test_explicit_retry_permission_does_not_reopen_done_dungeons_on_final_pass(self):
        from extra_collector import ExtraCollector
        from daily_state import DailyLedger,DAILY_STEPS,korea_day
        from unittest.mock import Mock
        from run_review import final_review
        import threading
        with tempfile.TemporaryDirectory() as d:
            c=ExtraCollector(Mock(),Mock(),threading.Event(),lambda _:None)
            c.daily_ledger=DailyLedger(Path(d)/'daily.json');c.daily_ident='vm';c.daily_day=korea_day()
            c.manual_retry_tasks={'daily_dungeons'};c.daily_task='daily_dungeons'
            for step in DAILY_STEPS['daily_dungeons']:
                if step!='treasure':c.daily_ledger.mark('vm','daily_dungeons',step)
            c.daily_ledger.checkpoint('vm','daily_dungeons','treasure','failed',reason='button not found')
            c.daily_open=Mock();c.daily_main=Mock();seen=[]
            c.daily_dungeon=lambda step:(seen.append(step),c.daily_mark(step))
            def execute(tasks):return {task:c.collect_daily(task) for task in tasks}
            final_review(c,['daily_dungeons'],{'daily_dungeons':'failed'},execute,lambda _:None,c.stop)
            self.assertEqual(seen,['treasure'])

class KeyProgressTests(unittest.TestCase):
    def test_confirmed_free_key_is_partial_not_dungeon_success(self):
        from extra_collector import ExtraCollector
        from daily_state import DailyLedger,korea_day
        from run_review import progress_snapshot
        from ui_state import entry_summary
        from unittest.mock import Mock
        import threading
        with tempfile.TemporaryDirectory() as d:
            c=ExtraCollector(Mock(),Mock(),threading.Event(),lambda _:None)
            c.daily_ledger=DailyLedger(Path(d)/'daily.json');c.daily_ident='vm';c.daily_day=korea_day()
            c.daily_ledger.checkpoint('vm','daily_dungeons','equipment','failed',free_key_received=True,reason='소탕 버튼 미인식')
            progress=progress_snapshot(c,'daily_dungeons')
            self.assertEqual(progress.get('free_keys'),1)
            text,tone=entry_summary('daily_dungeons',{'result':'failed','progress':progress})
            self.assertEqual((text,tone),('열쇠 수령 / 미완료','warning'))
            self.assertEqual(progress['complete'],0)
