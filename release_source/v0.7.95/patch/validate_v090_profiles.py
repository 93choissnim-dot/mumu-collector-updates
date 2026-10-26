"""Profile choices and explicit spending settings survive real draft merges."""
import copy
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from profile_edits import merge_profiles, copy_settings
from ui_state import validate_profile


class ProfileSafetyTests(unittest.TestCase):
    def player(self, **extra):
        return dict(enabled=True, minutes=60, selected={'farm': True},
                    daily_selected={'daily_guild': True}, daily_profile='본계정', **extra)

    def test_missing_paid_permission_defaults_to_zero(self):
        self.assertEqual(validate_profile(self.player()).get('guild_paid_limit'), 0)

    def test_budget_is_preserved_by_validation_and_three_way_merge(self):
        original={'a': self.player(guild_paid_limit=50)}
        draft=copy.deepcopy(original);draft['a']['guild_paid_limit']='100'
        current=copy.deepcopy(original);current['a']['minutes']=30
        merged=merge_profiles(current, original, draft)
        self.assertEqual(merged['a'].get('guild_paid_limit'),100)
        self.assertEqual(merged['a']['minutes'],30)

    def test_conflicting_spending_edit_is_rejected(self):
        original={'a':self.player(guild_paid_limit=50)}
        draft=copy.deepcopy(original);draft['a']['guild_paid_limit']=100
        current=copy.deepcopy(original);current['a']['guild_paid_limit']=150
        with self.assertRaises(ValueError):merge_profiles(current, original, draft)

    def test_invalid_budgets_never_become_permission(self):
        for value in [True,-1,1,51,800,'nan','50.5']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_profile(self.player(guild_paid_limit=value))

    def test_switch_remembers_old_and_new_accounts_without_overwriting_scope(self):
        original={'a':self.player(account_profiles=['부계정'])}
        draft=copy.deepcopy(original);draft['a']['daily_profile']='새계정'
        merged=merge_profiles(original, original, draft)['a']
        self.assertEqual(merged['daily_profile'],'새계정')
        self.assertEqual(set(merged.get('account_profiles',[])), {'본계정','부계정','새계정'})
        self.assertEqual(original['a']['daily_profile'],'본계정')

    def test_blank_keeps_legacy_record_scope_and_remembers_name(self):
        original={'a':self.player()};draft=copy.deepcopy(original)
        draft['a']['daily_profile']=''
        merged=merge_profiles(original,original,draft)['a']
        self.assertEqual(merged['daily_profile'],'')
        self.assertIn('본계정',merged.get('account_profiles',[]))

    def test_bulk_copy_never_copies_paid_budget_or_identity(self):
        draft={'a':self.player(guild_paid_limit=500),
               'b':self.player(guild_paid_limit=0)}
        draft['b']['daily_profile']='다른계정'
        copy_settings(draft,'a',['b'],['selected','minutes','guild_paid_limit','daily_profile'])
        self.assertEqual(draft['b']['guild_paid_limit'],0)
        self.assertEqual(draft['b']['daily_profile'],'다른계정')

    def test_declined_new_spending_leaves_live_profiles_unchanged(self):
        from ui_player_settings import PlayerSettings
        original={'a':self.player(guild_paid_limit=0)}
        draft=copy.deepcopy(original);draft['a']['guild_paid_limit']=100
        editor=PlayerSettings.__new__(PlayerSettings)
        editor.app=SimpleNamespace(busy=lambda:False,players=copy.deepcopy(original),save=Mock(),
            update_fleet_summary=Mock(),status=Mock())
        editor.capture=lambda:None;editor.original=original;editor.draft=draft
        editor.error=Mock();editor.window=Mock();editor.active=None
        with patch('ui_player_settings.messagebox.askyesno',return_value=False):
            self.assertFalse(editor.apply())
        self.assertEqual(editor.app.players,original)
        editor.app.save.assert_not_called()

    def test_legacy_string_budget_requires_confirmation_before_authorization(self):
        from ui_player_settings import PlayerSettings
        original={'a':self.player(guild_paid_limit='50')}
        editor=PlayerSettings.__new__(PlayerSettings)
        editor.app=SimpleNamespace(busy=lambda:False,players=copy.deepcopy(original),save=Mock())
        editor.capture=lambda:None;editor.original=original;editor.draft=copy.deepcopy(original)
        editor.error=Mock();editor.window=Mock();editor.active=None
        with patch('ui_player_settings.messagebox.askyesno',return_value=False) as consent:
            self.assertFalse(editor.apply())
        consent.assert_called_once()
        editor.app.save.assert_not_called()


class BinaryDonationTests(unittest.TestCase):
    def test_startup_migrates_intermediate_budgets_without_increasing_spending(self):
        from fleet_ui import FleetUI
        source={'players':{str(value):{'guild_paid_limit':value,'daily_profile':'본캐',
                'selected':{'farm':True}} for value in (0,50,100,700,750)}}
        snapshot=copy.deepcopy(source)
        app=SimpleNamespace(config=source)
        FleetUI.init_fleet(app)
        self.assertEqual({k:p['guild_paid_limit'] for k,p in app.players.items()},
                         {'0':0,'50':0,'100':0,'700':0,'750':750})
        self.assertEqual(app.players['50']['daily_profile'],'본캐')
        self.assertEqual(app.players['50']['selected'],{'farm':True})
        self.assertEqual(source['players'],snapshot['players'])
        again=SimpleNamespace(config={'players':copy.deepcopy(app.players)})
        FleetUI.init_fleet(again)
        self.assertEqual(again.players,app.players)

    def test_ui_choice_captures_numeric_budget_before_switching_players(self):
        from ui_player_settings import PlayerSettings
        def var(value):return SimpleNamespace(get=lambda:value)
        for choice,want in [('0회',0),('무료 기부',0),('4회',750)]:
            with self.subTest(choice=choice):
                editor=PlayerSettings.__new__(PlayerSettings)
                editor.active='a';editor.draft={'a':{}}
                editor.enabled=var(True);editor.minutes=var('60')
                editor.tasks={'farm':var(True)};editor.daily_tasks={'daily_guild':var(True)}
                editor.daily_profile=var('본캐');editor.guild_paid_limit=var(choice)
                editor.capture()
                self.assertEqual(editor.draft['a']['guild_paid_limit'],want)

    def test_startup_invalid_authorization_stays_free_only(self):
        from fleet_ui import FleetUI
        for value in ('750',750.0,True,None,800):
            with self.subTest(value=value):
                app=SimpleNamespace(config={'players':{'a':{'guild_paid_limit':value}}})
                FleetUI.init_fleet(app)
                self.assertEqual(app.players['a']['guild_paid_limit'],0)

    def test_zero_to_maximum_keeps_same_day_usage_and_free_confirmation(self):
        from validate_v065_donation import GuildDonationTests
        d,done,error=GuildDonationTests().route(paid_limit=0,seed_paid=14,
                remaining=20,counter_cycle=True,manual=True,rerun_limits=(750,0,750))
        self.assertIsNone(error)
        self.assertEqual([(f,p) for f,p,_ in d.runs],[(1,0),(1,1),(1,1),(1,1)])
        self.assertEqual(d.saved['donation_paid'],15)


if __name__=='__main__':unittest.main()
