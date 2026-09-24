"""Deterministic route/button regression; no game connection or real input."""
import threading,unittest
from unittest.mock import patch
import numpy as np
from extra_collector import ExtraCollector
from collector import Halt
from vision import Screen,Match

class Device:
    def __init__(self,task,empty=False,lost=0,unknown=False,stop_after=False,overlay=0):
        self.task=task;self.state='menu';self.empty=empty;self.lost=lost;self.unknown=unknown
        self.stop_after=stop_after;self.overlay=overlay;self.overlay_left=0
        self.claims=0;self.actions=[];self.clock=0;self.stop=threading.Event();self.level=0
    def capture(self):
        self.clock+=.1;im=np.zeros((540,960,3),dtype=np.uint8)
        if self.task=='training':
            from validate_training_completion import training_frame
            im=training_frame(652+self.level)
        else:im[85:107,735:807]=self.level*100
        return im
    def click(self,point):
        assert not self.stop.is_set();self.actions.append((self.state,point))
        if point==(640,520):return
        if self.state=='menu':self.state={'ranking':'ranking','training':'training','excavation':'relic','worldboss':'boss_select'}[self.task]
        elif point in {(34,28),(830,50),(830,85)}:self.state='menu'
        elif point==(866,65):self.state='boss'
        elif self.state=='relic':self.state='excavation'
        elif self.state=='boss_select':self.state='boss'
        elif self.state=='boss':self.state='boss_rank'
        else:
            assert not self.empty
            self.claims+=1
            if self.stop_after:self.stop.set()
            if self.claims>self.lost:self.empty=True;self.level=1;self.overlay_left=self.overlay
            if self.unknown:self.state='unknown'
    def screen(self):
        def m(name):return Match(name,1,0,(400,400))
        state=self.state;matches={}
        if self.overlay_left:
            self.overlay_left-=1;return Screen('reward',{'reward_close':m('reward_close')})
        if state=='menu':matches={name:m(name) for name in ['x_menu_rank','x_menu_train','x_menu_relic','x_menu_boss']}
        if state=='menu':matches['top_worldboss']=Match('top_worldboss',1,0,(706,28))
        elif state=='relic':matches={'x_dig_open':m('x_dig_open')}
        elif state=='boss_select':
            matches={'x_boss_card':m('x_boss_card')}
            if not self.empty:matches['x_boss_notice_cerberus']=m('x_boss_notice_cerberus')
        elif state=='boss':matches={'x_boss_rank_open':m('x_boss_rank_open')}
        elif state!='unknown':
            prefix={'ranking':'x_rank','training':'x_train','excavation':'x_dig','boss_rank':'x_boss'}[state]
            name=prefix+('_empty' if self.empty else '_active');matches={name:m(name)}
        return Screen(state,matches)

class Tests(unittest.TestCase):
    def run_task(self,task,**opts):
        d=Device(task,**opts)
        class Vision:
            def recognize(self,image):return d.screen()
        c=ExtraCollector(d,Vision(),d.stop,lambda x:None)
        def pause(n):
            d.clock+=n
            if d.stop.is_set():raise Halt('stop')
        c.pause=pause
        with patch('extra_collector.time.monotonic',lambda:d.clock):
            try:result=c.cycle([task])
            except Halt:result='halt'
        return d,c,result
    def test_each_route_success_and_return(self):
        for task in ['ranking','worldboss','excavation','training']:
            d,c,r=self.run_task(task)
            self.assertEqual(r,{task:'collected'});self.assertEqual(d.claims,1);self.assertEqual(d.state,'menu')
    def test_each_empty_skips_without_claim(self):
        for task in ['ranking','worldboss','excavation','training']:
            d,c,r=self.run_task(task,empty=True)
            self.assertEqual(r,{task:'skipped'});self.assertEqual(d.claims,0)
    def test_unconfirmed_first_tap_is_not_repeated(self):
        d,c,r=self.run_task('ranking',lost=1);self.assertEqual(d.claims,1);self.assertEqual(r,{'ranking':'deferred'});self.assertTrue(c.action_state.pending('ranking'))
    def test_persistent_active_button_is_deferred_after_one_input(self):
        d,c,r=self.run_task('ranking',lost=99);self.assertEqual(d.claims,1);self.assertEqual(r,{'ranking':'deferred'})
    def test_unknown_screen_receives_no_extra_tap(self):
        d,c,r=self.run_task('ranking',unknown=True);self.assertEqual(r,'halt');self.assertEqual(len(d.actions),2)
    def test_stop_prevents_departure(self):
        d,c,r=self.run_task('excavation',stop_after=True);self.assertEqual(r,'halt');self.assertEqual(len(d.actions),3)
    def test_long_overlay_waits_without_reclaim(self):
        d,c,r=self.run_task('excavation',overlay=30);self.assertEqual(r,{'excavation':'collected'});self.assertEqual(d.claims,1)
        self.assertLessEqual(sum(p==(640,520) for _,p in d.actions),3)

if __name__=='__main__':unittest.main()
