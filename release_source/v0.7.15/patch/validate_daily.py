"""Daily scheduling, durable checkpoints and guarded route regression tests."""
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import Mock,patch
import numpy as np
from collector import Halt
from daily_state import DailyLedger,DailySchedule,KST,korea_day,seconds_to_midnight
from daily_actions import DailyActions,SWEEP_DUNGEONS,DUNGEONS
from daily_vision import DailyVision,classify
from vision import Screen,Match

class Clock:
    def __init__(self):self.tick=0;self.start=datetime(2026,9,20,23,59,tzinfo=KST)
    def wall(self):return self.start+timedelta(seconds=self.tick)
    def clock(self):return self.tick

class StateTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'daily.json'
    def tearDown(self):self.tmp.cleanup()
    def test_fixed_kst_midnight_on_utc_machine(self):
        a=datetime(2026,9,20,14,59,59,tzinfo=timezone.utc)
        self.assertEqual(korea_day(a),'2026-09-20');self.assertEqual(korea_day(a+timedelta(seconds=1)),'2026-09-21')
        self.assertEqual(seconds_to_midnight(a),1)
    def test_completion_survives_restart_and_separates_instances(self):
        a=DailyLedger(self.path);a.mark('vm1','daily_pass',day='2026-09-20')
        b=DailyLedger(self.path)
        self.assertTrue(b.done('vm1','daily_pass',day='2026-09-20'))
        self.assertFalse(b.done('vm2','daily_pass',day='2026-09-20'))
        self.assertFalse(b.done('vm1','daily_pass',day='2026-09-21'))
    def test_partial_and_inflight_are_not_task_completion(self):
        a=DailyLedger(self.path);a.mark('vm1','daily_guild','donation');a.mark('vm1','daily_guild','raid','started')
        b=DailyLedger(self.path);self.assertTrue(b.done('vm1','daily_guild','donation'))
        self.assertFalse(b.done('vm1','daily_guild'));self.assertFalse(b.done('vm1','daily_guild','raid'))
        self.assertEqual(b.get('vm1','daily_guild','raid'),'started')
    def test_bad_record_fails_closed(self):
        self.path.write_text('{broken')
        with self.assertRaises(Halt):DailyLedger(self.path)
    def test_failed_save_does_not_mark_memory_complete(self):
        a=DailyLedger(self.path)
        with patch.object(Path,'replace',side_effect=OSError('disk full')):
            with self.assertRaises(Halt):a.mark('vm1','daily_pass')
        self.assertFalse(a.done('vm1','daily_pass'))
    def test_daily_only_sleeps_until_midnight(self):
        c=Clock();s=DailySchedule(['daily_pass'],3600,c.clock,c.wall)
        self.assertEqual(s.next(),(0,['daily_pass'],False));s.complete(['daily_pass'],{'daily_pass':'collected'},False,0)
        self.assertEqual(s.next()[0],60)
        c.tick=59;self.assertEqual(s.next()[0],60)
        c.tick=60;self.assertEqual(s.next(),(0,['daily_pass'],False))
    def test_mixed_tasks_get_midnight_before_hourly(self):
        c=Clock();s=DailySchedule(['farm','daily_pass'],3600,c.clock,c.wall)
        self.assertEqual(s.next()[1],['farm','daily_pass']);s.complete(['farm','daily_pass'],{'farm':'collected','daily_pass':'collected'},False,0)
        self.assertEqual(s.next()[1],['daily_pass']);c.tick=60;s.next();s.complete(['daily_pass'],{'daily_pass':'collected'},False,60)
        self.assertEqual(s.next(),(3600,['farm'],False))
    def test_daily_failures_retry_only_twice(self):
        c=Clock();c.start=c.start.replace(hour=12,minute=0)
        s=DailySchedule(['daily_pass','daily_guild'],3600,c.clock,c.wall)
        for i in range(3):
            due,rooms,retry=s.next();c.tick=due
            self.assertEqual(rooms,['daily_pass','daily_guild'] if i==0 else ['daily_guild'])
            s.complete(rooms,{'daily_pass':'collected','daily_guild':'failed'},retry,c.tick)
        self.assertEqual(s.next()[0],43200)
    def test_midnight_during_execution_does_not_complete_new_day(self):
        c=Clock();s=DailySchedule(['daily_pass'],3600,c.clock,c.wall);s.next();c.tick=61
        s.complete(['daily_pass'],{'daily_pass':'failed'},False,61)
        self.assertEqual(s.next(),(0,['daily_pass'],False))

class VisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.vision=DailyVision(Path(__file__).parent/'assets')
    def frame(self,*names):
        im=np.full((540,960,3),110,np.uint8)
        for name in names:
            s=self.vision.specs[name];x,y,r,b=s['box'];im[y:b,x:r]=self.vision.templates[name][0]
        return im
    def test_exact_two_sweeps_and_five_entries(self):
        self.assertEqual(SWEEP_DUNGEONS,{'equipment','summon'});self.assertEqual(len(set(DUNGEONS)-SWEEP_DUNGEONS),5)
    def test_different_free_counts_are_not_confused(self):
        for count in (0,1):
            state,matches=self.vision.recognize(self.frame('room_stone','d_close','d_count_0','d_free_'+str(count)))
            self.assertEqual(state,'daily_room_stone');self.assertIn('daily_d_free_'+str(count),matches)
            self.assertNotIn('daily_d_free_'+str(1-count),matches)
    def test_numeric_zero_aliases_agree(self):
        for name in ('d_count_0','rune_zero','relic_zero'):
            _,m=self.vision.recognize(self.frame(name));self.assertIn('daily_d_count_0',m)
    def test_pass_active_and_completed_are_distinct(self):
        for value in ('active','done'):
            state,m=self.vision.recognize(self.frame('pass_title','pass_ad','pass_ad_'+value))
            self.assertEqual(state,'daily_pass_ad');self.assertIn('daily_pass_ad_'+value,m)
            self.assertNotIn('daily_pass_ad_'+('done' if value=='active' else 'active'),m)
    def test_partial_dialog_never_identifies_an_action_page(self):
        for name in ('sweep_title','donate_title','relic_title','room_stone'):
            self.assertIsNone(classify({name}))
    def test_black_transition_has_no_daily_action(self):
        state,m=self.vision.recognize(np.zeros((540,960,3),np.uint8));self.assertIsNone(state);self.assertEqual(m,{})

class GuardTests(unittest.TestCase):
    def collector(self):
        c=DailyActions();c.daily_day=korea_day();c.device=Mock();c.pause=Mock()
        return c
    def screen(self,state,*keys):return Screen(state,{'daily_'+k:Match('daily_'+k,1,0,(480,380)) for k in keys})
    def test_changed_page_blocks_click(self):
        c=self.collector();s=self.screen('daily_sweep','sweep_action');c.screen=Mock(return_value=self.screen('unknown'))
        with self.assertRaises(Halt):c.daily_tap(s,'sweep_action')
        c.device.click.assert_not_called()
    def test_disappearing_button_blocks_click(self):
        c=self.collector();s=self.screen('daily_sweep','sweep_action');c.screen=Mock(return_value=self.screen('daily_sweep'))
        with self.assertRaises(Halt):c.daily_tap(s,'sweep_action')
        c.device.click.assert_not_called()
    def test_midnight_blocks_old_day_input(self):
        c=self.collector();c.daily_day='2000-01-01';s=self.screen('daily_sweep','sweep_action');c.screen=Mock(return_value=s)
        with self.assertRaises(Halt):c.daily_tap(s,'sweep_action')
        c.device.click.assert_not_called()

if __name__=='__main__':unittest.main()
