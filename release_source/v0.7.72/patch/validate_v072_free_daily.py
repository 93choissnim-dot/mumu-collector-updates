"""Recorded free-only controls and durable input boundary regressions."""
import unittest
from pathlib import Path
from vision import Vision
from task_catalog import DAILY_LABELS
from daily_state import DAILY_STEPS,DailySchedule

class RegistrationTests(unittest.TestCase):
    def test_new_tasks_are_scheduled_as_daily_not_hourly(self):
        self.assertIn('daily_summon',DAILY_LABELS)
        self.assertIn('daily_store',DAILY_LABELS)
        self.assertEqual(DAILY_STEPS['daily_summon'],('character','skill','pet'))
        self.assertEqual(DAILY_STEPS['daily_store'],('ruby','ruby_ad','cube_ad'))
        s=DailySchedule(['daily_summon','daily_store'],60,lambda:0)
        self.assertEqual(s.next()[1],['daily_summon','daily_store'])

class RecognitionTests(unittest.TestCase):
    def test_free_control_recognizer_is_connected_to_live_vision(self):
        self.assertIsNotNone(getattr(Vision(),'free_daily',None),'new free controls are not recognized')

class RecordedFramesTests(unittest.TestCase):
    def test_recorded_pages_counts_and_free_dialogs(self):
        import cv2,json,numpy as np
        v=Vision(); root=Path(__file__).parent/'assets'
        for name,case in json.loads((root/'free_daily_cases.json').read_text()).items():
            with self.subTest(name=name):
                frame=cv2.imdecode(np.fromfile(root/('free_daily_fixture_'+name+'.png'),np.uint8),1)
                s=v.recognize(frame)
                self.assertEqual(s.state,case['state'])
                if case['count'] is not None:self.assertIn('daily_free_count_'+str(case['count']),s.matches)


class RouteHarness:
    def make(self,task,step,states,*,stuck=False,fail_save=False):
        import tempfile,threading,numpy as np
        from extra_collector import ExtraCollector
        from daily_state import DailyLedger,korea_day
        from vision import Screen,Match
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        class Device:
            index=0;clock=0;clicks=[]
            def capture(d):d.clock+=.1;return np.full((540,960,3),d.index,np.uint8)
            def click(d,point):
                d.clicks.append((d.index,point))
                if not stuck:d.index=min(d.index+1,len(states)-1)
            def drag(d,a,b):raise AssertionError('unexpected scroll')
        class Observer:
            def recognize(v,im):return states[int(im[0,0,0])]
        d=Device();d.clicks=[];c=ExtraCollector(d,Observer(),threading.Event(),lambda _:None)
        c.now=lambda:d.clock;c.pause=lambda n:setattr(d,'clock',d.clock+n)
        c.daily_ledger=DailyLedger(Path(t.name)/'daily.json');c.daily_ident='account';c.daily_day=korea_day();c.daily_task=task;c.daily_step=step;c.daily_reward_seen=False;c.daily_performed=False
        if fail_save:
            from unittest.mock import patch
            self.addCleanup(patch.stopall);patch('record_storage.save_json',side_effect=OSError('disk')).start()
        return c,d
    def screen(self,state,count=None,**keys):
        from vision import Screen,Match
        m={'daily_free_'+k:Match('daily_free_'+k,1,0,p) for k,p in keys.items()}
        if count is not None:m['daily_free_count_'+str(count)]=Match('daily_free_count_'+str(count),1,0,(299,499))
        return Screen(state,m)
class RouteSafetyTests(RouteHarness,unittest.TestCase):
    def test_summons_spend_two_free_attempts_then_stop(self):
        self.assertTrue(hasattr(__import__('extra_collector').ExtraCollector,'free_summon_step'),'summon route missing')
        s=self.screen
        c,d=self.make('daily_summon','character',[
            s('free_summon_character',2,summon=(230,500),identity_character=(840,125)),
            s('free_summon_result_character',1,result_close=(370,495)),
            s('free_summon_character',1,summon=(230,500),identity_character=(840,125)),
            s('free_summon_result_character',0,result_close=(370,495)),
            s('free_summon_character',0,identity_character=(840,125))])
        c.free_summon_step('character')
        self.assertEqual([p for _,p in d.clicks],[(230,500),(370,495),(230,500),(370,495)])
        self.assertTrue(c.daily_done('character'));self.assertFalse(c.daily_detail().get('pending'))
    def test_unchanged_count_after_input_never_repeats(self):
        from collector import Halt
        self.assertTrue(hasattr(__import__('extra_collector').ExtraCollector,'free_summon_step'))
        c,d=self.make('daily_summon','character',[self.screen('free_summon_character',2,summon=(230,500),identity_character=(840,125))],stuck=True)
        with self.assertRaises(Halt):c.free_summon_step('character')
        self.assertEqual(len(d.clicks),1);self.assertTrue(c.daily_detail().get('pending'));self.assertFalse(c.daily_done('character'))
    def test_old_pending_same_count_is_not_replayed(self):
        from collector import Halt
        self.assertTrue(hasattr(__import__('extra_collector').ExtraCollector,'free_summon_step'))
        c,d=self.make('daily_summon','character',[self.screen('free_summon_character',1,summon=(230,500),identity_character=(840,125))])
        c.daily_checkpoint('uncertain',pending='free_summon',before_count=1)
        with self.assertRaises(Halt):c.free_summon_step('character')
        self.assertEqual(d.clicks,[])

class StoreSafetyTests(RouteHarness,unittest.TestCase):
    def test_confirmed_reward_marks_only_this_store_item(self):
        from vision import Screen,Match
        c,d=self.make('daily_store','ruby',[
            self.screen('free_store_confirm_ruby',confirm_ruby=(480,387),dialog_close=(631,86)),
            Screen('reward',{'reward_close':Match('reward_close',1,0,(640,520))}),
            self.screen('free_store',home=(919,28))])
        c.free_store_step('ruby')
        self.assertEqual([p for _,p in d.clicks],[(480,387),(640,520)])
        self.assertTrue(c.daily_done('ruby'));self.assertFalse(c.daily_done('ruby_ad'))
    def test_missing_reward_preserves_pending_and_never_repeats(self):
        from collector import Halt
        c,d=self.make('daily_store','ruby',[
            self.screen('free_store_confirm_ruby',confirm_ruby=(480,387),dialog_close=(631,86)),
            self.screen('free_store',home=(919,28))])
        with self.assertRaises(Halt):c.free_store_step('ruby')
        self.assertEqual(len(d.clicks),1);self.assertTrue(c.daily_detail().get('pending'));self.assertFalse(c.daily_done('ruby'))
    def test_paid_or_missing_button_never_dispatches(self):
        from collector import Halt
        c,d=self.make('daily_store','ruby',[self.screen('free_store_confirm_ruby',dialog_close=(631,86))])
        with self.assertRaises(Halt):c.free_store_step('ruby')
        self.assertEqual(d.clicks,[])
    def test_save_failure_precedes_every_free_input(self):
        from unittest.mock import patch
        from collector import Halt
        c,d=self.make('daily_store','ruby',[self.screen('free_store_confirm_ruby',confirm_ruby=(480,387),dialog_close=(631,86))])
        with patch('daily_state.save_json',side_effect=OSError('disk full')),self.assertRaises(Halt):c.free_store_step('ruby')
        self.assertEqual(d.clicks,[])

class NegativeRecognitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.v=Vision()
    def read(self,name):
        import cv2,numpy as np
        return cv2.imdecode(np.fromfile(Path(__file__).parent/'assets'/('free_daily_fixture_'+name+'.png'),np.uint8),1)
    def test_unreadable_summon_numerator_cannot_spend_or_complete(self):
        im=self.read('char_two');im[486:511,279:296]=0
        s=self.v.recognize(im)
        self.assertNotIn('daily_free_summon',s.matches)
        self.assertFalse(any('free_count_' in n for n in s.matches))
    def test_paid_store_cards_never_become_free(self):
        s=self.v.recognize(self.read('cube_claimed'))
        self.assertFalse(any('free_open_' in n or 'free_confirm_' in n for n in s.matches))
    def test_modal_without_literal_free_cannot_confirm(self):
        for name in ('ruby_modal','ruby_ad_modal','cube_modal'):
            with self.subTest(name=name):
                im=self.read(name);im[347:432,385:578]=0
                s=self.v.recognize(im)
                self.assertFalse(any('free_confirm_' in n for n in s.matches))
    def test_exhausted_summon_never_exposes_free_action(self):
        for name in ('char_zero_result','skill_zero_result','pet_zero_result'):
            s=self.v.recognize(self.read(name));self.assertNotIn('daily_free_summon',s.matches)


class AdditionalBoundaries(RouteHarness,unittest.TestCase):
    def test_changed_counter_before_reservation_sends_nothing(self):
        c,d=self.make('daily_summon','character',[self.screen('free_summon_character',1,summon=(230,500),identity_character=(840,125))])
        stale=self.screen('free_summon_character',2,summon=(230,500),identity_character=(840,125))
        self.assertFalse(c.free_commit(stale,'summon',2,required=('free_count_2','free_identity_character')))
        self.assertEqual(d.clicks,[]);self.assertFalse(c.daily_detail().get('pending'))
    def test_new_day_stops_free_work_even_manual_ledger(self):
        from unittest.mock import patch
        from collector import Halt
        c,d=self.make('daily_summon','character',[self.screen('free_summon_character',2,summon=(230,500),identity_character=(840,125))])
        with patch('free_daily_actions.korea_day',return_value='2099-01-01'),self.assertRaises(Halt):c.free_summon_step('character')
        self.assertEqual(d.clicks,[])
    def test_zero_after_restart_resolves_pending_without_spending(self):
        c,d=self.make('daily_summon','character',[self.screen('free_summon_character',0,identity_character=(840,125))])
        c.daily_checkpoint('uncertain',pending='free_summon',before_count=1)
        c.free_summon_step('character')
        self.assertEqual(d.clicks,[]);self.assertTrue(c.daily_done('character'));self.assertFalse(c.daily_detail().get('pending'))

class SelectionTests(unittest.TestCase):
    def test_update_adds_new_free_tasks_but_preserves_explicit_opt_out(self):
        from session_workflow import selected_daily
        self.assertEqual(selected_daily({'daily_selected':{}}),[])
        self.assertEqual(selected_daily({'daily_selected':{'daily_pass':True}}),['daily_store','daily_summon','daily_pass'])
        self.assertEqual(selected_daily({'daily_selected':{'daily_pass':True,'daily_store':False,'daily_summon':False}}),['daily_pass'])


class FinalInputBoundaryTests(RouteHarness,unittest.TestCase):
    def test_midnight_after_reservation_never_dispatches_manual_input(self):
        from unittest.mock import patch
        from collector import Halt
        c,d=self.make('daily_store','ruby',[self.screen('free_store_confirm_ruby',confirm_ruby=(480,387),dialog_close=(631,86))])
        c.daily_ledger.manual=True;original=c.daily_checkpoint;rolled=[False]
        def checkpoint(*a,**kw):
            original(*a,**kw);rolled[0]=True
        c.daily_checkpoint=checkpoint
        with patch('free_daily_actions.korea_day',side_effect=lambda:'2099-01-01' if rolled[0] else c.daily_day),self.assertRaises(Halt):
            c.free_commit(c.screen(),'confirm_ruby')
        self.assertEqual(d.clicks,[])
        self.assertTrue(c.daily_detail().get('pending'))

class ActionableCardTests(unittest.TestCase):
    setUpClass=classmethod(NegativeRecognitionTests.setUpClass.__func__)
    read=NegativeRecognitionTests.read
    def test_ad_ruby_card_is_actionable_only_as_ad_ruby(self):
        s=self.v.recognize(self.read('ruby_ad_card'))
        self.assertIn('daily_free_open_ruby_ad',s.matches)
        self.assertNotIn('daily_free_open_ruby',s.matches)
    def test_plain_ruby_and_cube_each_keep_their_own_identity(self):
        self.assertIn('daily_free_open_ruby',self.v.recognize(self.read('ruby_card')).matches)
        self.assertIn('daily_free_open_cube_ad',self.v.recognize(self.read('cube_card')).matches)

class DelayedStoreRewardTests(RouteHarness,unittest.TestCase):
    def test_list_can_reappear_before_reward_animation(self):
        from vision import Screen,Match
        c,d=self.make('daily_store','ruby',[
            self.screen('free_store_confirm_ruby',confirm_ruby=(480,387),dialog_close=(631,86)),
            self.screen('free_store',home=(919,28)),
            Screen('reward',{'reward_close':Match('reward_close',1,0,(640,520))}),
            self.screen('free_store',home=(919,28))])
        capture=d.capture
        def delayed():
            if d.index==1 and d.clock>=3:d.index=2
            return capture()
        d.capture=delayed
        c.free_store_step('ruby')
        self.assertTrue(c.daily_done('ruby'));self.assertFalse(c.daily_detail().get('pending'))
        self.assertEqual([p for _,p in d.clicks],[(480,387),(640,520)])

if __name__=='__main__':unittest.main()
