"""Explicit RED RUBY budgets govern real donation routes and persisted retries."""
import unittest
import validate_v065_donation as donation_cases
from session_workflow import selected_daily


class SpendingTests(unittest.TestCase):
    def route(self,**kwargs):return donation_cases.GuildDonationTests().route(**kwargs)

    def test_missing_budget_preserves_free_and_excludes_paid(self):
        d,done,error=self.route(paid_limit=None)
        self.assertIsNone(error);self.assertTrue(done)
        self.assertEqual((d.free_clicks,d.paid,d.left),(1,0,2))
        self.assertTrue(d.detail.get('policy_excluded'))

    def test_manual_run_cannot_spend_after_its_kst_day_changes(self):
        d,done,error=self.route(paid_limit=50,free=False,manual=True,stale_day=True)
        self.assertEqual(d.paid,0)
        self.assertIsNotNone(error)

    def test_manual_midnight_during_reservation_cannot_dispatch(self):
        from unittest.mock import patch
        from daily_state import ManualQuestLedger,korea_day
        day=[korea_day()];origin=day[0]
        checkpoint=ManualQuestLedger.checkpoint
        def rollover(ledger,*args,**kwargs):
            result=checkpoint(ledger,*args,**kwargs)
            if kwargs.get('pending')=='donate_50':day[0]='2999-01-01'
            return result
        with patch('daily_actions.korea_day',side_effect=lambda:day[0]),patch.object(ManualQuestLedger,'checkpoint',rollover):
            d,done,error=self.route(paid_limit=50,free=False,manual=True)
        self.assertEqual(d.paid,0);self.assertFalse(done);self.assertIsNotNone(error)
        self.assertEqual(d.saved['donation_day'],origin)
        self.assertEqual(d.saved['donation_paid'],1)
        self.assertEqual(d.detail.get('pending'),'donate_50')

    def test_manual_midnight_during_final_capture_cannot_dispatch(self):
        from unittest.mock import patch
        from daily_state import korea_day
        from extra_collector import ExtraCollector
        day=[korea_day()];screen=ExtraCollector.screen
        def rollover(collector,*args,**kwargs):
            result=screen(collector,*args,**kwargs)
            if collector.daily_detail().get('pending')=='donate_50':day[0]='2999-01-01'
            return result
        with patch('daily_actions.korea_day',side_effect=lambda:day[0]),patch.object(ExtraCollector,'screen',rollover):
            d,done,error=self.route(paid_limit=50,free=False,manual=True)
        self.assertEqual(d.paid,0);self.assertFalse(done);self.assertIsNotNone(error)
        self.assertEqual(d.detail.get('pending'),'donate_50')

    def test_manual_same_day_rerun_retains_cap_usage(self):
        d,done,error=self.route(paid_limit=50,manual=True,remaining=5,rerun_limits=(50,100))
        self.assertIsNone(error)
        self.assertEqual([(f,p) for f,p,_ in d.runs],[(1,1),(1,1),(1,2)])

    def test_zero_budget_sends_no_paid_input(self):
        d,done,error=self.route(paid_limit=0,free=False)
        self.assertIsNone(error);self.assertTrue(done);self.assertEqual(d.paid,0)

    def test_maximum_budget_finishes_policy_after_free_plus_fifteen_paid(self):
        d,done,error=self.route(paid_limit=750,remaining=20,counter_cycle=True)
        self.assertIsNone(error);self.assertTrue(done)
        self.assertEqual((d.free_clicks,d.paid),(1,15))
        self.assertTrue(d.detail.get('policy_excluded'))

    def test_exact_budget_counts_prior_durable_attempts(self):
        d,done,error=self.route(paid_limit=100,seed_paid=1,free=False,remaining=5)
        self.assertIsNone(error);self.assertTrue(done);self.assertEqual(d.paid,1)
        self.assertEqual(d.saved['donation_paid'],2)
        self.assertTrue(d.detail.get('policy_excluded'))

    def test_budget_is_fail_closed_for_invalid_values(self):
        for value in (-50,25,800,True,'50',50.0):
            with self.subTest(value=value):
                d,done,error=self.route(paid_limit=value,free=False)
                self.assertEqual(d.paid,0)

    def test_increase_reopens_policy_exclusion_without_replaying_free(self):
        d,done,error=self.route(paid_limit=0,rerun_limits=(50,100),remaining=5)
        self.assertIsNone(error);self.assertTrue(done)
        self.assertEqual([(f,p) for f,p,_ in d.runs],[(1,0),(1,1),(1,2)])
        self.assertEqual(d.saved['donation_paid'],2)

    def test_confirmed_free_is_not_replayed_if_stale_free_button_returns(self):
        d,done,error=self.route(paid_limit=0,rerun_limits=(50,),stale_free=True)
        self.assertEqual((d.free_clicks,d.paid),(1,0))

    def test_unchanged_or_lower_budget_does_not_reopen(self):
        d,done,error=self.route(paid_limit=50,rerun_limits=(50,0),remaining=5)
        self.assertIsNone(error);self.assertEqual(d.paid,1)
        self.assertEqual([(f,p) for f,p,_ in d.runs],[(1,1),(1,1),(1,1)])

    def test_pending_payment_never_replayed_even_after_cap_increase(self):
        d,done,error=self.route(paid_limit=750,pending=True,free=False)
        self.assertEqual(d.paid,0);self.assertEqual(d.detail.get('pending'),'donate_50')

    def test_game_exhausted_is_distinct_and_not_reopened(self):
        d,done,error=self.route(paid_limit=0,remaining=1,rerun_limits=(100,))
        self.assertIsNone(error);self.assertTrue(done);self.assertEqual(d.paid,0)
        self.assertFalse(d.detail.get('policy_excluded'))

    def test_old_free_only_completion_stays_excluded_at_zero(self):
        d,done,error=self.route(paid_limit=0,free=False,old_excluded=True)
        self.assertIsNone(error);self.assertEqual(d.paid,0)


class NormalizeBudgetTests(unittest.TestCase):
    def test_settings_normalization_accepts_explicit_decimal_amounts(self):
        import spending_policy
        self.assertTrue(callable(getattr(spending_policy,'normalize_paid_limit',None)))
        normalize=spending_policy.normalize_paid_limit
        self.assertEqual([normalize(v) for v in (0,750,'50',' 100 ')],[0,750,50,100])
        for value in (True,50.0,'50.0','nan','-50',25,None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):normalize(value)


class SelectionTests(unittest.TestCase):
    def test_missing_selection_defaults_only_free_tasks(self):
        self.assertEqual(selected_daily({}),['daily_store','daily_summon'])
    def test_explicit_selection_preserved(self):
        self.assertEqual(selected_daily({'daily_selected':{'daily_store':False,'daily_summon':False,'daily_guild':True}}),['daily_guild'])
        self.assertEqual(selected_daily({'daily_selected':{}}),[])

class ManualBudgetTests(unittest.TestCase):
    def test_new_run_retains_today_attempts_and_confirmed_free(self):
        from pathlib import Path
        import tempfile
        from daily_state import ManualQuestLedger,korea_day
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'manual.json';ledger=ManualQuestLedger(path)
            ledger.update('a','daily_guild',{'donation_day':korea_day(),'donation_paid':2,'donation_verified':1,'donation_free_confirmed':True})
            ledger.checkpoint('a','daily_guild','donation','done',values={'donation':'done'},policy_excluded=True,excluded=True)
            ledger.begin_run('a',tasks=['daily_guild']);ledger=ManualQuestLedger(path)
            self.assertEqual(ledger.get('a','daily_guild','donation_paid'),2)
            self.assertTrue(ledger.get('a','daily_guild','donation_free_confirmed'))
            self.assertTrue(ledger.detail('a','daily_guild','donation').get('policy_excluded'))

    def test_unknown_legacy_counter_kept_conservatively_for_today(self):
        from pathlib import Path
        import tempfile
        from daily_state import ManualQuestLedger,korea_day
        with tempfile.TemporaryDirectory() as tmp:
            ledger=ManualQuestLedger(Path(tmp)/'manual.json')
            ledger.update('a','daily_guild',{'donation_paid':3})
            ledger.begin_run('a',tasks=['daily_guild'])
            self.assertEqual(ledger.get('a','daily_guild','donation_paid'),3)
            self.assertEqual(ledger.get('a','daily_guild','donation_day'),korea_day())

    def test_new_kst_day_resets_only_confirmed_old_budget(self):
        from pathlib import Path
        import tempfile
        from daily_state import ManualQuestLedger
        with tempfile.TemporaryDirectory() as tmp:
            ledger=ManualQuestLedger(Path(tmp)/'manual.json')
            ledger.update('a','daily_guild',{'donation_day':'2000-01-01','donation_paid':3,'donation_free_confirmed':True})
            ledger.begin_run('a',tasks=['daily_guild'])
            self.assertIsNone(ledger.get('a','daily_guild','donation_paid'))
            self.assertFalse(ledger.get('a','daily_guild','donation_free_confirmed'))

    def test_old_day_pending_payment_and_spend_survive_new_run(self):
        from pathlib import Path
        import tempfile
        from daily_state import ManualQuestLedger
        with tempfile.TemporaryDirectory() as tmp:
            ledger=ManualQuestLedger(Path(tmp)/'manual.json')
            ledger.checkpoint('a','daily_guild','donation','uncertain',pending='donate_50',values={'donation_day':'2000-01-01','donation_paid':3})
            ledger.begin_run('a',tasks=['daily_guild'])
            self.assertEqual(ledger.get('a','daily_guild','donation_paid'),3)
            self.assertEqual(ledger.detail('a','daily_guild','donation')['pending'],'donate_50')

if __name__=='__main__':unittest.main()
