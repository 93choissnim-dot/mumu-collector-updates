"""Late combat loading and rejected navigation from the Oct 3 diagnostics."""
import unittest
from unittest.mock import Mock
import numpy as np
from collector import Halt,ScreenChanged
from daily_execution import OutcomeUnknown
from run_control import ResumeRecognition
import validate_combat_start as fixtures
screen=fixtures.screen


class LoadingTests(unittest.TestCase):
    setUp=fixtures.CombatStartTests.setUp
    observe=fixtures.CombatStartTests.observe
    assert_unresolved=fixtures.CombatStartTests.assert_unresolved

    def loading(self,choose):
        def capture():
            state=choose()
            self.c.last_image=np.zeros((540,960,3),np.uint8) if state.state=='unknown' else None
            self.c.last_screen=state
            return state
        self.c.screen=capture

    def test_reported_black_loading_then_late_clear_resolves_once(self):
        c=self.c;unknown=screen('unknown');clear=screen('daily_clear','battle_leave')
        self.loading(lambda:unknown if self.clock<23 else clear if not c.device.click.called else self.room)
        capture=c.screen
        def transition():
            state=capture()
            if 17<=self.clock<23:c.last_image=np.full((540,960,3),35,np.uint8)
            return state
        c.screen=transition
        evidence=[]
        def resolved():
            evidence.append(c.daily_combat_evidence);c.daily_confirm_input(c.daily_combat_evidence)
        returned,result=c.daily_combat({self.room.state},accept_clear=True,on_result=resolved)
        self.assertTrue(result);self.assertEqual(returned.state,self.room.state)
        self.assertEqual(evidence,['daily_clear']);self.assertIsNone(c.daily_detail()['pending'])
        self.assertEqual(c.device.click.call_count,1)

    def test_black_loading_is_bounded_and_never_reenters(self):
        self.loading(lambda:screen('unknown'))
        with self.assertRaisesRegex(Halt,'전투 시작'):self.c.daily_combat({self.room.state})
        self.assertGreaterEqual(self.clock,60);self.assertLess(self.clock,61)
        self.assert_unresolved();self.c.device.click.assert_not_called()

    def test_arbitrary_unknown_image_retains_short_startup_limit(self):
        self.observe(lambda:screen('unknown'));self.c.last_image=np.full((540,960,3),80,np.uint8)
        with self.assertRaises(Halt):self.c.daily_combat({self.room.state})
        self.assertLess(self.clock,21);self.assert_unresolved()

    def test_black_frame_without_pending_combat_does_not_extend(self):
        self.c.daily_confirm_input('test');self.loading(lambda:screen('unknown'))
        with self.assertRaises(Halt):self.c.daily_combat({self.room.state})
        self.assertLess(self.clock,21);self.c.device.click.assert_not_called()

    def test_black_loading_respects_explicit_short_timeout(self):
        self.loading(lambda:screen('unknown'))
        with self.assertRaises(Halt):self.c.daily_combat({self.room.state},timeout=3)
        self.assertLess(self.clock,4);self.assert_unresolved()

    def test_stop_during_extended_loading_preserves_input(self):
        self.loading(lambda:screen('unknown'));capture=self.c.screen
        def stopped():
            if self.clock>22:raise Halt('사용자가 중지했습니다.')
            return capture()
        self.c.screen=stopped
        with self.assertRaisesRegex(Halt,'사용자가 중지'):self.c.daily_combat({self.room.state})
        self.assert_unresolved();self.c.device.click.assert_not_called()


class NavigationTests(unittest.TestCase):
    setUp=fixtures.CombatStartTests.setUp

    def test_home_already_arrived_at_final_guard_is_not_clicked_again(self):
        c=self.c;raid=screen('daily_raid_map');main=screen('main')
        c.daily_wait=Mock(side_effect=[raid,main]);c.screen=Mock(side_effect=[raid,main])
        self.assertEqual(c.daily_main().state,'main');c.device.click.assert_not_called()

    def test_guild_stat_animation_rechecks_before_back(self):
        c=self.c;c.daily_task='daily_guild';c.daily_step='raid';c.post_input=Mock()
        room=screen('daily_guild_dungeon');tab=screen('daily_guild_battle')
        c.daily_wait=Mock(side_effect=[room,room,tab])
        c.screen=Mock(side_effect=[room,screen('unknown'),room,room])
        self.assertEqual(c.daily_guild_page(battle=True).state,'daily_guild_battle')
        c.device.click.assert_called_once_with((34,28))

    def test_guild_already_arrived_before_back_sends_no_touch(self):
        c=self.c;room=screen('daily_guild_dungeon');tab=screen('daily_guild_battle')
        c.daily_wait=Mock(side_effect=[room,tab]);c.screen=Mock(side_effect=[room,tab])
        self.assertEqual(c.daily_guild_page(battle=True).state,tab.state)
        c.device.click.assert_not_called()

    def test_navigation_rechecks_are_bounded(self):
        c=self.c;room=screen('daily_guild_dungeon');c.daily_wait=Mock(return_value=room)
        c.screen=Mock(side_effect=[room,screen('unknown')]*3)
        with self.assertRaises(ScreenChanged):c.daily_guild_page()
        self.assertEqual(c.daily_wait.call_count,3);c.device.click.assert_not_called()

    def test_transport_uncertainty_and_pause_are_not_retried(self):
        for error in (Halt('transport acknowledgement lost'),ResumeRecognition()):
            with self.subTest(error=type(error).__name__):
                c=self.c;room=screen('daily_guild_dungeon');c.daily_wait=Mock(return_value=room)
                c.screen=Mock(return_value=room);c.device.click=Mock(side_effect=error)
                with self.assertRaises(type(error)):c.daily_guild_page()
                c.device.click.assert_called_once();self.assertEqual(c.daily_wait.call_count,1)


if __name__=='__main__':unittest.main()
