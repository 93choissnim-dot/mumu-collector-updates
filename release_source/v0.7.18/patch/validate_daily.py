"""Daily scheduling, durable checkpoints and guarded route regression tests."""
import tempfile
import threading
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import Mock,patch
import numpy as np
from collector import Halt
from daily_state import DailyLedger,DailySchedule,KST,korea_day,seconds_to_midnight
from daily_actions import DailyActions,SWEEP_DUNGEONS,DUNGEONS
from daily_vision import DailyVision,classify
from vision import Screen,Match,Vision,MAIN_MARKERS

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
    def native(self,im):
        return np.clip(im.astype(float)*[1.22065,1.17493,1.12426]+[22.12782,2.31765,-4.33370],0,255).astype(np.uint8)
    def test_native_color_guild_context_survives_absolute_color_shift(self):
        # Public reference images plus the independently measured color shift;
        # no user diagnostic capture is bundled or uploaded.
        im=self.native(self.frame('guild_title','guild_tabs','guild_menu','guild_donate_open'))
        state,m=self.vision.recognize(im)
        self.assertEqual(state,'daily_guild_menu');self.assertIn('daily_guild_donate_open',m)
        self.assertNotIn('daily_guild_attended',m);self.assertNotIn('daily_guild_donated',m)
        d=self.vision.diagnostics
        self.assertGreater(d['guild_tabs']['raw_mae'],18);self.assertLess(d['guild_tabs']['mae'],6)
        self.assertEqual(d['_exposure']['anchors'],['guild_title','guild_tabs'])
    def test_native_pass_claim_and_done_stay_distinct(self):
        for key in ('ad','keys','gear'):
            for value in ('active','done'):
                with self.subTest(key=key,value=value):
                    im=self.native(self.frame('pass_title','pass_tabs','pass_'+key,'pass_'+key+'_'+value))
                    state,m=self.vision.recognize(im)
                    self.assertEqual(state,'daily_pass_'+key);self.assertIn('daily_pass_'+key+'_'+value,m)
                    self.assertNotIn('daily_pass_'+key+'_'+('done' if value=='active' else 'active'),m)
    def test_native_free_key_counts_stay_distinct(self):
        for count in (0,1):
            im=self.native(self.frame('room_stone','d_close','d_count_0','d_free_'+str(count)))
            state,m=self.vision.recognize(im)
            self.assertEqual(state,'daily_room_stone');self.assertIn('daily_d_free_'+str(count),m)
            self.assertNotIn('daily_d_free_'+str(1-count),m)
    def test_reward_button_cannot_calibrate_its_own_exposure(self):
        im=self.frame('pass_title','pass_tabs','pass_ad','pass_ad_active')
        x,y,r,b=self.vision.specs['pass_ad_active']['box']
        im[y:b,x:r]=(im[y:b,x:r]*.5).astype(np.uint8)
        _,m=self.vision.recognize(im);self.assertNotIn('daily_pass_ad_active',m)
    def test_native_guild_remaining_attempts_stay_distinct(self):
        for count in range(4):
            im=self.native(self.frame('guild_dungeon_rank','guild_fight','guild_count_'+str(count)))
            state,m=self.vision.recognize(im);self.assertEqual(state,'daily_guild_dungeon')
            self.assertEqual([n for n in m if n.startswith('daily_guild_count_')],['daily_guild_count_'+str(count)])
    def test_native_relic_claim_and_empty_stay_distinct(self):
        for value in ('claim','empty'):
            im=self.native(self.frame('relic_title','relic_list','relic_close','relic_'+value))
            state,m=self.vision.recognize(im);self.assertEqual(state,'daily_relic')
            self.assertIn('daily_relic_'+value,m)
            self.assertNotIn('daily_relic_'+('empty' if value=='claim' else 'claim'),m)
    def test_dimmed_modal_background_is_not_calibrated(self):
        im=(self.frame('guild_title','guild_tabs','guild_menu')*.5).astype(np.uint8)
        state,_=self.vision.recognize(im);self.assertIsNone(state)
        self.assertEqual(self.vision.diagnostics['_exposure']['anchors'],[])

class BindingTests(unittest.TestCase):
    def test_daily_pages_rebind_only_to_verified_game(self):
        from validate_start_navigation import BindingTests as Setup
        from adb_device import DAILY_RECOVERY_STATES
        setup=Setup()
        for state in DAILY_RECOVERY_STATES:
            a,d,v=setup.device('com.nns.genesis',state);d.bind_game(v);self.assertEqual(d.package,'com.nns.genesis')
            a,d,v=setup.device('com.android.launcher',state)
            with self.assertRaises(Halt):d.bind_game(v)

class PassNavigationTests(unittest.TestCase):
    """An independent menu hit map: the event button never opens the pass."""
    @classmethod
    def setUpClass(cls):cls.vision=Vision()
    def run_route(self,wrong_entry=False):
        from extra_collector import ExtraCollector
        from validate_overlays import composite
        v=self.vision
        class Device:
            def __init__(self):self.page='main';self.done=set();self.clock=0;self.actions=[]
            def capture(self):
                self.clock+=.1
                if self.page=='main':return composite(v,*MAIN_MARKERS)
                im=np.full((540,960,3),110,np.uint8)
                if self.page=='event':return im
                key=self.page
                for name in ('pass_title','pass_'+key,'pass_'+key+('_done' if key in self.done else '_active')):
                    x,y,r,b=v.daily.specs[name]['box'];im[y:b,x:r]=v.daily.templates[name][0]
                return im
            def click(self,point):
                self.actions.append((self.page,point));x,y=point
                if self.page=='main':
                    if 790<=x<=839 and 3<=y<=53:self.page='ad'
                    elif 630<=x<=679 and 3<=y<=53:self.page='event'
                    else:raise AssertionError(('Unmapped menu input',point))
                elif self.page=='event':raise AssertionError('No input allowed on the event page')
                elif x>900 and y<50:self.page='main'
                elif x<140:self.page='ad' if y<110 else 'keys' if y<175 else 'gear'
                else:
                    assert self.page not in self.done
                    x1,y1,x2,y2=v.daily.specs['pass_'+self.page+'_active']['box']
                    assert x1<=x<=x2 and y1<=y<=y2
                    self.done.add(self.page)
        d=Device();c=ExtraCollector(d,v,threading.Event(),lambda _:None)
        c.now=lambda:d.clock;c.pause=lambda t:setattr(d,'clock',d.clock+t)
        with tempfile.TemporaryDirectory() as tmp:
            c.daily_ledger=DailyLedger(Path(tmp)/'daily.json');c.daily_ident='test'
            if wrong_entry:
                original=c.daily_tap
                def incorrect(screen,key=None,point=None):
                    if screen.state=='main' and point==(813,28):point=(652,30)
                    return original(screen,key,point)
                c.daily_tap=incorrect
                with self.assertRaises(Halt):c.collect_daily('daily_pass')
                self.assertEqual(d.page,'event');self.assertEqual(len(d.actions),1)
                self.assertFalse(c.daily_ledger.done('test','daily_pass'))
            else:
                self.assertEqual(c.collect_daily('daily_pass'),'collected')
                self.assertEqual(d.done,{'ad','keys','gear'});self.assertEqual(d.page,'main')
                self.assertEqual(d.actions[0],('main',(813,28)))
                before=len(d.actions);self.assertEqual(c.collect_daily('daily_pass'),'skipped')
                self.assertEqual(len(d.actions),before)
    def test_pass_icon_reaches_all_three_rewards_once(self):self.run_route()
    def test_old_event_coordinate_fails_and_never_marks_complete(self):self.run_route(wrong_entry=True)

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
    def test_navigation_survives_animated_icon_background(self):
        for key,point in [('pass',(813,28)),('dungeon',(509,505)),('guild',(563,505))]:
            c=self.collector();main=self.screen('main');c.daily_main=Mock(return_value=main)
            c.screen=Mock(return_value=main);c.daily_wait=Mock(return_value=self.screen('daily_'+key))
            c.daily_open(key,{'daily_'+key});c.device.click.assert_called_once_with(point)
    def test_navigation_blocks_new_overlay(self):
        c=self.collector();c.daily_main=Mock(return_value=self.screen('main'))
        c.screen=Mock(return_value=self.screen('exit_dialog'))
        with self.assertRaises(Halt):c.daily_open('pass',{'daily_pass_ad'})
        c.device.click.assert_not_called()

if __name__=='__main__':unittest.main()
