"""Three-card notice detection and collection routes without live input."""
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch,Mock
import cv2
import numpy as np
from collector import Halt
from extra_collector import ExtraCollector
from vision import Vision,Screen,Match
from task_catalog import PAGE_MARKERS
from validate_overlays import composite
from world_boss import BOSSES,boss_notices

class NoticeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.v=Vision()
    def selection(self,keys,color=(25,25,220)):
        im=composite(self.v,*PAGE_MARKERS['boss_select'])
        for key,_,_,(x1,y1,x2,y2) in BOSSES:
            if key in keys:
                x,y=x1+10,y1+10
                cv2.fillConvexPoly(im,np.array([(x,y-5),(x+4,y),(x,y+5),(x-4,y)],np.int32),color)
        return im
    def test_boss_page_survives_obscured_unused_tactics_icon(self):
        im=composite(self.v,'x_boss_mission','x_boss_rank_open','x_boss_supply')
        x,y,r,b=self.v.specs['x_boss_power']['box'];im[y:b,x:r]=0
        s=self.v.recognize(im);self.assertEqual(s.state,'boss')
        self.assertIn('x_boss_rank_open',s.matches);self.assertNotIn('x_boss_power',s.matches)
    def test_boss_page_requires_all_three_independent_controls(self):
        markers=('x_boss_mission','x_boss_rank_open','x_boss_supply')
        for missing in markers:
            im=composite(self.v,*(n for n in markers if n!=missing))
            self.assertNotEqual(self.v.recognize(im).state,'boss',missing)
    def test_each_card_and_combinations_at_three_sizes(self):
        for keys in [(),('cerberus',),('kraken',),('void',),('cerberus','void'),tuple(b[0] for b in BOSSES)]:
            for color in ((25,25,220),(18,18,130)):
                for width in (640,960,1280):
                    s=self.v.recognize(cv2.resize(self.selection(keys,color),(width,width*9//16)))
                    self.assertEqual(s.state,'boss_select')
                    seen={b[0] for b in BOSSES if 'x_boss_notice_'+b[0] in s.matches}
                    self.assertEqual(seen,set(keys),(keys,color,width,seen))
    def test_red_background_outside_badges_is_ignored(self):
        im=self.selection(())
        im[180:420,120:840]=(0,0,240)
        self.assertFalse(boss_notices(im))
    def test_grey_marks_single_pixels_and_full_red_boxes_are_not_badges(self):
        self.assertFalse(boss_notices(self.selection([b[0] for b in BOSSES],(180,180,180))))
        for mode in ('pixel','solid'):
            im=self.selection(())
            for _,_,_,(x1,y1,x2,y2) in BOSSES:
                if mode=='pixel':im[y1+10,x1+10]=(0,0,240)
                else:im[y1:y2,x1:x2]=(0,0,240)
            self.assertFalse(boss_notices(im))
    def test_badges_without_selection_markers_do_not_trigger(self):
        im=self.selection(['cerberus','kraken','void']);im[55:110,100:850]=0
        s=self.v.recognize(im)
        self.assertNotEqual(s.state,'boss_select')
        self.assertFalse(any('notice_' in k for k in s.matches))

    def test_preparing_text_each_card_with_notice_at_three_sizes_and_color_casts(self):
        for key,_,_,_ in BOSSES:
            name='x_boss_preparing_'+key
            im=self.selection([key]);x1,y1,x2,y2=self.v.specs[name]['box']
            im[y1:y2,x1:x2]=self.v.templates[name][0]
            for light in (.9,1,1.18):
                cast=np.clip(im.astype(np.float32)*light,0,255).astype(np.uint8)
                for width in (640,960,1280):
                    s=self.v.recognize(cv2.resize(cast,(width,width*9//16)))
                    self.assertEqual(s.state,'boss_select')
                    self.assertIn('x_boss_notice_'+key,s.matches)
                    self.assertIn(name,s.matches,(key,light,width))
                    for other,_,_,_ in BOSSES:
                        if other!=key:self.assertNotIn('x_boss_preparing_'+other,s.matches)

class BossDevice:
    def __init__(self,notices,*,preparing=(),empty=(),persistent=False,lost=0,unknown=None,cancel=False,back_to_select=False,back_to_relic=False,hidden_entry=False):
        self.state='menu';self.notices=set(notices);self.empty=set(empty);self.persistent=persistent
        self.preparing=set(preparing)
        self.lost,self.unknown,self.cancel=lost,unknown,cancel;self.back_to_select=back_to_select
        self.back_to_relic=back_to_relic;self.hidden_entry=hidden_entry
        self.current=None;self.clock=0.;self.stop=threading.Event();self.entered=[];self.actions=[]
        self.claims={b[0]:0 for b in BOSSES};self.results=[]
        self.cards={b[2]:(234+i*246,152) for i,b in enumerate(BOSSES)}
    def capture(self):self.clock+=.1;return self.screen()
    def screen(self):
        def m(name,point):return Match(name,1,0,point)
        matches={}
        if self.state=='menu' and not self.hidden_entry:matches['x_menu_boss']=m('x_menu_boss',(706,28))
        elif self.state=='boss_select':
            for key,_,card,_ in BOSSES:
                matches[card]=m(card,self.cards[card])
                if key in self.notices:matches['x_boss_notice_'+key]=m('x_boss_notice_'+key,(0,0))
                if key in self.preparing:matches['x_boss_preparing_'+key]=m('x_boss_preparing_'+key,(0,0))
        elif self.state=='boss':matches['x_boss_rank_open']=m('x_boss_rank_open',(136,487))
        elif self.state=='boss_rank':
            name='x_boss_empty' if self.current in self.empty else 'x_boss_active'
            matches[name]=m(name,(843,114))
        return Screen(self.state,matches)
    def click(self,point):
        assert not self.stop.is_set()
        self.actions.append((self.state,point))
        if self.state=='menu':assert point==(706,28);self.state='boss_select'
        elif self.state=='relic':assert point==(34,28);self.state='menu'
        elif self.state=='boss_select':
            if point==(830,85):self.state='menu';return
            key=next(b[0] for b in BOSSES if self.cards[b[2]]==point)
            assert key in self.notices
            assert key not in self.preparing
            self.current=key;self.entered.append(key)
            self.state='unknown' if key==self.unknown else 'boss'
        elif self.state=='boss':
            if point==(34,28):self.state='boss_select' if self.back_to_select else 'relic' if self.back_to_relic else 'menu'
            else:assert point==(136,487);self.state='boss_rank'
        elif self.state=='boss_rank':
            if point==(866,65):self.state='boss';return
            assert point==(843,114) and self.current not in self.empty
            self.claims[self.current]+=1
            if self.claims[self.current]>self.lost:
                self.empty.add(self.current)
                if not self.persistent:self.notices.discard(self.current)
            if self.cancel:self.stop.set()
        else:raise AssertionError('Unexpected input '+self.state)

class RouteTests(unittest.TestCase):
    def run_flow(self,notices,**options):
        d=BossDevice(notices,**options);c=ExtraCollector(d,SimpleNamespace(recognize=lambda x:x),d.stop,lambda x:None,
            on_result=lambda task,result:d.results.append((task,result)))
        def pause(t):
            if d.stop.is_set():raise Halt('Stopped')
            d.clock+=t
        c.pause=pause
        with patch('collector.time.monotonic',lambda:d.clock):
            try:r=c.cycle(['worldboss'])
            except Halt:r='halt'
        return d,c,r
    def test_only_second_or_third_notice_is_followed(self):
        for key in ('kraken','void'):
            d,c,r=self.run_flow([key]);self.assertEqual(d.entered,[key])
            self.assertEqual(r,{'worldboss':'collected'});self.assertEqual(sum(d.claims.values()),1)
    def test_combat_effects_on_entry_icon_do_not_block_verified_menu(self):
        d,c,r=self.run_flow(['kraken'],hidden_entry=True)
        self.assertEqual(r,{'worldboss':'collected'});self.assertEqual(d.entered,['kraken'])
    def test_boss_back_can_restore_underlying_relic_page(self):
        d,c,r=self.run_flow(['cerberus','kraken'],back_to_relic=True)
        self.assertEqual(r,{'worldboss':'collected'});self.assertEqual(d.entered,['cerberus','kraken'])
        self.assertEqual(d.state,'menu');self.assertEqual(sum(d.claims.values()),2)
        self.assertIn(('relic',(34,28)),d.actions)
    def test_changed_menu_blocks_entry(self):
        d=BossDevice([]);c=ExtraCollector(d,SimpleNamespace(recognize=lambda x:x),d.stop,lambda x:None)
        menu=d.screen();d.state='unknown'
        with self.assertRaises(Halt):c.open_boss_selection(menu)
        self.assertFalse(d.actions)
    def test_changed_boss_page_blocks_stale_back_click(self):
        d=BossDevice([]);c=ExtraCollector(d,SimpleNamespace(recognize=lambda x:x),d.stop,lambda x:None)
        c.wait_page=Mock(side_effect=[Screen('boss',{}),Screen('boss_select',{})])
        d.state='relic';self.assertEqual(c.return_to_boss_selection().state,'boss_select')
        self.assertFalse(d.actions)
    def test_three_notices_collect_once_each_and_record_one_result(self):
        for back in (False,True):
            d,c,r=self.run_flow([b[0] for b in BOSSES],back_to_select=back)
            self.assertEqual(d.entered,[b[0] for b in BOSSES]);self.assertEqual(sum(d.claims.values()),3)
            self.assertEqual(c.claim_counts['worldboss'],3);self.assertEqual(d.results,[('worldboss','collected')])
            self.assertEqual(d.state,'menu')
    def test_two_notices_skip_unmarked_middle(self):
        d,c,r=self.run_flow(['cerberus','void']);self.assertEqual(d.entered,['cerberus','void'])
        self.assertEqual(d.claims['kraken'],0)
    def test_no_notices_skip_all_cards(self):
        d,c,r=self.run_flow([]);self.assertFalse(d.entered);self.assertEqual(r,{'worldboss':'skipped'})
    def test_preparing_overrides_red_notice_on_any_card(self):
        keys=[b[0] for b in BOSSES]
        for preparing in ([key] for key in keys):
            d,c,r=self.run_flow(keys,preparing=preparing)
            self.assertEqual(d.entered,[key for key in keys if key not in preparing])
            self.assertEqual(r,{'worldboss':'collected'})
    def test_all_preparing_skips_even_when_all_red(self):
        keys=[b[0] for b in BOSSES]
        d,c,r=self.run_flow(keys,preparing=keys)
        self.assertFalse(d.entered);self.assertEqual(sum(d.claims.values()),0)
        self.assertEqual(r,{'worldboss':'skipped'})
    def test_persistent_notices_do_not_reopen_visited_cards(self):
        d,c,r=self.run_flow([b[0] for b in BOSSES],persistent=True)
        self.assertEqual(len(d.entered),3);self.assertEqual(len(set(d.entered)),3)
        self.assertEqual(r,{'worldboss':'collected'})
    def test_notice_with_inactive_reward_is_skipped_without_claim(self):
        d,c,r=self.run_flow(['kraken'],empty=['kraken'],persistent=True)
        self.assertEqual(d.entered,['kraken']);self.assertEqual(sum(d.claims.values()),0)
        self.assertEqual(r,{'worldboss':'skipped'})
    def test_each_boss_has_three_claim_limit(self):
        d,c,r=self.run_flow([b[0] for b in BOSSES],lost=99,persistent=True)
        self.assertEqual(list(d.claims.values()),[3,3,3]);self.assertEqual(c.claim_counts['worldboss'],9)
        self.assertEqual(r,{'worldboss':'attempted'})
    def test_first_success_skips_remaining_retries(self):
        d,c,r=self.run_flow(['cerberus','kraken'],lost=1)
        self.assertEqual(list(d.claims.values()),[2,2,0]);self.assertEqual(c.claim_counts['worldboss'],4)
    def test_unknown_boss_page_never_gets_rank_or_claim_click(self):
        d,c,r=self.run_flow(['kraken','void'],unknown='kraken')
        self.assertEqual(r,'halt');self.assertEqual(d.entered,['kraken']);self.assertEqual(sum(d.claims.values()),0)
    def test_cancel_during_claim_prevents_next_boss(self):
        d,c,r=self.run_flow([b[0] for b in BOSSES],cancel=True)
        self.assertEqual(r,'halt');self.assertEqual(d.entered,['cerberus']);self.assertEqual(sum(d.claims.values()),1)

if __name__=='__main__':unittest.main()
