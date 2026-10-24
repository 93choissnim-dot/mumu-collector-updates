"""Fault-injection regressions for interruption and durable-state boundaries."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from daily_state import DailyLedger, ManualQuestLedger, LedgerError


class LedgerBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'daily.json'

    def test_two_live_writers_preserve_other_accounts_pending_input(self):
        first=ManualQuestLedger(self.path,scope='a');second=ManualQuestLedger(self.path,scope='b')
        first.checkpoint('a','daily_guild','donation','uncertain',pending='donate_50')
        origin=first.detail('a','daily_guild','donation')['input_request']
        second.checkpoint('b','daily_store','ruby','done',values={'ruby':'done'})
        saved=json.loads(self.path.read_text())
        self.assertIn('a',saved)
        self.assertEqual(saved['a']['manual']['daily_guild']['_steps']['donation']['input_request'],origin)
        self.assertTrue(first.path.exists())

    def test_checkpoint_reloads_steps_written_by_another_instance(self):
        first=ManualQuestLedger(self.path);second=ManualQuestLedger(self.path)
        first.checkpoint('a','daily_store','ruby','uncertain',pending='claim')
        second.checkpoint('a','daily_store','cube_ad','done',values={'cube_ad':'done'})
        self.assertEqual(first.detail('a','daily_store','cube_ad').get('status'),'done')
        self.assertEqual(second.detail('a','daily_store','ruby').get('pending'),'claim')

    def test_begin_run_preserves_newly_reserved_payment(self):
        first=ManualQuestLedger(self.path);second=ManualQuestLedger(self.path)
        first.checkpoint('a','daily_guild','donation','uncertain',pending='donate_50')
        origin=first.detail('a','daily_guild','donation')['input_request']
        second.begin_run('a',tasks=['daily_guild'])
        self.assertEqual(second.detail('a','daily_guild','donation').get('input_request'),origin)

    def test_deleted_existing_file_is_not_recreated_from_stale_memory(self):
        ledger=ManualQuestLedger(self.path);ledger.mark('a','daily_store','ruby')
        self.path.unlink()
        with self.assertRaises(LedgerError):ledger.mark('a','daily_store','cube_ad')
        self.assertFalse(self.path.exists())

    def test_existing_empty_file_deletion_is_detected(self):
        self.path.write_text('{}');ledger=DailyLedger(self.path);self.path.unlink()
        with self.assertRaises(LedgerError):ledger.snapshot('a')

    def test_corruption_after_open_preserves_original_bytes(self):
        ledger=DailyLedger(self.path);self.path.write_text('{broken')
        with self.assertRaises(LedgerError):ledger.mark('a','daily_store','ruby')
        self.assertEqual(self.path.read_text(),'{broken')

    def test_checkpoint_uses_one_day_even_if_clock_crosses_midnight(self):
        ledger=DailyLedger(self.path)
        ledger.checkpoint('a','daily_store','ruby','uncertain',day='2026-10-25',pending='claim')
        with patch('daily_state.korea_day',side_effect=['2026-10-25','2026-10-26','2026-10-26','2026-10-26']):
            ledger.checkpoint('a','daily_store','ruby','done',pending=None)
        self.assertEqual(ledger.detail('a','daily_store','ruby','2026-10-25').get('status'),'done')
        self.assertEqual(ledger.snapshot('a','2026-10-26'),{})

    def test_legacy_pending_view_is_read_only_and_first_write_preserves_origin(self):
        from retry_resolution import _ledger,pending_choices
        root=self.path.parent;legacy=DailyLedger(root/'daily_tasks.json')
        legacy.checkpoint('a','daily_guild','donation','uncertain',pending='donate_50')
        request=legacy.detail('a','daily_guild','donation')['input_request'];before=legacy.path.read_bytes()
        current=_ledger(root,'a')
        self.assertEqual([x['step'] for x in pending_choices(root,'a','daily_guild')],['donation'])
        self.assertFalse((root/'daily_manual.json').exists())
        current.mark('a','daily_store','ruby')
        self.assertEqual(ManualQuestLedger(root/'daily_manual.json').detail('a','daily_guild','donation')['input_request'],request)
        self.assertEqual(legacy.path.read_bytes(),before)

    def test_legacy_fallback_refreshes_and_rejects_deleted_source(self):
        from retry_resolution import _ledger
        root=self.path.parent;legacy=DailyLedger(root/'daily_tasks.json')
        legacy.mark('a','daily_store','ruby')
        current=_ledger(root,'a')
        legacy.checkpoint('a','daily_guild','donation','uncertain',pending='donate_50')
        self.assertEqual(current.detail('a','daily_guild','donation').get('pending'),'donate_50')
        legacy.path.unlink()
        with self.assertRaises(LedgerError):current.mark('a','daily_store','cube_ad')
        self.assertFalse((root/'daily_manual.json').exists())


class ObservationBoundaryTests(unittest.TestCase):
    def collector(self,control,capture_hook=None,recognize_hook=None):
        import numpy as np
        from collector import Collector
        from vision import Screen
        events=[];image=np.zeros((540,960,3),dtype=np.uint8)
        def capture():
            if capture_hook:capture_hook()
            return image
        def recognize(im):
            if recognize_hook:recognize_hook()
            return Screen('farm_empty',{})
        c=Collector(SimpleNamespace(capture=capture),SimpleNamespace(recognize=recognize),control,
                    lambda _:None,on_frame=lambda *args:events.append('published'))
        return c,events

    def test_pause_during_capture_discards_observation_before_completion(self):
        from run_control import RunControl,ResumeRecognition
        control=RunControl()
        def interrupt():control.pause();control.resume()
        c,events=self.collector(control,capture_hook=interrupt)
        with self.assertRaises(ResumeRecognition):c.screen()
        self.assertEqual(events,[]);self.assertIsNone(c.last_screen)

    def test_pause_during_recognition_discards_observation(self):
        from run_control import RunControl,ResumeRecognition
        control=RunControl()
        def interrupt():control.pause();control.resume()
        c,events=self.collector(control,recognize_hook=interrupt)
        with self.assertRaises(ResumeRecognition):c.screen()
        self.assertEqual(events,[]);self.assertIsNone(c.last_screen)

    def test_stop_during_capture_cannot_publish_completion_screen(self):
        from collector import Halt
        control=threading.Event();c,events=self.collector(control,capture_hook=control.set)
        with self.assertRaises(Halt):c.screen()
        self.assertEqual(events,[]);self.assertIsNone(c.last_screen)

    def test_stop_during_recognition_cannot_publish_completion_screen(self):
        from collector import Halt
        control=threading.Event();c,events=self.collector(control,recognize_hook=control.set)
        with self.assertRaises(Halt):c.screen()
        self.assertEqual(events,[]);self.assertIsNone(c.last_screen)

    def test_new_observation_after_resume_is_usable(self):
        from run_control import RunControl
        control=RunControl();control.pause();control.resume()
        c,events=self.collector(control)
        self.assertEqual(c.screen().state,'farm_empty');self.assertEqual(events,['published'])

    def test_pause_during_trace_cannot_publish_or_confirm_empty(self):
        from run_control import RunControl,ResumeRecognition
        from vision import Screen,Match
        control=RunControl();c,events=self.collector(control)
        empty=Screen('farm_empty',{'room_farm':Match('room_farm',1,0,(10,10)),
                                  'empty_farm':Match('empty_farm',1,0,(780,500))})
        c.vision.recognize=lambda _:empty;c.pause=lambda _:None
        observe=c.trace.observe
        def trace(*args):observe(*args);control.pause();control.resume()
        c.trace.observe=trace
        with self.assertRaises(ResumeRecognition):c.confirm_room_empty('farm',empty)
        self.assertEqual(events,[]);self.assertIsNone(c.last_screen)
        self.assertEqual(getattr(c,'_observations',[]),[])

    def test_stop_during_trace_discards_observation(self):
        from run_control import RunControl
        from collector import Halt
        control=RunControl();c,events=self.collector(control)
        observe=c.trace.observe
        def trace(*args):observe(*args);control.set()
        c.trace.observe=trace
        with self.assertRaises(Halt):c.screen()
        self.assertEqual(events,[]);self.assertIsNone(c.last_screen)
        self.assertEqual(getattr(c,'_observations',[]),[])

    def test_pause_from_preview_callback_cannot_return_completion_evidence(self):
        from run_control import RunControl,ResumeRecognition
        control=RunControl();c,_=self.collector(control)
        def preview(*args):control.pause();control.resume()
        c.on_frame=preview
        with self.assertRaises(ResumeRecognition):c.screen()
        self.assertIsNone(c.last_screen);self.assertEqual(c._observations,[])

    def test_stop_from_preview_callback_discards_cached_completion_evidence(self):
        from run_control import RunControl
        from collector import Halt
        control=RunControl();c,_=self.collector(control)
        c.on_frame=lambda *args:control.set()
        with self.assertRaises(Halt):c.screen()
        self.assertIsNone(c.last_screen);self.assertEqual(c._observations,[])


class DispatchBoundaryTests(unittest.TestCase):
    def test_stop_or_update_at_status_event_prevents_account_dispatch(self):
        from fleet_runner import run_fleet
        from run_control import RunControl
        for trigger in ('stop','update'):
            with self.subTest(trigger=trigger):
                control=RunControl();update=threading.Event();calls=[]
                def event(kind,value):
                    if kind=='fleet_status':(control if trigger=='stop' else update).set()
                run_fleet([{'id':'a','name':'A','rooms':['farm'],'minutes':1}],False,
                          control,update,lambda *args:calls.append(args) or {'farm':'collected'},event)
                self.assertEqual(calls,[])

    def test_pause_at_dispatch_waits_and_update_during_pause_cancels(self):
        from fleet_runner import run_fleet
        from run_control import RunControl
        control=RunControl();update=threading.Event();paused=threading.Event();calls=[];errors=[]
        def event(kind,value):
            if kind=='fleet_status':control.pause();paused.set()
        def work():
            try:run_fleet([{'id':'a','name':'A','rooms':['farm'],'minutes':1}],False,
                          control,update,lambda *args:calls.append(args) or {'farm':'collected'},event)
            except Exception as exc:errors.append(exc)
        thread=threading.Thread(target=work,daemon=True);thread.start()
        try:
            self.assertTrue(paused.wait(1))
            update.set();control.resume();thread.join(1)
            self.assertFalse(thread.is_alive());self.assertEqual(calls,[]);self.assertEqual(errors,[])
        finally:control.set();thread.join(1)

    def test_changed_identity_prevents_first_cycle_and_recovery_input(self):
        from run_support import cycle_with_recovery
        from collector import Halt
        calls=[]
        collector=SimpleNamespace(cycle=lambda *args:calls.append('cycle') or {},results={},claim_counts={})
        recovery=SimpleNamespace(recover=lambda:calls.append('recover'))
        def verify():raise Halt('identity changed')
        with self.assertRaisesRegex(Halt,'identity changed'):
            cycle_with_recovery(collector,['farm'],False,SimpleNamespace(),SimpleNamespace(package='game'),
                                None,threading.Event(),lambda _:None,verify_identity=verify,game_recovery=recovery)
        self.assertEqual(calls,[])


class FailureFamilyTests(unittest.TestCase):
    def test_free_claim_lost_acknowledgement_reconciles_after_reload_without_extra_click(self):
        from validate_v072_free_daily import RouteHarness
        from collector import Halt
        harness=RouteHarness();harness.addCleanup=self.addCleanup
        screen=harness.screen
        c,d=harness.make('daily_summon','pet',[
            screen('free_summon_pet',1,summon=(230,500),identity_pet=(840,125)),
            screen('free_summon_pet',0,identity_pet=(840,125))])
        click=d.click
        def lost_ack(point):click(point);raise Halt('connection lost after dispatch')
        d.click=lost_ack
        with self.assertRaises(Halt):c.free_summon_step('pet')
        request=c.daily_detail()['input_request']['id']
        c.daily_ledger=DailyLedger(c.daily_ledger.path)
        d.click=click;c.forget_observations();c.free_summon_step('pet')
        self.assertTrue(c.daily_done('pet'));self.assertEqual(len(d.clicks),1)
        self.assertFalse(c.daily_detail().get('pending'))
        self.assertEqual(c.daily_detail()['last_input']['id'],request)

    def test_pending_payment_survives_midnight_reopen_and_another_account_write(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'daily.json';a=ManualQuestLedger(path);b=ManualQuestLedger(path)
            a.checkpoint('a','daily_guild','donation','uncertain',pending='donate_50',
                         values={'donation_day':'2026-10-25','donation_paid':1})
            request=a.detail('a','daily_guild','donation')['input_request']
            b.mark('b','daily_store','ruby')
            with patch('daily_state.korea_day',return_value='2026-10-26'):
                a.begin_run('a',tasks=['daily_guild'])
            reopened=ManualQuestLedger(path)
            self.assertEqual(reopened.detail('a','daily_guild','donation')['input_request'],request)
            self.assertEqual(reopened.get('a','daily_guild','donation_paid'),1)
            self.assertTrue(reopened.done('b','daily_store','ruby'))

    def test_long_reconnect_loading_retains_timeout_and_never_repeats_confirmation(self):
        from validate_network_recovery import recovery
        from game_recovery import GameRecovery
        from collector import Halt
        android,device,first,taps=recovery(stuck=True)
        self.assertIsNone(first.poll())
        for tick in (1,15,30,60,89):
            android.tick=tick
            current=GameRecovery(device,first.vision,android.stop,lambda:None,lambda _:None,clock=lambda:android.tick)
            current.startup=first.startup
            self.assertIsNone(current.poll())
        android.tick=91
        with self.assertRaises(Halt):current.poll()
        self.assertEqual(len(taps),1)
        self.assertTrue(current.startup.get('network_unconfirmed'))

    def test_repeated_overlay_is_bounded_and_cannot_become_collection(self):
        from validate_v072_free_daily import RouteHarness
        from vision import Screen,Match
        from collector import Halt
        harness=RouteHarness();harness.addCleanup=self.addCleanup
        c,d=harness.make('daily_store','ruby',[
            Screen('offline_reward',{'offline_confirm':Match('offline_confirm',1,0,(480,440))})],stuck=True)
        with self.assertRaises(Halt):c.daily_wait({'free_store'},timeout=40)
        self.assertEqual(len(d.clicks),3)
        self.assertFalse(c.daily_done('ruby'))
        self.assertLess(d.clock,40)

    def test_fsync_failure_before_claim_prevents_input_and_preserves_prior_request(self):
        from validate_v072_free_daily import RouteHarness
        harness=RouteHarness();harness.addCleanup=self.addCleanup
        c,d=harness.make('daily_summon','pet',[
            harness.screen('free_summon_pet',1,summon=(230,500),identity_pet=(840,125))])
        c.daily_ledger.checkpoint('other','daily_guild','donation','uncertain',pending='donate_50')
        before=c.daily_ledger.path.read_bytes()
        with patch('os.fsync',side_effect=OSError('disk full')):
            with self.assertRaises(LedgerError):c.free_summon_step('pet')
        self.assertEqual(d.clicks,[]);self.assertEqual(c.daily_ledger.path.read_bytes(),before)


if __name__=='__main__':unittest.main()
