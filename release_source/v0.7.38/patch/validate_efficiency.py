"""Safety boundaries and measured work budgets for the efficiency changes."""
import threading
import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock,patch
import numpy as np
from collector import Halt
from daily_state import korea_day
from extra_collector import ExtraCollector
from fleet_runner import run_fleet
from mumu_names import CatalogLookup
from run_control import RunControl
from vision import Screen,Match,Vision


def page(state,*keys):
    return Screen(state,{k:Match(k,1,0,(480,380)) for k in keys})


class ObservationTests(unittest.TestCase):
    def make(self,frames):
        clock=[0.];stop=RunControl(lambda:clock[0]);device=Mock()
        device.capture.return_value=np.zeros((540,960,3),np.uint8)
        vision=Mock();vision.recognize.side_effect=frames
        c=ExtraCollector(device,vision,stop,Mock());c.trace=Mock()
        c.now=lambda:clock[0];c.pause=lambda n:clock.__setitem__(0,clock[0]+n)
        c.daily_day=korea_day()
        return c,clock
    def test_page_and_button_share_pair_but_changed_fresh_frame_blocks_click(self):
        ready=page('daily_pass_ad','daily_pass_ad_active');done=page('daily_pass_ad','daily_pass_ad_done')
        c,_=self.make([ready,ready,done])
        c.daily_wait({'daily_pass_ad'})
        found=c.daily_ready({'daily_pass_ad'},['pass_ad_active','pass_ad_done'])
        self.assertEqual(c.device.capture.call_count,2)
        with self.assertRaises(Halt):c.daily_tap(found,'pass_ad_active')
        self.assertEqual(c.device.capture.call_count,3);c.device.click.assert_not_called()
    def test_input_invalidates_both_observations(self):
        ready=page('daily_pass_ad','daily_pass_ad_active')
        c,_=self.make([ready,ready,ready])
        found=c.daily_wait({'daily_pass_ad'});c.tap(found,'daily_pass_ad_active')
        self.assertEqual(c.confirmation_seed(lambda s:s.state)[1],0)
        c.device.click.assert_called_once()
    def test_expired_pair_requires_two_new_captures(self):
        ready=page('daily_shop','daily_shop_free');c,clock=self.make([ready]*4)
        c.daily_wait({'daily_shop'});clock[0]+=.8;c.daily_wait({'daily_shop'})
        self.assertEqual(c.device.capture.call_count,4)
    def test_pause_invalidates_pair_even_when_active_clock_is_frozen(self):
        ready=page('daily_shop');c,clock=self.make([ready]*4)
        c.daily_wait({'daily_shop'});c.stop.pause();clock[0]+=50;c.stop.resume()
        c.daily_wait({'daily_shop'});self.assertEqual(c.device.capture.call_count,4)
    def test_stop_and_midnight_cannot_return_cached_completion(self):
        ready=page('daily_shop');c,_=self.make([ready]*2);c.daily_wait({'daily_shop'})
        c.stop.set()
        with self.assertRaises(Halt):c.daily_wait({'daily_shop'})
        c.stop.clear();c.daily_day='2000-01-01'
        with self.assertRaises(Halt):c.daily_wait({'daily_shop'})
    def test_intervening_unknown_does_not_confirm_a_button(self):
        ready=page('daily_pass_ad','daily_pass_ad_active')
        c,_=self.make([ready,page('unknown'),ready,ready])
        c.daily_ready({'daily_pass_ad'},['pass_ad_active'])
        self.assertEqual(c.device.capture.call_count,4)
    def test_new_page_stable_pair_finishes_early_and_is_shared(self):
        ready=page('daily_pass_ad','daily_pass_ad_active');c,clock=self.make([ready,ready])
        c.post_input(page('main'),'top_pass')
        self.assertLess(clock[0],.65)
        c.daily_ready({'daily_pass_ad'},['pass_ad_active'])
        self.assertEqual(c.device.capture.call_count,2)
    def test_unchanged_page_and_button_retains_settle_delay(self):
        ready=page('daily_pass_ad','daily_pass_ad_active');c,clock=self.make([ready])
        c.post_input(ready,'daily_pass_ad_active')
        self.assertGreaterEqual(clock[0],.65)
    def test_transient_new_page_then_unknown_cannot_finish_early(self):
        c,clock=self.make([page('daily_shop'),page('unknown')])
        c.post_input(page('daily_guild_menu'),'daily_guild_shop_open')
        self.assertGreaterEqual(clock[0],.65)
    def test_button_change_requires_two_observations(self):
        done=page('daily_pass_ad','daily_pass_ad_done');c,clock=self.make([done,done])
        c.post_input(page('daily_pass_ad','daily_pass_ad_active'),'daily_pass_ad_active')
        self.assertEqual(c.device.capture.call_count,2);self.assertLess(clock[0],.65)
    def test_combat_entry_does_not_consume_result_frames(self):
        ready=page('daily_guild_dungeon','daily_guild_fight');c,_=self.make([ready])
        c.daily_tap(ready,'guild_fight')
        self.assertEqual(c.device.capture.call_count,1);c.device.click.assert_called_once()
    def test_guild_back_keeps_raid_in_same_guild_visit(self):
        dungeon=page('daily_guild_dungeon')
        c,_=self.make([]);c.daily_wait=Mock(side_effect=[dungeon,page('daily_guild_battle')])
        c.daily_tap=Mock();c.daily_guild_root=Mock()
        self.assertEqual(c.daily_guild_page(battle=True).state,'daily_guild_battle')
        c.daily_tap.assert_called_once_with(dungeon,point=(34,28))
        c.daily_guild_root.assert_not_called()


class RecognitionCostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.v=Vision()
    def frame(self,*names):
        v=self.v.daily;im=np.full((540,960,3),55,np.uint8)
        for n in names:
            x,y,r,b=v.specs[n]['box'];im[y:b,x:r]=v.templates[n][0]
        return im
    def test_pass_page_avoids_all_wide_card_searches(self):
        import cv2
        im=self.frame('pass_title','pass_ad','pass_ad_active');v=self.v.daily
        with patch('daily_vision.cv2.matchTemplate',wraps=cv2.matchTemplate) as search:
            state,matches=v.recognize(im)
        self.assertEqual(state,'daily_pass_ad');self.assertIn('daily_pass_ad_active',matches)
        card_arrays={id(t) for name,values in v.scaled.items() if name.startswith('card_') for t in values}
        self.assertFalse(any(id(c.args[1]) in card_arrays for c in search.call_args_list))
    def test_dungeon_labels_still_enable_all_card_sizes(self):
        import cv2
        v=self.v.daily
        for scale in (.95,1.,1.05):
            im=self.frame('dungeon_title','dungeon_tab');t=cv2.resize(v.templates['card_stone'][0],None,fx=scale,fy=scale)
            h,w=t.shape[:2];im[456:456+h,200:200+w]=t
            state,matches=v.recognize(im)
            self.assertEqual(state,'daily_dungeons');self.assertIn('daily_card_stone',matches)


class DiscoveryAndIdleTests(unittest.TestCase):
    def test_known_manager_avoids_process_scan_but_reads_live_instance(self):
        from mumu_names import read_catalog,instance_id
        with tempfile.TemporaryDirectory() as directory:
            manager=Path(directory)/'MuMuManager.exe';manager.touch()
            row={'index':3,'name':'test','created_timestamp':10,'is_process_started':True,'adb_port':12345}
            ident=instance_id(manager,row)
            with patch('adb_device.mumu_locations') as discover,patch('mumu_manager.query',return_value=json.dumps({'3':row}).encode()) as query:
                result=read_catalog('adb.exe',threading.Event(),Mock(),target_id=ident,manager_path=manager)
            self.assertEqual(result['127.0.0.1:12345']['instance_id'],ident)
            discover.assert_not_called();query.assert_called_once()
    def test_cached_manager_queries_live_port_after_change(self):
        lookup=CatalogLookup()
        first={'127.0.0.1:1001':{'instance_id':'vm','manager_path':'manager.exe'}}
        moved={'127.0.0.1:1002':{'instance_id':'vm','manager_path':'manager.exe'}}
        with patch('mumu_names.read_catalog',side_effect=[first,moved]) as read:
            lookup.read('adb',threading.Event(),Mock(),'vm')
            result=lookup.read('adb',threading.Event(),Mock(),'vm')
        self.assertEqual(result,moved);self.assertEqual(read.call_args.kwargs['manager_path'],'manager.exe')
    def test_stale_manager_falls_back_to_discovery_and_never_trusts_old_identity(self):
        lookup=CatalogLookup();lookup.paths['vm']='old.exe'
        wrong={'127.0.0.1:1001':{'instance_id':'other'}}
        fresh={'127.0.0.1:1002':{'instance_id':'vm','manager_path':'new.exe'}}
        with patch('mumu_names.read_catalog',side_effect=[wrong,fresh]) as read:
            result=lookup.read('adb',threading.Event(),Mock(),'vm')
        self.assertEqual(result,fresh);self.assertEqual(read.call_count,2)
        self.assertNotIn('manager_path',read.call_args.kwargs);self.assertEqual(lookup.paths['vm'],'new.exe')
    def test_idle_wait_emits_one_unchanged_due_time(self):
        class Clock:
            now=0;stopped=False;waits=0
            def is_set(self):return self.stopped
            def wait(self,t):self.now+=t;self.waits+=1;return self.stopped
        c=Clock();events=[];visits=[]
        def execute(job,rooms):
            visits.append(c.now)
            if len(visits)==2:c.stopped=True
            return {'farm':'skipped'}
        run_fleet([{'id':'vm','name':'vm','rooms':['farm'],'minutes':1}],True,c,threading.Event(),
                  execute,lambda *e:events.append(e),lambda:c.now)
        self.assertEqual(visits,[0,60]);self.assertEqual(len([e for e in events if e[0]=='fleet_wait']),1)
        self.assertEqual(c.waits,60)


if __name__=='__main__':unittest.main()
