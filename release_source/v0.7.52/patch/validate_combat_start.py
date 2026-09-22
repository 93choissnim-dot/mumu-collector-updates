"""Combat startup has its own budget; only observed outcomes resolve input."""
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock

from collector import Halt
from daily_execution import OutcomeUnknown
from daily_state import DailyLedger,korea_day
from extra_collector import ExtraCollector
from run_control import ResumeRecognition
from vision import Screen,Match


def screen(state,*keys):
    return Screen(state,{'daily_'+k:Match('daily_'+k,1,0,(480,380)) for k in keys})


class CombatStartTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.clock=0.
        c=self.c=ExtraCollector(Mock(),Mock(),threading.Event(),lambda _:None)
        c.daily_ident='vm';c.daily_task='daily_dungeons';c.daily_step='stone';c.daily_day=korea_day()
        c.daily_ledger=DailyLedger(Path(tmp.name)/'daily.json')
        c.daily_checkpoint('uncertain',pending='d_enter')
        c.now=lambda:self.clock
        c.pause=lambda duration:setattr(self,'clock',self.clock+duration)
        self.room=screen('daily_room_stone','d_enter')

    def observe(self,choose):
        def capture():
            self.c.last_screen=choose()
            return self.c.last_screen
        self.c.screen=capture

    def assert_unresolved(self):
        self.assertEqual(self.c.daily_detail()['pending'],'d_enter')
        self.assertFalse(self.c.daily_done('stone'))
        self.assertIsNone(self.c.daily_combat_evidence)

    def test_unchanged_room_stops_early_and_cannot_repeat_pending_entry(self):
        c=self.c;self.observe(lambda:self.room)
        with self.assertRaisesRegex(Halt,'전투 시작'):
            c.daily_combat({self.room.state})
        self.assertGreaterEqual(self.clock,20)
        self.assertLess(self.clock,21)
        self.assert_unresolved()
        with self.assertRaises(OutcomeUnknown):c.daily_committed_tap(self.room,'d_enter')
        c.device.click.assert_not_called()

    def test_loading_or_one_battle_frame_does_not_extend_startup_budget(self):
        battle=screen('daily_battle','battle_skip');unknown=screen('unknown')
        self.observe(lambda:battle if 10<=self.clock<10.3 else unknown)
        with self.assertRaisesRegex(Halt,'전투 시작'):
            self.c.daily_combat({self.room.state})
        self.assertLess(self.clock,21)
        self.assert_unresolved();self.c.device.click.assert_not_called()

    def test_delayed_battle_gets_full_completion_budget_from_confirmed_start(self):
        battle=screen('daily_battle','battle_skip');result=screen('daily_result')
        self.observe(lambda:self.room if self.clock<15 else battle if self.clock<245
                     else result if self.clock<247 else self.room)
        c=self.c
        returned,confirmed=c.daily_combat({self.room.state},on_result=lambda:
            c.daily_confirm_input(c.daily_combat_evidence))
        self.assertEqual(returned.state,self.room.state);self.assertTrue(confirmed)
        self.assertGreaterEqual(self.clock,247)
        self.assertIsNone(c.daily_detail()['pending'])
        self.assertEqual(c.daily_detail()['input_resolution']['source'],'daily_result')
        c.device.click.assert_called_once_with((480,380))

    def test_confirmed_battle_still_has_bounded_completion_wait(self):
        battle=screen('daily_battle','battle_skip')
        self.observe(lambda:self.room if self.clock<15 else battle)
        with self.assertRaisesRegex(Halt,'전투 종료'):
            self.c.daily_combat({self.room.state})
        self.assertGreaterEqual(self.clock,255)
        self.assertLess(self.clock,257)
        self.assert_unresolved();self.c.device.click.assert_called_once_with((480,380))

    def test_fast_result_resolves_once_without_battle_frame(self):
        c=self.c;result=screen('daily_result');observed=[]
        self.observe(lambda:result if self.clock<2 else self.room)
        def resolved():
            observed.append(c.daily_combat_evidence)
            c.daily_confirm_input(c.daily_combat_evidence)
        self.assertEqual(c.daily_combat({self.room.state},on_result=resolved),(self.room,True))
        self.assertEqual(observed,['daily_result'])
        self.assertIsNone(c.daily_detail()['pending']);c.device.click.assert_not_called()

    def test_direct_clear_still_obeys_result_contract(self):
        clear=screen('daily_clear','battle_leave')
        for accept in (False,True):
            with self.subTest(accept_clear=accept):
                self.clock=0;self.c.device.click.reset_mock();observed=[]
                self.observe(lambda:clear if self.clock<1 else self.room)
                returned,result=self.c.daily_combat({self.room.state},accept_clear=accept,
                    on_result=lambda:observed.append(self.c.daily_combat_evidence))
                self.assertEqual(returned.state,self.room.state);self.assertEqual(result,accept)
                self.assertEqual(observed,['daily_clear'] if accept else [])
                self.c.device.click.assert_called_once_with((480,380))

    def test_explicit_short_timeout_still_limits_startup(self):
        self.observe(lambda:self.room)
        with self.assertRaisesRegex(Halt,'전투 시작'):
            self.c.daily_combat({self.room.state},timeout=2)
        self.assertLess(self.clock,3);self.assert_unresolved()

    def test_stop_or_pause_reacquisition_propagates_without_resolution(self):
        for exception in (Halt('사용자가 중지했습니다.'),ResumeRecognition()):
            with self.subTest(exception=type(exception).__name__):
                self.c.screen=Mock(side_effect=exception)
                with self.assertRaises(type(exception)):
                    self.c.daily_combat({self.room.state})
                self.assert_unresolved();self.c.device.click.assert_not_called()


if __name__=='__main__':unittest.main()
