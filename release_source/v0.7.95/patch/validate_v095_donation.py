"""Count-based guild choices exercise real routes and durable records."""
import copy, unittest
import validate_v065_donation as donation_cases
from profile_edits import merge_profiles

class DonationModeTests(unittest.TestCase):
    def test_off_sends_no_donation(self):
        d,done,error=donation_cases.GuildDonationTests().route(donation_mode='off',remaining=4)
        self.assertIsNone(error);self.assertEqual((d.free_clicks,d.paid),(0,0));self.assertTrue(done)

    def test_free_never_sends_paid(self):
        d,done,error=donation_cases.GuildDonationTests().route(donation_mode='free',remaining=4)
        self.assertIsNone(error);self.assertEqual((d.free_clicks,d.paid),(1,0))

    def test_four_ignores_legacy_ruby_budget(self):
        d,done,error=donation_cases.GuildDonationTests().route(donation_mode='four',remaining=4,paid_limit=0)
        self.assertIsNone(error);self.assertEqual((d.free_clicks,d.paid),(1,3));self.assertTrue(done)

    def test_four_stops_even_if_completion_badge_missing(self):
        d,done,error=donation_cases.GuildDonationTests().route(donation_mode='four',remaining=8,counter_cycle=True)
        self.assertIsNone(error);self.assertEqual((d.free_clicks,d.paid),(1,3))

    def test_free_already_used_allows_only_three_paid(self):
        d,done,error=donation_cases.GuildDonationTests().route(donation_mode='four',remaining=8,free=False,counter_cycle=True)
        self.assertIsNone(error);self.assertEqual(d.paid,3)

    def test_rerun_and_switch_modes_preserve_daily_count(self):
        d,done,error=donation_cases.GuildDonationTests().route(donation_mode='off',remaining=8,counter_cycle=True,manual=True,
                                  rerun_modes=('free','four','off','four'))
        self.assertIsNone(error)
        self.assertEqual([(f,p) for f,p,_ in d.runs],[(0,0),(1,0),(1,3),(1,3),(1,3)])

    def test_four_does_not_repeat_ambiguous_payment(self):
        d,done,error=donation_cases.GuildDonationTests().route(donation_mode='four',free=False,evidence='unchanged',resume=True)
        self.assertIsNotNone(error);self.assertEqual(d.paid,1)
        self.assertEqual(d.detail.get('pending'),'donate_50')

    def test_mode_survives_profile_merge(self):
        original={'a':dict(enabled=True,minutes=60,selected={},guild_donation_mode='free')}
        draft=copy.deepcopy(original);draft['a']['guild_donation_mode']='four'
        self.assertEqual(merge_profiles(original,original,draft)['a'].get('guild_donation_mode'),'four')

class MigrationTests(unittest.TestCase):
    def test_startup_preserves_old_meaning_and_explicit_new_choices(self):
        from fleet_ui import FleetUI
        from types import SimpleNamespace
        for old,mode in [(0,'free'),(750,'four'),(50,'free')]:
            app=SimpleNamespace(config={'players':{'a':{'guild_paid_limit':old}}})
            FleetUI.init_fleet(app)
            self.assertEqual(app.players['a']['guild_donation_mode'],mode)
        for mode in ('off','free','four'):
            app=SimpleNamespace(config={'players':{'a':{'guild_donation_mode':mode,'guild_paid_limit':750}}})
            FleetUI.init_fleet(app)
            self.assertEqual(app.players['a']['guild_donation_mode'],mode)

    def test_off_preserves_unresolved_input(self):
        d,done,error=donation_cases.GuildDonationTests().route(donation_mode='off',pending=True)
        self.assertEqual((d.free_clicks,d.paid),(0,0))
        self.assertEqual(d.detail.get('pending'),'donate_50')

    def test_count_selection_saves_without_ruby_prompt(self):
        from ui_player_settings import PlayerSettings
        from types import SimpleNamespace
        from unittest.mock import Mock,patch
        original={'a':dict(enabled=True,minutes=60,selected={},guild_donation_mode='free')}
        draft=copy.deepcopy(original);draft['a'].update(guild_donation_mode='four',guild_paid_limit=750)
        editor=PlayerSettings.__new__(PlayerSettings)
        editor.app=SimpleNamespace(busy=lambda:False,players=copy.deepcopy(original),save=Mock(),
            update_fleet_summary=Mock(),status=Mock())
        editor.capture=lambda:None;editor.original=original;editor.draft=draft
        editor.error=Mock();editor.window=Mock();editor.active=None
        with patch('ui_player_settings.messagebox.askyesno',side_effect=AssertionError('Unexpected ruby prompt')):
            self.assertTrue(editor.apply())
        self.assertEqual(editor.app.players['a']['guild_donation_mode'],'four')

if __name__=='__main__':unittest.main()
