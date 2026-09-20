import unittest
from ui_state import player_summary,visible_players,task_summary,remaining_text,validate_profile,selected_tasks


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
    def test_empty_selection_cannot_be_enabled(self):
        with self.assertRaises(ValueError):validate_profile({'enabled':True,'minutes':60,'selected':{},'restore_sleep':True})
    def test_invalid_intervals_rejected(self):
        for value in ['0','1441','nan','inf','abc']:
            with self.subTest(value=value),self.assertRaises(ValueError):
                validate_profile({'enabled':True,'minutes':value,'selected':{'farm':True},'restore_sleep':True})
    def test_existing_optional_tasks_never_enabled_by_ui_defaults(self):
        self.assertNotIn('training',selected_tasks({'selected':{'farm':True}}))
        self.assertEqual(remaining_text(3700,100),'01:00:00')
        self.assertEqual(remaining_text(None,100),'예약 없음')

if __name__=='__main__':unittest.main()
