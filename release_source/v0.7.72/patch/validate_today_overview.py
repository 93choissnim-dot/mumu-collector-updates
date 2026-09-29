"""Read-only today/account boundaries and conservative donation reporting."""
import copy
import unittest


class TodayOverviewTests(unittest.TestCase):
    def setUp(self):
        self.day='2026-09-28'
        self.player={'name':'A','enabled':True,'selected':{'farm':True,'wood':True},
                     'daily_selected':{'daily_guild':True}}

    def report(self,record=None,daily=None,actions=None,player=None):
        from today_overview import account_overview
        return account_overview('a',player or self.player,record or {},daily or {},actions or {},self.day)

    def rows(self,report):return {row['task']:row for row in report['tasks']}

    def test_no_run_shows_all_selected_tasks_including_daily(self):
        rows=self.rows(self.report())
        self.assertEqual(set(rows),{'farm','wood','daily_guild','daily_store','daily_summon'})
        self.assertEqual({r['status'] for r in rows.values()},{'unrun'})

    def test_today_latest_result_and_stale_result_are_distinct(self):
        record={'day':self.day,'tasks':['farm','wood'],'results':{'farm':'collected','wood':'failed'}}
        rows=self.rows(self.report(record))
        self.assertEqual(rows['farm']['status'],'done')
        self.assertEqual(rows['wood']['status'],'partial')
        record['day']='2026-09-27'
        self.assertEqual({r['status'] for r in self.rows(self.report(record)).values()},{'unrun'})

    def test_partial_daily_uses_today_step_dates_only(self):
        daily={'daily_guild':{'attendance':'done','relic':'done','_steps':{
            'attendance':{'status':'done','updated_at':'2026-09-28T00:01:00+09:00'},
            'relic':{'status':'done','updated_at':'2026-09-27T23:00:00+09:00'}}}}
        row=self.rows(self.report(daily=daily))['daily_guild']
        self.assertEqual(row['status'],'partial');self.assertEqual(row['complete'],1)

    def test_pending_survives_stale_date_and_deselection_and_disabled_account(self):
        p=copy.deepcopy(self.player);p['daily_selected']={};p['enabled']=False
        daily={'daily_guild':{'_steps':{'donation':{'pending':'donate_50','status':'uncertain',
            'input_request':{'requested_at':'2026-09-27T13:00:00+09:00'}}}}}
        report=self.report(daily=daily,player=p);row=self.rows(report)['daily_guild']
        self.assertFalse(report['enabled']);self.assertFalse(row['selected'])
        self.assertEqual(row['status'],'uncertain');self.assertIn('donation',row['pending'])

    def test_pending_overrides_terminal_result_and_regular_block_is_held(self):
        record={'day':self.day,'tasks':['farm'],'results':{'farm':'collected'}}
        rows=self.rows(self.report(record,actions={'farm':{'pending':{'claim':{}}},'wood':{'blocked':True}}))
        self.assertEqual(rows['farm']['status'],'uncertain');self.assertEqual(rows['wood']['status'],'held')

    def test_account_profile_snapshot_uses_only_matching_scope(self):
        from today_overview import build_overview
        p=copy.deepcopy(self.player);p['daily_profile']='new'
        result=build_overview({'a':p},{'a':{'day':self.day,'tasks':['farm'],'results':{'farm':'collected'}}},{},{},self.day)
        self.assertEqual(self.rows(result['accounts'][0])['farm']['status'],'unrun')

    def test_prior_history_is_visible_but_never_overrides_new_run_waiting(self):
        from today_overview import account_overview
        history={'farm':{'checked_at':'2026-09-28T01:00:00+09:00','result':'collected'}}
        report=account_overview('a',self.player,{}, {},{},self.day,history)
        self.assertEqual(self.rows(report)['farm']['status'],'prior')
        report=account_overview('a',self.player,{'day':self.day,'tasks':['farm'],'results':{}},{},{},self.day,history)
        self.assertEqual(self.rows(report)['farm']['status'],'unrun')

    def test_resolved_retry_authorization_is_not_uncertain_without_pending(self):
        daily={'daily_guild':{'_steps':{'raid':{'status':'uncertain','pending':None,
            'input_resolution':{'kind':'retry_authorized','confirmed':False}}}}}
        self.assertEqual(self.rows(self.report(daily=daily))['daily_guild']['status'],'unrun')

    def test_dated_excluded_steps_are_complete_but_displayed_as_exclusions(self):
        p=copy.deepcopy(self.player);p['daily_selected']={'daily_pass':True}
        daily={'daily_pass':{'ad':'done','keys':'done','gear':'done','_steps':{
            s:{'status':'done','excluded':s!='ad','updated_at':'2026-09-28T01:00:00+09:00'} for s in ('ad','keys','gear')}}}
        row=self.rows(self.report(daily=daily,player=p))['daily_pass']
        self.assertEqual(row['status'],'done');self.assertEqual(row['excluded'],2)


class DonationReportTests(unittest.TestCase):
    day='2026-09-28'
    def pair(self,ident='one',action='donate_50',source='donation_counter_changed',stamp='2026-09-28T01:00:00+09:00'):
        return {'request':{'id':ident,'action':action,'requested_at':stamp},
                'resolution':{'at':stamp,'confirmed':True,'kind':'confirmed','source':source}}
    def report(self,record):
        from today_overview import donation_report
        return donation_report(record,self.day)

    def test_verified_pairs_count_spend_but_attempt_counter_and_pending_do_not(self):
        pair=self.pair()
        report=self.report({'donation_paid':9,'donation_verified':8,'_steps':{'donation':{
            'input_history':[pair,self.pair('free','donate_free')],
            'last_input':pair['request'],'input_resolution':pair['resolution'],
            'pending':'donate_50','input_request':{'id':'next','requested_at':'2026-09-28T02:00:00+09:00'}}}})
        self.assertEqual(report['paid_confirmed'],1);self.assertEqual(report['ruby_confirmed'],50)
        self.assertEqual(report['free_confirmed'],1);self.assertTrue(report['pending'])

    def test_already_completed_badge_and_manual_completion_never_infer_spend(self):
        pair=self.pair(source='screen_confirmed')
        manual=self.pair('manual');manual['resolution']['kind']='manual_resolution'
        report=self.report({'donation':'done','donation_paid':3,'_steps':{'donation':{
            'status':'done','updated_at':'2026-09-28T01:00:00+09:00','input_history':[pair,manual]}}})
        self.assertEqual(report['ruby_confirmed'],0);self.assertTrue(report['completed'])

    def test_kst_day_and_old_pending_are_preserved_without_counting_old_spend(self):
        report=self.report({'_steps':{'donation':{'input_history':[
            self.pair('today',stamp='2026-09-27T15:01:00+00:00'),
            self.pair('old',stamp='2026-09-27T14:59:00+00:00')],
            'pending':'donate_50','input_request':{'requested_at':'2026-09-27T14:59:00+00:00'}}}})
        self.assertEqual(report['ruby_confirmed'],50);self.assertTrue(report['pending'])

    def test_unknown_request_origin_does_not_prove_today_spend(self):
        pair=self.pair();pair['request'].pop('requested_at')
        report=self.report({'_steps':{'donation':{'input_history':[pair]}}})
        self.assertEqual(report['ruby_confirmed'],0)

    def test_stale_completed_badge_is_not_today_completion(self):
        report=self.report({'donation':'done','_steps':{'donation':{
            'status':'done','updated_at':'2026-09-27T01:00:00+09:00'}}})
        self.assertFalse(report['completed'])


if __name__=='__main__':unittest.main()
