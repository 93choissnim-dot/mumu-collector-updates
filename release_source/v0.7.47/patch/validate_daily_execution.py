"""Independent interruption, partial-recovery and evidence regressions."""
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch
import zipfile
import numpy as np
from collector import Halt,ScreenChanged
from daily_execution import OutcomeUnknown
from daily_state import DailyLedger,LedgerError,DAILY_STEPS,korea_day
from extra_collector import ExtraCollector
from history import History
from diagnostics import save_collection_failure,save_execution_trace,export_diagnostics
from execution_trace import ExecutionTrace
from run_control import ResumeRecognition
from run_support import Schedule
from vision import Screen,Match


def screen(state,*keys):
    return Screen(state,{'daily_'+k:Match('daily_'+k,1,0,(480,380)) for k in keys})

class DailyExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'daily_tasks.json'
        self.c=ExtraCollector(Mock(),Mock(),threading.Event(),Mock(),on_issue=Mock())
        c=self.c;c.daily_ledger=DailyLedger(self.path);c.daily_ident='a'*24
        c.daily_day=korea_day();c.daily_task='daily_dungeons';c.daily_step='treasure'
        c.daily_main=Mock();c.daily_open=Mock();c.last_screen=screen('daily_room_treasure')
        c.last_image=np.zeros((540,960,3),np.uint8)
    def tearDown(self):self.tmp.cleanup()
    def complete_others(self,task,except_steps):
        self.c.daily_task=task
        for step in DAILY_STEPS[task]:
            if step not in except_steps:self.c.daily_ledger.mark(self.c.daily_ident,task,step)
    def test_later_dungeon_runs_after_verified_recovery_and_retry_only_missing(self):
        c=self.c;visited=[];c.daily_recover=Mock()
        def execute(key):
            visited.append(key)
            if key=='treasure':raise Halt('free key unknown')
            c.daily_mark(key)
        c.daily_dungeon=execute
        self.assertEqual(c.collect_daily('daily_dungeons'),'failed')
        self.assertEqual(visited,list(DAILY_STEPS['daily_dungeons']))
        self.assertTrue(c.daily_done('artifact'));self.assertFalse(c.daily_done('_complete'))
        c.daily_recover.assert_called_once();visited.clear()
        c.daily_dungeon=lambda key:(visited.append(key),c.daily_mark(key))
        self.assertEqual(c.collect_daily('daily_dungeons'),'no_entries')
        self.assertEqual(visited,['treasure']);self.assertTrue(c.daily_done('_complete'))
    def test_unknown_recovery_stops_before_later_dungeon(self):
        c=self.c;visited=[];self.complete_others('daily_dungeons',{'treasure','artifact'})
        c.daily_dungeon=lambda key:(visited.append(key),(_ for _ in ()).throw(Halt('unknown')))
        c.daily_recover=Mock(side_effect=Halt('unknown recovery'))
        with self.assertRaises(Halt):c.collect_daily('daily_dungeons')
        self.assertEqual(visited,['treasure']);self.assertFalse(c.daily_done('artifact'))
    def test_identical_failure_twice_is_deferred_without_further_action(self):
        c=self.c;self.complete_others('daily_dungeons',{'treasure'})
        c.daily_recover=Mock();c.daily_dungeon=Mock(side_effect=Halt('missing free key'))
        self.assertEqual(c.collect_daily('daily_dungeons'),'failed')
        self.assertEqual(c.collect_daily('daily_dungeons'),'deferred')
        self.assertEqual(c.collect_daily('daily_dungeons'),'deferred')
        self.assertEqual(c.daily_dungeon.call_count,2)
        c.daily_ledger=DailyLedger(self.path)
        self.assertEqual(c.daily_detail('treasure')['status'],'blocked')
        c.daily_ledger.reset_blocked(c.daily_ident,'daily_dungeons')
        self.assertEqual(c.daily_detail('treasure')['status'],'pending')
    def test_different_failure_is_not_mislabelled_repeated(self):
        c=self.c;self.complete_others('daily_dungeons',{'treasure'});c.daily_recover=Mock()
        c.daily_dungeon=Mock(side_effect=[Halt('missing free key'),Halt('missing close')])
        self.assertEqual(c.collect_daily('daily_dungeons'),'failed')
        self.assertEqual(c.collect_daily('daily_dungeons'),'failed')
    def test_repaired_recognition_block_is_rechecked_once_and_persisted(self):
        c=self.c;c.daily_recover=Mock();reason='일일 작업 버튼 확인 시간 초과: d_enter, d_free_0, d_free_1'
        c.daily_checkpoint('blocked',reason=reason,failures=2)
        action=Mock(side_effect=Halt(reason))
        c.daily_run_step('treasure','보물 창고',action)
        self.assertEqual(action.call_count,1)
        self.assertEqual(c.daily_detail()['recognition_revision'],40)
        c.daily_run_step('treasure','보물 창고',action)
        self.assertEqual(c.daily_detail()['status'],'blocked')
        c.daily_ledger=DailyLedger(self.path)
        c.daily_run_step('treasure','보물 창고',action)
        self.assertEqual(action.call_count,2)
    def test_repaired_rule_never_resets_pending_input_or_unrelated_block(self):
        c=self.c;action=Mock()
        for fields in ({'reason':'일일 작업 버튼 확인 시간 초과: d_enter, d_free_0, d_free_1','pending':'d_enter'},
                       {'reason':'different error','pending':None}):
            c.daily_checkpoint('blocked',**fields)
            c.daily_run_step('treasure','보물 창고',action)
        action.assert_not_called()
    def test_guild_failure_does_not_block_later_steps(self):
        c=self.c;c.daily_recover=Mock();visited=[]
        for key in DAILY_STEPS['daily_guild']:
            def action(k=key):
                visited.append(k)
                if k=='donation':raise OutcomeUnknown('pending payment')
                c.daily_mark(k)
            setattr(c,'daily_guild_'+key,action)
        self.assertEqual(c.collect_daily('daily_guild'),'deferred')
        self.assertEqual(visited,list(DAILY_STEPS['daily_guild']))
        self.assertTrue(c.daily_done('raid'));self.assertFalse(c.daily_done('donation'))
    def test_stop_pause_midnight_and_storage_failure_never_start_recovery(self):
        c=self.c;c.daily_recover=Mock()
        for exception in (ResumeRecognition(),LedgerError('disk full')):
            with self.assertRaises(type(exception)):
                c.daily_run_step('treasure','보물',Mock(side_effect=exception))
        c.stop.set()
        with self.assertRaises(Halt):c.daily_run_step('treasure','보물',Mock(side_effect=Halt('stopped')))
        c.stop.clear();c.daily_day='2000-01-01'
        with self.assertRaises(Halt):c.daily_run_step('treasure','보물',Mock())
        c.daily_recover.assert_not_called()
    def test_sweep_recovery_closes_only_verified_controls(self):
        c=self.c;c.daily_wait=Mock(side_effect=[screen('daily_sweep'),screen('daily_room_equipment'),screen('daily_dungeons')])
        c.daily_tap=Mock();c.daily_recover()
        self.assertEqual([call.args[1] for call in c.daily_tap.call_args_list],['sweep_close','d_close'])
        c.device.back.assert_not_called()
    def test_guild_recovery_stays_inside_guild(self):
        c=self.c;c.daily_task='daily_guild'
        c.daily_wait=Mock(return_value=screen('daily_relic'));c.daily_guild_page=Mock()
        c.daily_recover()
        c.daily_guild_page.assert_called_once();c.daily_main.assert_not_called()
    def test_pending_payment_survives_restart_and_explicit_retry(self):
        c=self.c;c.daily_task='daily_guild';c.daily_step='donation'
        c.daily_checkpoint('uncertain',pending='donate_50',values={'donation_paid':1})
        c.daily_ledger=DailyLedger(self.path);c.daily_ledger.reset_blocked(c.daily_ident,'daily_guild')
        c.daily_guild_page=Mock();c.daily_wait=Mock(return_value=screen('daily_guild_menu'))
        c.daily_tap=Mock()
        with self.assertRaises(OutcomeUnknown):c.daily_guild_donation()
        c.daily_tap.assert_not_called();self.assertEqual(c.daily_detail()['pending'],'donate_50')
    def test_pending_payment_reconciles_only_with_final_donated_badge(self):
        c=self.c;c.daily_task='daily_guild';c.daily_step='donation'
        c.daily_checkpoint('uncertain',pending='donate_50',values={'donation_paid':1})
        c.daily_guild_page=Mock();c.daily_wait=Mock(return_value=screen('daily_guild_menu','guild_donated'))
        c.daily_tap=Mock();c.daily_guild_donation()
        self.assertTrue(c.daily_done('donation'));self.assertIsNone(c.daily_detail()['pending']);c.daily_tap.assert_not_called()
    def test_payment_reservation_after_fresh_button_check(self):
        c=self.c;c.screen=Mock(return_value=screen('daily_donate'));reserve=Mock()
        with self.assertRaises(Halt):c.daily_tap(screen('daily_donate','donate_50'),'donate_50',before_input=reserve)
        reserve.assert_not_called();c.device.click.assert_not_called()
    def test_reservation_failure_prevents_payment(self):
        c=self.c;c.screen=Mock(return_value=screen('daily_donate','donate_50'))
        with self.assertRaises(LedgerError):
            c.daily_tap(screen('daily_donate','donate_50'),'donate_50',before_input=Mock(side_effect=LedgerError('disk')))
        c.device.click.assert_not_called()
    def test_failed_input_keeps_pending_payment_and_does_not_confirm_it(self):
        c=self.c;c.daily_task='daily_guild';c.daily_step='donation';c.daily_recover=Mock()
        c.screen=Mock(return_value=screen('daily_donate','donate_50'));c.device.click.side_effect=Halt('transport')
        def attempt():
            c.daily_tap(screen('daily_donate','donate_50'),'donate_50',before_input=lambda:c.daily_checkpoint('uncertain',pending='donate_50',values={'donation_paid':1}))
        c.daily_run_step('donation','기부',attempt)
        c.daily_ledger=DailyLedger(self.path)
        self.assertEqual(c.daily_detail()['status'],'uncertain');self.assertFalse(c.daily_done('donation'))
    def test_legacy_started_raid_never_reenters(self):
        c=self.c;c.daily_task='daily_guild';c.daily_step='raid';c.daily_mark('raid','started')
        c.daily_guild_page=Mock();c.daily_tap=Mock()
        c.daily_wait=Mock(side_effect=[Mock(state='daily_raid_map'),Mock(state='daily_raid_detail')])
        with self.assertRaises(OutcomeUnknown):c.daily_guild_raid()
        c.daily_guild_page.assert_called_once();self.assertEqual(c.daily_wait.call_count,2)
        self.assertNotIn('raid_fight',[a.args[1] for a in c.daily_tap.call_args_list if len(a.args)>1])
    def test_deferred_is_visible_issue_but_has_no_automatic_retry(self):
        from ui_state import task_summary,retry_tasks
        from fleet_runner import run_fleet
        s=Schedule(['daily_guild'],86400);s.next();s.complete(['daily_guild'],{'daily_guild':'deferred'},False,10)
        self.assertFalse(s.pending);self.assertEqual(s.next()[0],86410)
        h=History(Path(self.tmp.name)/'history.json');h.record('vm','daily_guild','deferred',reason='약탈 결과 미확인')
        self.assertEqual(h.stats('vm')['today'],0);self.assertEqual(h.stats('vm')['failed_tasks'],1)
        self.assertEqual(task_summary('daily_guild','deferred'),('자동 재시도 보류','warning'))
        self.assertEqual(retry_tasks({'selected':{'daily_guild':True}},{'daily_guild':h.get('vm','daily_guild')}),['daily_guild'])
        events=[]
        run_fleet([{'id':'vm','name':'test','rooms':['daily_guild'],'minutes':60}],False,threading.Event(),threading.Event(),lambda *_:{'daily_guild':'deferred'},lambda *a:events.append(a))
        self.assertEqual([e[1][1]['status'] for e in events if e[0]=='fleet_status'][-1],'확인 필요')
    def test_corrupt_nested_record_fails_closed(self):
        for data in ({'vm':[]},{'vm':{korea_day():[]}}, {'vm':{korea_day():{'daily_guild':[]}}}):
            self.path.write_text(json.dumps(data))
            with self.assertRaises(LedgerError):DailyLedger(self.path)
    def test_new_day_does_not_inherit_blocked_or_pending_states(self):
        c=self.c;c.daily_checkpoint('blocked',pending='donate_50')
        self.assertEqual(c.daily_ledger.detail(c.daily_ident,c.daily_task,c.daily_step,'2000-01-01'),{})

class ReadinessTests(unittest.TestCase):
    def collector(self,frames):
        c=ExtraCollector(Mock(),Mock(),threading.Event(),Mock());c.daily_day=korea_day()
        c.screen=Mock(side_effect=frames);c.pause=Mock();return c
    def test_page_and_button_confirm_together_but_tap_still_requires_fresh_frame(self):
        ready=screen('daily_sweep','sweep_action')
        c=self.collector([ready,ready,ready,ready])
        c.device.click.side_effect=lambda _:self.assertEqual(c.screen.call_count,3)
        found=c.daily_ready({'daily_sweep'},['sweep_action']);self.assertEqual(c.screen.call_count,2)
        c.daily_tap(found,'sweep_action');self.assertEqual(c.screen.call_count,4)
        c.device.click.assert_called_once()
    def test_intervening_unknown_resets_consecutive_confirmation(self):
        ready=screen('daily_sweep','sweep_action')
        c=self.collector([ready,screen('unknown'),ready,ready])
        c.daily_ready({'daily_sweep'},['sweep_action']);self.assertEqual(c.screen.call_count,4)
    def test_changed_button_or_page_resets_confirmation(self):
        first=screen('daily_sweep','sweep_free_1');second=screen('daily_sweep','sweep_action')
        c=self.collector([first,second,second])
        c.daily_ready({'daily_sweep'},['sweep_free_1','sweep_action']);self.assertEqual(c.screen.call_count,3)
    def test_successive_daily_tasks_do_not_toggle_menu_between_them(self):
        c=ExtraCollector(Mock(),Mock(),threading.Event(),Mock());main=screen('main')
        def collect(task):c.last_screen=main;c.record_task(task,'already_complete')
        c.collect_daily=collect;c.last_screen=main;c.ensure_menu=Mock(return_value=screen('menu'))
        with patch('start_navigation.prepare_start',return_value=main):
            c.cycle(['daily_pass','daily_dungeons'])
        self.assertEqual(c.ensure_menu.call_count,1)
    def test_step_summary_separates_done_missing_and_uncertain(self):
        from ui_state import daily_step_summary
        text=daily_step_summary('daily_guild',{'attendance':'done','_steps':{'donation':{'status':'uncertain'},'raid':{'status':'blocked'}}})
        self.assertIn('1/6',text);self.assertIn('출석: 완료',text);self.assertIn('기부: 결과 미확인',text)
        self.assertIn('공방 약탈: 재시도 보류',text);self.assertIn('성물 보상: 미실행',text)

class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        c=self.c=ExtraCollector(Mock(),Mock(),threading.Event(),Mock())
        c.daily_day=korea_day();c.daily_task='daily_guild';c.daily_step='donation';c.daily_ident='vm'
        c.daily_ledger=DailyLedger(Path(self.tmp.name)/'daily.json')
        self.clock=0
        c.now=lambda:self.clock
        c.pause=lambda seconds:setattr(self,'clock',self.clock+seconds)
        c.dismiss_overlay=Mock(return_value=False)
    def tearDown(self):self.tmp.cleanup()
    def test_midnight_during_capture_prevents_reservation_and_click(self):
        c=self.c;day=[c.daily_day];ready=screen('daily_donate','donate_50');reserve=Mock()
        def capture():day[0]='2099-01-01';return ready
        c.screen=Mock(side_effect=capture)
        with patch('daily_actions.korea_day',side_effect=lambda:day[0]),self.assertRaises(Halt):
            c.daily_tap(ready,'donate_50',before_input=reserve)
        reserve.assert_not_called();c.device.click.assert_not_called()
    def test_midnight_during_reservation_keeps_pending_without_click(self):
        c=self.c;day=[c.daily_day];ready=screen('daily_donate','donate_50')
        c.screen=Mock(return_value=ready)
        def reserve():
            c.daily_checkpoint('uncertain',pending='donate_50',values={'donation_paid':1})
            day[0]='2099-01-01'
        with patch('daily_actions.korea_day',side_effect=lambda:day[0]),self.assertRaises(Halt):
            c.daily_tap(ready,'donate_50',before_input=reserve)
        c.device.click.assert_not_called()
        self.assertEqual(c.daily_detail()['pending'],'donate_50')
        self.assertEqual(c.daily_ledger.detail('vm','daily_guild','donation',day[0]),{})
    def test_midnight_during_trace_prevents_click(self):
        c=self.c;day=[c.daily_day];ready=screen('daily_donate','donate_50')
        c.screen=Mock(return_value=ready);c.trace=Mock()
        c.trace.event.side_effect=lambda *a,**k:day.__setitem__(0,'2099-01-01')
        with patch('daily_actions.korea_day',side_effect=lambda:day[0]),self.assertRaises(Halt):
            c.daily_tap(ready,'donate_50')
        c.device.click.assert_not_called()
    def test_delayed_entry_waits_for_battle_before_accepting_return(self):
        c=self.c;room=screen('daily_room_stone','d_enter');battle=screen('daily_battle','battle_skip')
        c.screen=Mock(side_effect=[room]*4+[screen('unknown')]*2+[battle]*2+[room]*2)
        c.daily_tap=Mock()
        returned,result=c.daily_combat({room.state},timeout=10)
        self.assertEqual(returned,room);self.assertFalse(result)
        self.assertEqual(c.screen.call_count,10)
        c.daily_tap.assert_called_once_with(battle,'battle_skip')
    def test_unchanged_room_times_out_without_repeating_entry(self):
        c=self.c;c.screen=Mock(return_value=screen('daily_room_stone','d_enter'))
        with self.assertRaisesRegex(Halt,'전투 시작'):c.daily_combat({'daily_room_stone'},timeout=2)
        c.device.click.assert_not_called()
    def test_unknown_loading_alone_does_not_prove_combat(self):
        c=self.c;room=screen('daily_guild_dungeon','guild_fight');frames=iter([screen('unknown')]*3)
        c.screen=Mock(side_effect=lambda:next(frames,room))
        with self.assertRaisesRegex(Halt,'전투 시작'):c.daily_combat({room.state},timeout=2)
        c.device.click.assert_not_called()
    def test_fast_result_confirms_combat_and_marks_result_once(self):
        c=self.c;room=screen('daily_raid_map');result=screen('daily_result');callback=Mock()
        c.screen=Mock(side_effect=[result]*3+[room]*2)
        self.assertEqual(c.daily_combat({room.state},on_result=callback),(room,True))
        callback.assert_called_once();c.device.click.assert_not_called()
    def test_one_battle_frame_is_not_stable_proof(self):
        c=self.c;room=screen('daily_room_stone');frames=iter([screen('daily_battle','battle_skip')])
        c.screen=Mock(side_effect=lambda:next(frames,room))
        with self.assertRaisesRegex(Halt,'전투 시작'):c.daily_combat({room.state},timeout=2)
        c.device.click.assert_not_called()
    def test_battle_ends_on_preclick_capture_then_clear_can_exit(self):
        c=self.c;battle=screen('daily_battle','battle_skip');clear=screen('daily_clear','battle_leave')
        room=screen('daily_room_stone')
        c.screen=Mock(side_effect=[battle,battle,screen('unknown'),clear,clear,clear,room,room])
        self.assertEqual(c.daily_combat({room.state},timeout=10),(room,False))
        c.device.click.assert_called_once_with((480,380))
    def test_auto_exit_on_preclick_capture_does_not_abort_combat(self):
        c=self.c;clear=screen('daily_clear','battle_leave');room=screen('daily_room_stone')
        c.screen=Mock(side_effect=[clear,clear,room,room,room])
        self.assertEqual(c.daily_combat({room.state},timeout=10),(room,False))
        c.device.click.assert_not_called()
    def test_other_combat_errors_still_stop(self):
        c=self.c;c.screen=Mock(return_value=screen('daily_battle','battle_skip'))
        c.daily_tap=Mock(side_effect=Halt('device disconnected'))
        with self.assertRaisesRegex(Halt,'disconnected'):c.daily_combat({'daily_room_stone'},timeout=10)
    def test_final_scroll_card_is_opened_without_ninth_drag(self):
        c=self.c;empty=screen('daily_dungeons');found=screen('daily_dungeons','card_artifact');room=screen('daily_room_artifact')
        c.daily_wait=Mock(side_effect=[empty]*8+[found,room]);c.screen=Mock(return_value=empty);c.daily_tap=Mock()
        self.assertEqual(c.daily_find_dungeon('artifact'),room)
        self.assertEqual(c.device.drag.call_count,8);c.daily_tap.assert_called_once_with(found,'card_artifact')
    def test_missing_card_still_has_bounded_search(self):
        c=self.c;empty=screen('daily_dungeons');c.daily_wait=Mock(return_value=empty);c.screen=Mock(return_value=empty)
        with self.assertRaisesRegex(Halt,'카드를 찾지'):c.daily_find_dungeon('artifact')
        self.assertEqual(c.device.drag.call_count,8);c.device.click.assert_not_called()
    def test_midnight_during_scroll_capture_prevents_drag(self):
        c=self.c;day=[c.daily_day];empty=screen('daily_dungeons');c.daily_wait=Mock(return_value=empty)
        def capture():day[0]='2099-01-01';return empty
        c.screen=Mock(side_effect=capture)
        with patch('daily_actions.korea_day',side_effect=lambda:day[0]),self.assertRaises(Halt):c.daily_find_dungeon('artifact')
        c.device.drag.assert_not_called()
    def check_recovery(self,exception):
        from run_support import cycle_with_recovery
        c=Mock();c.results={};c.claim_counts={};runs=[]
        def cycle(remaining,restore):
            runs.append(list(remaining))
            if len(runs)==1:
                c.results={'daily_guild':'deferred','daily_pass':'already_complete'}
                raise exception
            return {'farm':'collected'}
        c.cycle.side_effect=cycle;device=Mock();device.package='game';device.current_package.return_value='game'
        stop=Mock();stop.is_set.return_value=False;stop.wait.return_value=False
        adb=Mock();adb.is_connected.return_value=False
        result=cycle_with_recovery(c,['daily_guild','daily_pass','farm'],False,adb,device,Mock(),stop,Mock())
        self.assertEqual(runs[1],['farm']);self.assertEqual(result['daily_guild'],'deferred')
        self.assertEqual(result['daily_pass'],'already_complete');self.assertEqual(result['farm'],'collected')
    def test_pause_resume_excludes_deferred_tasks(self):self.check_recovery(ResumeRecognition())
    def test_connection_recovery_excludes_deferred_tasks(self):self.check_recovery(Halt('disconnected'))

class EvidenceTests(unittest.TestCase):
    def test_recovery_failure_keeps_first_task_image_and_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);ident='b'*24;trace=ExecutionTrace();trace.task='daily_guild';trace.step='relic'
            first=np.full((540,960,3),120,np.uint8);later=np.zeros_like(first)
            save_collection_failure(p,ident,first,screen('daily_relic'),'claim missing','daily_guild',trace=trace)
            task=p/f'last_{ident}_daily_guild_error.png';evidence=p/f'last_{ident}_daily_guild_relic_evidence.zip'
            original=task.read_bytes();archive=evidence.read_bytes()
            save_collection_failure(p,ident,later,screen('unknown'),'recovery failed','daily_guild',trace=trace)
            self.assertEqual(task.read_bytes(),original);self.assertEqual(evidence.read_bytes(),archive)
            self.assertEqual(json.loads((p/f'last_{ident}_daily_guild_error.json').read_text())['reason'],'claim missing')
            self.assertEqual(json.loads((p/f'last_{ident}_error.json').read_text())['reason'],'recovery failed')
    def test_export_preserves_per_step_evidence_and_current_ledger(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);ident='a'*24;ledger=DailyLedger(p/'daily_tasks.json');trace=ExecutionTrace()
            trace.task='daily_dungeons';im=np.zeros((540,960,3),np.uint8)
            for step in ('stone','treasure'):
                trace.step=step;trace.expected=['daily_room_'+step]
                frame=screen('daily_room_'+step);trace.frame(im,frame)
                trace.event('input',point=[744,440]);ledger.checkpoint(ident,trace.task,step,'failed',reason='unknown')
                save_collection_failure(p,ident,im,frame,'unknown',trace.task,trace=trace,ledger=ledger.snapshot(ident))
            save_execution_trace(p,ident,trace,ledger.snapshot(ident))
            export_diagnostics(p,p/'export.zip')
            with zipfile.ZipFile(p/'export.zip') as z:
                self.assertIn('daily_tasks.json',z.namelist())
                self.assertIn('last_'+ident+'_run.json',z.namelist())
                for step in ('stone','treasure'):
                    name=f'last_{ident}_daily_dungeons_{step}_evidence.zip';self.assertIn(name,z.namelist())
                    with zipfile.ZipFile(io.BytesIO(z.read(name))) as evidence:
                        report=json.loads(evidence.read('trace.json'))
                        self.assertEqual(report['run_id'],trace.run_id);self.assertEqual(report['step'],step)
                        self.assertIn('daily_state.json',evidence.namelist());self.assertIn('before_1.jpg',evidence.namelist())
                index=json.loads(z.read('diagnostics.json'))
                self.assertTrue(all(x['run_id']==trace.run_id for x in index['snapshots']))
    def test_trace_memory_and_timing_are_bounded(self):
        trace=ExecutionTrace();im=np.zeros((540,960,3),np.uint8)
        for _ in range(230):trace.event('wait')
        for _ in range(9):trace.frame(im,screen('main'))
        trace.observe(im,screen('main'),.2,.1)
        self.assertEqual(len(trace.events),200);self.assertEqual(len(trace.frames),6)
        self.assertEqual(trace.timing['captures'],1);self.assertEqual(trace.timing['capture_seconds'],.2)

class DonationEvidenceTests(unittest.TestCase):
    def setUp(self):
        import cv2
        self.cv2=cv2
    def frame(self,n):
        # Synthetic numeral/label shapes, independent of user's image pixels.
        im=np.zeros((540,960),np.uint8)
        rng=np.random.default_rng(7)
        im[410:429,411:513]=rng.integers(20,220,(19,102),dtype=np.uint8)
        im[410:429,529:548]=rng.integers(20,220,(19,19),dtype=np.uint8)
        self.cv2.putText(im,str(n),(515,424),self.cv2.FONT_HERSHEY_SIMPLEX,.45,200,1,self.cv2.LINE_AA)
        return im
    def test_unchanged_counter_and_brightness_change_are_not_confirmation(self):
        from donation_evidence import changed_counter
        a=self.frame(3)
        self.assertIsNone(changed_counter(a,a.copy()))
        self.assertIsNone(changed_counter(a,np.clip(a.astype(float)*.9+10,0,255).astype(np.uint8)))
    def test_counter_change_requires_same_label_and_denominator(self):
        from donation_evidence import changed_counter
        a=self.frame(3);b=self.frame(2)
        self.assertIsNotNone(changed_counter(a,b))
        for box in ((410,429,411,513),(410,429,529,548),(410,429,515,529)):
            y,r,x,z=box;c=b.copy();c[y:r,x:z]=0
            self.assertIsNone(changed_counter(a,c))
    def test_cost_fifty_stays_distinct_at_pressed_and_settled_scales(self):
        from daily_vision import DailyVision
        v=DailyVision(Path(__file__).parent/'assets')
        for scale in (.95,1.,1.05):
            im=np.full((540,960,3),110,np.uint8)
            for name in ('donate_title','donate_rewards','donate_50'):
                x,y,r,b=v.specs[name]['box'];ref=v.templates[name][0]
                if name=='donate_50':ref=self.cv2.resize(ref,None,fx=scale,fy=scale)
                h,w=ref.shape[:2];im[y:y+h,x:x+w]=ref
            state,m=v.recognize(im)
            self.assertEqual(state,'daily_donate');self.assertIn('daily_donate_50',m)
            x,y,r,b=v.specs['donate_50']['box'];im[y-7:b+7,x-7:r+7]=0
            _,m=v.recognize(im);self.assertNotIn('daily_donate_50',m)

if __name__=='__main__':unittest.main()

class DurableEntryTests(unittest.TestCase):
    setUp=DailyExecutionTests.setUp
    tearDown=DailyExecutionTests.tearDown
    # Inherit the fixture only; the explicit regressions cover restart after
    # dispatch, not a mock of the new implementation's internal control flow.
    def test_entry_transport_failure_survives_restart_and_blocks_second_entry(self):
        c=self.c;s=screen('daily_room_treasure','d_enter');c.screen=Mock(return_value=s)
        c.device.click.side_effect=Halt('ack lost');c.post_input=Mock()
        with self.assertRaises(Halt):c.daily_committed_tap(s,'d_enter')
        c.daily_ledger=DailyLedger(self.path)
        self.assertEqual(c.daily_detail()['pending'],'d_enter')
        with self.assertRaises(OutcomeUnknown):c.daily_committed_tap(s,'d_enter')
        self.assertEqual(c.device.click.call_count,1)
    def test_pending_entry_can_confirm_exhaustion_without_reentering(self):
        c=self.c;c.daily_checkpoint('uncertain',pending='d_enter')
        done=screen('daily_room_treasure','d_count_0','d_free_0')
        c.daily_find_dungeon=Mock(return_value=done);c.daily_ready=Mock(return_value=done);c.daily_close_room=Mock()
        c.daily_dungeon('treasure');self.assertTrue(c.daily_done('treasure'));c.device.click.assert_not_called()
    def test_pending_sweep_never_replays_on_unchanged_button(self):
        c=self.c;c.daily_step='equipment';c.daily_checkpoint('uncertain',pending='sweep_action')
        s=screen('daily_sweep','sweep_action');c.daily_find_dungeon=Mock();c.daily_tap=Mock()
        c.daily_wait=Mock(return_value=s);c.daily_ready=Mock(return_value=s)
        with self.assertRaises(OutcomeUnknown):c.daily_dungeon('equipment')
        self.assertEqual([x.args[1] for x in c.daily_tap.call_args_list],['d_sweep_open'])
    def test_failed_reservation_never_enters(self):
        c=self.c;s=screen('daily_room_treasure','d_enter');c.screen=Mock(return_value=s)
        with patch.object(Path,'replace',side_effect=OSError('disk full')):
            with self.assertRaises(LedgerError):c.daily_committed_tap(s,'d_enter')
        c.device.click.assert_not_called()

class ManualQuestTests(unittest.TestCase):
    def test_explicit_runs_reinspect_completed_steps_without_calendar(self):
        from daily_state import ManualQuestLedger,DAILY_TASKS,DAILY_STEPS
        with tempfile.TemporaryDirectory() as directory:
            ledger=ManualQuestLedger(Path(directory)/'manual.json');ledger.begin_run('vm')
            for task in DAILY_TASKS:
                for step in DAILY_STEPS[task]:ledger.mark('vm',task,step,day='2026-09-22')
                ledger.mark('vm',task,day='2026-09-22')
            self.assertTrue(ledger.done('vm','daily_pass',day='2026-09-23'))
            ledger=ManualQuestLedger(ledger.path);ledger.begin_run('vm')
            for task in DAILY_TASKS:
                self.assertFalse(ledger.done('vm',task))
                for step in DAILY_STEPS[task]:self.assertFalse(ledger.done('vm',task,step))
    def test_pending_inputs_and_budget_survive_rerun_and_restart(self):
        from daily_state import ManualQuestLedger
        with tempfile.TemporaryDirectory() as directory:
            ledger=ManualQuestLedger(Path(directory)/'manual.json');ledger.begin_run('vm')
            ledger.checkpoint('vm','daily_guild','donation','uncertain',pending='donate_50',values={'donation_paid':2,'donation_verified':1})
            ledger.checkpoint('vm','daily_dungeons','relic','blocked',pending='d_enter',failures=2)
            ledger=ManualQuestLedger(ledger.path);ledger.begin_run('vm')
            self.assertEqual(ledger.detail('vm','daily_guild','donation')['pending'],'donate_50')
            self.assertEqual(ledger.get('vm','daily_guild','donation_paid'),2)
            self.assertEqual(ledger.detail('vm','daily_dungeons','relic')['pending'],'d_enter')
            self.assertFalse(ledger.done('vm','daily_dungeons','relic'))
    def test_legacy_done_does_not_block_but_pending_is_migrated(self):
        from daily_state import ManualQuestLedger,DailyLedger
        with tempfile.TemporaryDirectory() as directory:
            old=DailyLedger(Path(directory)/'daily.json');old.mark('vm','daily_pass')
            old.checkpoint('vm','daily_guild','raid','uncertain',pending='raid_fight',values={'raid':'started'})
            new=ManualQuestLedger(Path(directory)/'manual.json');new.begin_run('vm',old.path)
            self.assertFalse(new.done('vm','daily_pass'))
            self.assertEqual(new.get('vm','daily_guild','raid'),'started')
            new.mark('vm','daily_guild','raid');new.checkpoint('vm','daily_guild','raid','done',pending=None)
            new.begin_run('vm',old.path)
            self.assertIsNone(new.get('vm','daily_guild','raid'))
    def test_midnight_does_not_interrupt_manual_run(self):
        from daily_actions import DailyActions
        from daily_state import ManualQuestLedger
        with tempfile.TemporaryDirectory() as directory:
            c=DailyActions();c.daily_ledger=ManualQuestLedger(Path(directory)/'manual.json');c.daily_day='2000-01-01'
            c.daily_check_day()
    def test_failed_begin_run_preserves_previous_checkpoints(self):
        from daily_state import ManualQuestLedger,LedgerError
        with tempfile.TemporaryDirectory() as directory:
            ledger=ManualQuestLedger(Path(directory)/'manual.json');ledger.begin_run('vm');ledger.mark('vm','daily_pass')
            with patch.object(Path,'replace',side_effect=OSError('disk full')):
                with self.assertRaises(LedgerError):ledger.begin_run('vm')
            self.assertTrue(ledger.done('vm','daily_pass'))
            self.assertTrue(ManualQuestLedger(ledger.path).done('vm','daily_pass'))
