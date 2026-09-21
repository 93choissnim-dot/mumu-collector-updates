"""Autumn page identity, free claim and common-interval regressions."""
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock
import cv2
import numpy as np
from autumn_vision import AutumnVision
from collector import Halt
from daily_state import DAILY_TASKS,DailySchedule
from extra_collector import ExtraCollector
from history import History
from vision import Vision,Screen,Match


def event_frame(vision,*names,notice=False):
    im=np.full((540,960,3),110,np.uint8)
    for name in names:
        x,y,r,b=vision.specs[name]['box'];im[y:b,x:r]=vision.templates[name][0]
    if notice:cv2.fillConvexPoly(im,np.array([[928,473],[934,479],[928,485],[922,479]]),(30,30,210))
    return im


PAGE=('autumn_title','autumn_rank','autumn_reward_label','autumn_home')
MENU=('event_title','event_home','autumn_tab')


class VisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.v=AutumnVision(Path(__file__).parent/'assets')
    def test_active_and_empty_survive_native_color_shift(self):
        for kind in ('active','empty'):
            names=PAGE+('autumn_'+kind,)+(('autumn_zero',) if kind=='empty' else ())
            base=event_frame(self.v,*names,notice=kind=='active')
            for native in (False,True):
                im=np.clip(base.astype(float)*[1.22065,1.17493,1.12426]+[22.12782,2.31765,-4.33370],0,255).astype(np.uint8) if native else base
                state,m=self.v.recognize(im)
                self.assertEqual(state,'autumn');self.assertIn('autumn_'+kind,m)
                self.assertNotIn('autumn_'+('empty' if kind=='active' else 'active'),m)
    def test_list_finds_event_by_label_after_row_moves(self):
        im=event_frame(self.v,*MENU);x,y,r,b=self.v.specs['autumn_tab']['box'];tile=im[y:b,x:r].copy()
        im[y:b,x:r]=110;im[y+130:b+130,x:r]=tile
        state,m=self.v.recognize(im)
        self.assertEqual(state,'event_menu');self.assertAlmostEqual(m['autumn_tab'].center[1],(y+b)/2+130)
    def test_event_menu_without_autumn_is_distinct(self):
        state,m=self.v.recognize(event_frame(self.v,'event_title','event_home'))
        self.assertEqual(state,'event_menu');self.assertNotIn('autumn_tab',m)
    def test_empty_requires_independent_zero_count(self):
        state,m=self.v.recognize(event_frame(self.v,*PAGE,'autumn_empty'))
        self.assertEqual(state,'autumn');self.assertNotIn('autumn_empty',m)
    def test_active_requires_notice_and_rejects_zero_count(self):
        for notice,zero in ((False,False),(True,True)):
            names=PAGE+('autumn_active',)+(('autumn_zero',) if zero else ())
            _,m=self.v.recognize(event_frame(self.v,*names,notice=notice))
            self.assertNotIn('autumn_active',m)
    def test_other_event_with_same_claim_control_never_matches(self):
        names=tuple(n for n in PAGE if n!='autumn_title')+('autumn_active',)
        state,m=self.v.recognize(event_frame(self.v,*names,notice=True))
        self.assertIsNone(state);self.assertNotIn('autumn_active',m)
    def test_dim_reward_background_cannot_authorize_a_claim(self):
        im=event_frame(self.v,*PAGE,'autumn_active',notice=True)
        state,m=self.v.recognize((im*.5).astype(np.uint8))
        self.assertIsNone(state);self.assertNotIn('autumn_active',m)
    def test_partial_page_never_authorizes_a_claim(self):
        for missing in PAGE:
            names=tuple(n for n in PAGE if n!=missing)+('autumn_active',)
            state,m=self.v.recognize(event_frame(self.v,*names,notice=True))
            self.assertNotEqual(state,'autumn');self.assertNotIn('autumn_active',m)
    def test_full_vision_normalizes_resolution(self):
        v=Vision();base=event_frame(v.autumn,*PAGE,'autumn_active',notice=True)
        for size in ((960,540),(1280,720),(1920,1080)):
            s=v.recognize(cv2.resize(base,size));self.assertEqual(s.state,'autumn')
            self.assertIn('autumn_active',s.matches)
    def test_exit_modal_has_priority_over_event_background(self):
        v=Vision();im=event_frame(v.autumn,*PAGE,'autumn_active',notice=True)
        for n in ('exit_title','exit_cancel','exit_confirm'):
            x,y,r,b=v.specs[n]['box'];im[y:b,x:r]=v.templates[n][0]
        self.assertEqual(v.recognize(im).state,'exit_dialog')
    def sharp_claim(self):
        im=event_frame(self.v,*PAGE,'autumn_active',notice=True)
        x,y,r,b=self.v.specs['autumn_active']['box'];ref=self.v.templates['autumn_active'][0]
        sharp=cv2.addWeighted(ref,3,cv2.GaussianBlur(ref,(5,5),1.5),-2,0).astype(np.float32)
        mean=ref.mean((0,1));im[y:b,x:r]=np.clip(mean+(sharp-mean)*.65,0,255).astype(np.uint8)
        return im
    def test_sharp_glyph_edges_accept_only_the_active_control(self):
        state,m=self.v.recognize(self.sharp_claim())
        self.assertEqual(state,'autumn');self.assertIn('autumn_active',m);self.assertNotIn('autumn_empty',m)
        self.assertTrue(self.v.diagnostics['autumn_active']['outline_fallback'])
    def test_sharp_glyphs_survive_native_color_and_animated_title(self):
        im=self.sharp_claim();x,y,r,b=self.v.specs['autumn_title']['box']
        im[y:b,x:r]=np.clip(im[y:b,x:r].astype(float)+[20,-5,12],0,255).astype(np.uint8)
        im=np.clip(im.astype(float)*[1.22065,1.17493,1.12426]+[22.12782,2.31765,-4.33370],0,255).astype(np.uint8)
        state,m=self.v.recognize(im)
        self.assertEqual(state,'autumn');self.assertIn('autumn_active',m)
        self.assertEqual(self.v.diagnostics['_exposure']['anchors'],['autumn_rank','autumn_home'])
    def test_sharp_glyph_fallback_requires_independent_context(self):
        im=self.sharp_claim();x,y,r,b=self.v.specs['autumn_home']['box'];im[y:b,x:r]=110
        state,m=self.v.recognize(im)
        self.assertNotEqual(state,'autumn');self.assertNotIn('autumn_active',m)
    def test_similar_glyphs_with_wrong_button_color_are_rejected(self):
        im=self.sharp_claim();x,y,r,b=self.v.specs['autumn_active']['box']
        im[y:b,x:r]=np.clip(im[y:b,x:r].astype(float)+[40,-20,50],0,255).astype(np.uint8)
        _,m=self.v.recognize(im);self.assertNotIn('autumn_active',m)
    def test_scrambled_lettering_is_not_repaired_by_smoothing(self):
        im=self.sharp_claim();x,y,r,b=self.v.specs['autumn_active']['box'];im[y:b,x:r]=im[y:b,x:r][:,::-1]
        _,m=self.v.recognize(im);self.assertNotIn('autumn_active',m)


class Device:
    def __init__(self,empty=False,missing=False,stuck=False,reward=False):
        self.state='main';self.empty=empty;self.missing=missing;self.stuck=stuck;self.reward=reward
        self.clock=0;self.actions=[];self.claims=0;self.stop=threading.Event()
    def capture(self):self.clock+=.02;return np.zeros((540,960,3),np.uint8)
    def screen(self):
        keys={}
        if self.state=='main':keys={'main_menu':(919,28)}
        elif self.state=='menu':keys={'menu_farm':(800,150),'menu_wood':(800,210),'menu_mine':(800,270),'sleep_menu':(830,490)}
        elif self.state=='event_menu':
            keys={'event_title':(110,28),'event_home':(919,28)}
            if not self.missing:keys['autumn_tab']=(70,262)
        elif self.state=='autumn':
            keys={n:(200,30) for n in PAGE};keys['event_home']=(919,28)
            keys['autumn_empty' if self.empty else 'autumn_active']=(889,494)
        elif self.state=='reward':keys={'reward_close':(640,520)}
        return Screen(self.state,{k:Match(k,1,0,p) for k,p in keys.items()})
    def click(self,point):
        self.actions.append((self.state,point))
        if self.state=='main' and point==(919,28):self.state='menu'
        elif self.state=='menu' and point==(652,28):self.state='event_menu'
        elif self.state=='menu' and point==(830,490):self.state='sleep'
        elif self.state=='event_menu' and point==(70,262):self.state='autumn'
        elif self.state in {'event_menu','autumn'} and point==(919,28):self.state='main'
        elif self.state=='autumn' and point==(889,494):
            self.claims+=1
            if not self.stuck:self.empty=True
            if self.reward:self.state='reward'
        elif self.state=='reward' and point==(640,520):self.state='autumn'
        else:raise AssertionError(('Unexpected input, including enhancement',self.state,point))


class RouteTests(unittest.TestCase):
    def collector(self,**options):
        d=Device(**options);v=Mock();v.recognize.side_effect=lambda _:d.screen()
        c=ExtraCollector(d,v,d.stop,lambda _:None);c.now=lambda:d.clock
        def pause(n):
            d.clock+=n
            if d.stop.is_set():raise Halt('stopped')
        c.pause=pause;return d,c
    def test_full_cycle_claims_once_and_restores_sleep(self):
        d,c=self.collector(reward=True)
        self.assertEqual(c.cycle(['autumn'],True),{'autumn':'collected'})
        self.assertEqual(d.claims,1);self.assertEqual(d.state,'sleep')
    def test_empty_is_not_a_failure_or_claim(self):
        d,c=self.collector(empty=True)
        self.assertEqual(c.cycle(['autumn']),{'autumn':'skipped'})
        self.assertEqual(d.claims,0);self.assertEqual(d.state,'menu')
    def test_missing_event_is_terminal_without_wrong_tab_click(self):
        d,c=self.collector(missing=True)
        self.assertEqual(c.cycle(['autumn']),{'autumn':'unavailable'})
        self.assertFalse(any(p==(70,262) for _,p in d.actions));self.assertEqual(d.claims,0)
    def test_unchanged_claim_does_not_repeat_input_or_report_success(self):
        d,c=self.collector(stuck=True)
        self.assertEqual(c.cycle(['autumn']),{'autumn':'attempted'});self.assertEqual(d.claims,1)
    def test_second_run_reads_empty_instead_of_claiming_again(self):
        d,c=self.collector();self.assertEqual(c.cycle(['autumn']),{'autumn':'collected'})
        self.assertEqual(c.cycle(['autumn']),{'autumn':'skipped'});self.assertEqual(d.claims,1)
    def test_active_can_be_claimed_again_later_same_day(self):
        d,c=self.collector();c.cycle(['autumn']);d.empty=False
        self.assertEqual(c.cycle(['autumn']),{'autumn':'collected'});self.assertEqual(d.claims,2)
    def test_changed_page_prevents_stale_input(self):
        d,c=self.collector();d.state='autumn';old=d.screen();d.state='event_menu'
        with self.assertRaises(Halt):c.autumn_tap(old,'autumn_active')
        self.assertEqual(d.claims,0);self.assertFalse(d.actions)
    def test_changed_button_prevents_stale_input(self):
        d,c=self.collector();d.state='autumn';old=d.screen();d.empty=True
        with self.assertRaises(Halt):c.autumn_tap(old,'autumn_active')
        self.assertFalse(d.actions)
    def test_stop_prevents_input(self):
        d,c=self.collector();d.state='autumn';old=d.screen();d.stop.set()
        with self.assertRaises(Halt):c.autumn_tap(old,'autumn_active')
        self.assertFalse(d.actions)
    def test_conflicting_button_states_never_authorize_input(self):
        d,c=self.collector();d.state='autumn';ambiguous=d.screen();ambiguous.matches['autumn_empty']=Match('autumn_empty',1,0,(889,494))
        c.screen=Mock(return_value=ambiguous)
        with self.assertRaises(Halt):c.autumn_ready(timeout=2)
        self.assertFalse(d.actions)


class IntegrationTests(unittest.TestCase):
    def test_common_interval_and_no_failure_retry_when_unavailable(self):
        self.assertNotIn('autumn',DAILY_TASKS)
        s=DailySchedule(['autumn'],3600,lambda:0);self.assertEqual(s.next()[1],['autumn'])
        s.complete(['autumn'],{'autumn':'unavailable'},False,0)
        self.assertEqual(s.next(),(3600,['autumn'],False))
    def test_new_task_is_not_enabled_in_old_profiles(self):
        from ui_state import selected_tasks
        self.assertNotIn('autumn',selected_tasks({'selected':{'farm':True}}))
        self.assertEqual(selected_tasks({'selected':{'autumn':True}}),['autumn'])
    def test_status_labels_and_history_do_not_count_waits_as_success(self):
        from ui_state import task_summary
        self.assertEqual(task_summary('autumn','skipped'),('수령 대기','muted'))
        self.assertEqual(task_summary('autumn','unavailable'),('이벤트 없음','muted'))
        with tempfile.TemporaryDirectory() as tmp:
            h=History(Path(tmp)/'history.json');h.record('vm','autumn','unavailable')
            self.assertEqual(h.stats('vm')['today'],0);self.assertEqual(h.stats('vm')['failed_tasks'],0)


if __name__=='__main__':unittest.main()
