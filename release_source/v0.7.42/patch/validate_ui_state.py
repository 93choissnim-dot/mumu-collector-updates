import unittest
from ui_state import player_summary,visible_players,task_summary,remaining_text,validate_profile,selected_tasks,task_display_order,short_time


class UIStateTests(unittest.TestCase):
    def player(self):return {'name':'본캐','enabled':True,'minutes':60,'selected':{'farm':True,'training':False}}
    def state(self,state=None,**changes):
        args={'connected':True,'busy':False,'paused':False,'now':100};args.update(changes)
        return player_summary(self.player(),state or {},**args)
    def test_unknown_is_not_reported_as_complete(self):
        self.assertEqual(task_summary('farm',None),('기록 없음','muted'))
        self.assertEqual(task_summary('farm','attempted'),('완료 미확인','warning'))
        self.assertEqual(task_summary('training','skipped'),('조건 미충족','muted'))
    def test_task_progress_counts_results_not_imagined_steps(self):
        s=self.state({'status':'수령 중','rooms':['farm','ranking','training'],'results':{'farm':'collected'}},busy=True)
        self.assertEqual((s['completed'],s['total'],s['status']),(1,3,'수령 중'))
    def test_errors_and_disconnected_players_are_visible(self):
        self.assertTrue(self.state({'results':{'farm':'failed'}})['issue'])
        self.assertEqual(self.state(connected=False)['status'],'연결 미확인')
    def test_pause_keeps_reservation_without_making_success(self):
        s=self.state({'next_at':200},busy=True,paused=True)
        self.assertEqual(s['status'],'일시중지');self.assertEqual(s['next'],'일시중지')
        self.assertEqual(s['completed'],0)
    def test_filters_preserve_identity_and_input_order(self):
        players={'b':self.player(),'a':{**self.player(),'name':'부캐','enabled':False}}
        summaries={'b':self.state(),'a':self.state(connected=False)}
        self.assertEqual(visible_players(players,summaries,'본'),['b'])
        self.assertEqual(visible_players(players,summaries,mode='실행 대상'),['b'])
        self.assertEqual(visible_players(players,summaries,mode='확인 필요'),['a'])
    def test_issue_priority_is_display_only(self):
        import copy
        from task_catalog import TASK_LABELS
        p={'selected':{'farm':True,'wood':True,'mine':True,'ranking':True,'worldboss':True}}
        entries={'farm':{'result':'collected'},'wood':{'result':'failed'},'ranking':{'result':'attempted'},'worldboss':{'result':'deferred'},'daily_pass':{'result':'failed'}}
        saved=copy.deepcopy((p,entries));execution=selected_tasks(p)
        self.assertEqual(task_display_order(p,entries),['wood','ranking','worldboss','daily_pass','mine','farm'])
        self.assertEqual(selected_tasks(p),execution)
        self.assertEqual((p,entries),saved)
        expanded=task_display_order(p,entries,True)
        self.assertEqual(expanded[:6],task_display_order(p,entries))
        self.assertEqual(set(expanded),set(TASK_LABELS)-{'daily_dungeons','daily_guild'})
    def test_already_done_and_no_entries_are_not_prioritized_as_issues(self):
        p={'selected':{'daily_pass':True,'daily_dungeons':True,'daily_guild':True,'farm':True}}
        entries={'daily_pass':{'result':'already_complete'},'daily_dungeons':{'result':'no_entries'},'daily_guild':{'result':'already_claimed'}}
        self.assertEqual(task_display_order(p,entries),['farm','daily_pass','daily_dungeons','daily_guild'])
        self.assertEqual(task_display_order({'selected':{}},entries),list(entries))
    def test_empty_history_slots_do_not_show_unrun_manual_tasks(self):
        from task_catalog import TASK_LABELS
        entries={task:{} for task in TASK_LABELS}
        self.assertEqual(task_display_order(self.player(),entries),['farm'])
        entries['daily_pass']={'active':True}
        self.assertEqual(task_display_order(self.player(),entries),['farm','daily_pass'])
    def test_display_timestamps_use_the_same_kst_clock(self):
        self.assertEqual(short_time('2026-09-20T08:20:00+00:00'),short_time('2026-09-20T17:20:00+09:00'))
        self.assertEqual(short_time('2026-09-21T16:01:00+00:00'),'09/22 01:01')
        self.assertEqual(short_time(None),'기록 없음')
    def test_daily_only_target_can_be_enabled(self):
        self.assertTrue(validate_profile({'enabled':True,'minutes':60,'selected':{},'restore_sleep':True})['enabled'])
    def test_invalid_intervals_rejected(self):
        for value in ['0','1441','nan','inf','abc']:
            with self.subTest(value=value),self.assertRaises(ValueError):
                validate_profile({'enabled':True,'minutes':value,'selected':{'farm':True},'restore_sleep':True})
    def test_existing_optional_tasks_never_enabled_by_ui_defaults(self):
        self.assertNotIn('training',selected_tasks({'selected':{'farm':True}}))
        self.assertEqual(remaining_text(3700,100),'01:00:00')
        self.assertEqual(remaining_text(None,100),'예약 없음')

if __name__=='__main__':unittest.main()
