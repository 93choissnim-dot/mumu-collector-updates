"""Native exit geometry and pre-input-only navigation recovery."""
import threading,unittest
from types import SimpleNamespace
from unittest.mock import Mock
import cv2
import numpy as np
from collector import Collector,Halt,ScreenChanged
from extra_collector import ExtraCollector
from start_navigation import prepare_start
from vision import Vision,Screen,Match,MAIN_MARKERS
from validate_overlays import composite

EXIT=('exit_title','exit_cancel','exit_confirm')
def page(state,*names):
    return Screen(state,{n:Match(n,1,0,(395,361) if n=='exit_cancel' else (925,25)) for n in names})
MAIN=page('main','main_menu');MENU=page('menu');EQUIPMENT=page('equipment')
FARM=page('farm_empty','room_farm','empty_farm');REWARD=page('reward','reward_close')

class ExitGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.v=Vision()
    def shifted(self,names=EXIT):
        im=composite(self.v,*MAIN_MARKERS,*names)
        return cv2.warpAffine(im,np.float32([[.98,0,-3],[0,.98,4]]),(960,540))
    def test_native_geometry_at_multiple_capture_sizes(self):
        for width in (640,960,1280,1920):
            s=self.v.recognize(cv2.resize(self.shifted(),(width,width*9//16)))
            self.assertEqual(s.state,'exit_dialog');self.assertTrue(set(EXIT)<=s.matches.keys())
            self.assertTrue(360<s.matches['exit_cancel'].center[0]<415)
            self.assertGreater(s.matches['exit_confirm'].center[0],540)
    def test_shifted_partial_modal_blocks_background_but_never_supplies_cancel(self):
        s=self.v.recognize(self.shifted(('exit_title','exit_confirm')))
        self.assertEqual(s.state,'exit_dialog');self.assertNotIn('exit_cancel',s.matches)
    def test_flat_or_random_modal_never_supplies_cancel(self):
        rng=np.random.default_rng(90917)
        for noise in (False,True):
            im=self.shifted();im[310:400,280:490]=rng.integers(0,255,(90,210,3),dtype=np.uint8) if noise else 160
            s=self.v.recognize(im);self.assertEqual(s.state,'exit_dialog');self.assertNotIn('exit_cancel',s.matches)

class NavigationChangeTests(unittest.TestCase):
    def collector(self,frames,cls=Collector):
        remaining=list(frames);clock=[0.];latest=[None];actions=[]
        def capture():
            clock[0]+=.1
            if remaining:latest[0]=remaining.pop(0)
            return latest[0]
        def click(point):actions.append((latest[0].state,point))
        device=SimpleNamespace(capture=capture,click=Mock(side_effect=click),back=Mock())
        c=cls(device,SimpleNamespace(recognize=lambda f:f),threading.Event(),Mock())
        c.now=lambda:clock[0];c.pause=lambda t:clock.__setitem__(0,clock[0]+t)
        return c,device,actions,remaining
    def test_vanished_equipment_does_not_fail_or_send_dismissal(self):
        for cls in (Collector,ExtraCollector):
            c,d,actions,_=self.collector([EQUIPMENT,EQUIPMENT,MAIN,MAIN,MAIN],cls)
            self.assertEqual(c.wait_for({'main'}).state,'main');self.assertEqual(actions,[])
    def test_facility_return_dismisses_new_reward_without_reclaiming(self):
        c,d,actions,_=self.collector([FARM,REWARD,REWARD,REWARD,REWARD,FARM,FARM,FARM,MENU,MENU])
        c.results={'farm':'collected'};c.claim_counts={'farm':1}
        self.assertEqual(c.leave_room('farm',c.screen()).state,'menu')
        self.assertEqual(actions,[('reward',(640,520)),('farm_empty',(34,28))])
        self.assertEqual(c.results,{'farm':'collected'});self.assertEqual(c.claim_counts,{'farm':1})
    def test_facility_already_returned_before_input_sends_no_back(self):
        c,d,actions,_=self.collector([FARM,MENU,MENU,MENU])
        self.assertEqual(c.leave_room('farm',c.screen()).state,'menu');self.assertEqual(actions,[])
    def test_menu_opened_before_input_is_never_toggled_closed(self):
        c,d,actions,_=self.collector([MAIN,MENU,MENU,MENU])
        self.assertEqual(c.ensure_menu(c.screen()).state,'menu');self.assertEqual(actions,[])
    def test_transient_overlay_before_menu_rechecks_then_opens_once(self):
        c,d,actions,frames=self.collector([MAIN,EQUIPMENT,MAIN,MAIN,MAIN])
        def opened(point):actions.append(point);frames[:]=[MENU,MENU,MENU,MENU]
        d.click.side_effect=opened
        self.assertEqual(c.ensure_menu(c.screen()).state,'menu');self.assertEqual(actions,[(925,25)])
    def test_exit_cancel_disappears_before_input_never_hits_main(self):
        modal=page('exit_dialog',*EXIT)
        c,d,actions,_=self.collector([modal,modal,MAIN,MAIN,MAIN])
        self.assertEqual(prepare_start(c).state,'main');self.assertEqual(actions,[]);d.back.assert_not_called()
    def test_fresh_partial_exit_is_rechecked_without_click(self):
        modal=page('exit_dialog',*EXIT);partial=page('exit_dialog','exit_title','exit_cancel')
        c,d,actions,_=self.collector([modal,modal,partial,MAIN,MAIN])
        self.assertEqual(prepare_start(c).state,'main');self.assertEqual(actions,[]);d.back.assert_not_called()
    def test_dispatch_errors_are_not_retried(self):
        for method,frames in [('overlay',[EQUIPMENT]*5),('leave',[FARM]*5),('menu',[MAIN]*5)]:
            c,d,actions,_=self.collector(frames);d.click.side_effect=Halt('transport failed')
            with self.assertRaisesRegex(Halt,'transport failed'):
                if method=='overlay':c.wait_for({'main'})
                elif method=='leave':c.leave_room('farm',c.screen())
                else:c.ensure_menu(c.screen())
            d.click.assert_called_once()
    def test_rejected_menu_inputs_have_a_limit(self):
        c,d,actions,_=self.collector([MAIN]);s=c.screen()
        c.click_match=Mock(side_effect=ScreenChanged('changed'));c.wait_for=Mock(return_value=MAIN)
        with self.assertRaises(Halt):c.ensure_menu(s)
        self.assertEqual(c.click_match.call_count,3);d.click.assert_not_called()
    def test_sent_menu_input_retries_only_bounded_verified_main(self):
        c,d,actions,_=self.collector([MAIN]*5)
        with self.assertRaises(Halt):c.ensure_menu(c.screen())
        self.assertEqual(d.click.call_count,3)
    def test_top_icon_flicker_before_dispatch_rechecks_without_duplicate_touch(self):
        boss=page('menu','top_worldboss')
        c,d,actions,_=self.collector([boss,MENU,boss,boss])
        c.top_bar_tap(c.screen(),'worldboss')
        d.click.assert_called_once()
    def test_top_icon_missing_forever_or_different_page_never_clicks(self):
        boss=page('menu','top_worldboss')
        for frames in ([boss,MENU],[boss,page('daily_shop')]):
            c,d,_,_=self.collector(frames)
            with self.assertRaises(Halt):c.top_bar_tap(c.screen(),'worldboss')
            d.click.assert_not_called()
    def test_top_icon_dispatch_error_is_never_retried(self):
        boss=page('menu','top_worldboss');c,d,_,_=self.collector([boss]*4)
        d.click.side_effect=Halt('lost acknowledgement')
        with self.assertRaisesRegex(Halt,'lost acknowledgement'):c.top_bar_tap(c.screen(),'worldboss')
        d.click.assert_called_once()
    def test_extra_return_rechecks_before_input_and_preserves_result(self):
        autumn=page('autumn','event_home')
        c,d,actions,remaining=self.collector([autumn,MAIN,MAIN,MENU,MENU],ExtraCollector)
        c.results={'autumn':'collected'}
        self.assertEqual(c.ensure_menu(c.screen()).state,'menu')
        self.assertEqual(c.results,{'autumn':'collected'})
        self.assertNotIn(('main',(925,25)),actions)
    def test_extra_return_dispatch_failure_does_not_retry(self):
        autumn=page('autumn','event_home');c,d,_,_=self.collector([autumn]*5,ExtraCollector)
        d.click.side_effect=Halt('lost acknowledgement')
        with self.assertRaisesRegex(Halt,'lost acknowledgement'):c.ensure_menu(c.screen())
        d.click.assert_called_once()
    def test_stop_after_rejected_input_prevents_another_capture_or_touch(self):
        c,d,actions,_=self.collector([MAIN]);s=c.screen()
        def reject(*args,**kwargs):c.stop.set();raise ScreenChanged('changed')
        c.click_match=Mock(side_effect=reject)
        with self.assertRaises(Halt):c.ensure_menu(s)
        c.click_match.assert_called_once();d.click.assert_not_called()

if __name__=='__main__':unittest.main()

class RouteGroupingTests(unittest.TestCase):
    def test_top_bar_group_does_not_reopen_menu_between_tasks(self):
        c=ExtraCollector(Mock(),Mock(),threading.Event(),Mock());c.progress=Mock()
        c.last_screen=MAIN;opens=[];entries=[]
        def base(screen=None,room=None):
            if screen.state in {'main','menu'}:return screen
            c.last_screen=MAIN;return MAIN
        def menu(screen=None,room=None):
            if screen.state!='menu':opens.append(screen.state)
            c.last_screen=MENU;return MENU
        def task(key,screen):
            entries.append((key,screen.state));c.record_task(key,'skipped')
            c.last_screen=MAIN if key in {'worldboss','autumn'} else MENU
            return c.last_screen
        c.return_base=Mock(side_effect=base);c.ensure_menu=Mock(side_effect=menu)
        c.collect_world_boss=lambda s:task('worldboss',s)
        c.collect_autumn=lambda s:task('autumn',s)
        c.enter=lambda key,s:s
        c.claim_extra=lambda key,s:task(key,s)
        from unittest.mock import patch
        with patch('start_navigation.prepare_start',return_value=MAIN):
            result=c.cycle(['worldboss','autumn','ranking'])
        self.assertEqual(entries,[('worldboss','main'),('autumn','main'),('ranking','menu')])
        self.assertEqual(opens,['main'])
        self.assertEqual(result,{'worldboss':'skipped','autumn':'skipped','ranking':'skipped'})
    def test_unknown_recovery_cannot_advance_to_next_top_bar_task(self):
        from unittest.mock import patch
        c=ExtraCollector(Mock(),Mock(),threading.Event(),Mock());c.progress=Mock()
        c.return_base=Mock(return_value=MAIN);c.ensure_menu=Mock(return_value=MENU)
        c.collect_world_boss=Mock(side_effect=Halt('recognition failed'))
        c.collect_autumn=Mock();c.screen=Mock(return_value=page('unknown'))
        with patch('start_navigation.prepare_start',return_value=MAIN),self.assertRaises(Halt):
            c.cycle(['worldboss','autumn'])
        c.collect_autumn.assert_not_called()
    def test_worldboss_accepts_main_but_still_uses_verified_top_icon(self):
        c=ExtraCollector(Mock(),Mock(),threading.Event(),Mock());c.top_bar_tap=Mock()
        c.open_boss_selection(MAIN);c.top_bar_tap.assert_called_once_with(MAIN,'worldboss')
        c.top_bar_tap.reset_mock()
        with self.assertRaises(Halt):c.open_boss_selection(page('unknown'))
        c.top_bar_tap.assert_not_called()
