"""Native mode chooser and already-exhausted daily quota regressions."""
import base64,json,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import cv2,numpy as np
from vision import Vision,Screen,Match
from collector import Halt
from extra_collector import ExtraCollector
import validate_v077_routes as prior

def case(key):
    """Public fixtures contain only generic UI controls, never account captures."""
    root=Path(__file__).parent/'assets'
    if key=='boss':
        im=np.zeros((447,653,3),np.uint8)
        for spec in json.loads((root/'boss_mode_controls.json').read_text()).values():
            x,y,r,b=spec['box']
            tile=cv2.imdecode(np.frombuffer(base64.b64decode(spec['png']),np.uint8),1)
            im[y-6:b+6,x-6:r+6]=cv2.copyMakeBorder(tile,6,6,6,6,cv2.BORDER_REPLICATE)
        return im
    from free_daily_vision import FreeDailyVision
    v=FreeDailyVision(root);im=np.zeros((540,960,3),np.uint8)
    def put(tile,x,y):
        h,w=tile.shape[:2];im[y:y+h,x:x+w]=tile
    if key=='summon':
        for name in ('summon_info','title_character','count_main_zero'):
            x,y,_,_=v.specs[name]['roi'];put(v.refs[name],x+4,y+4)
        return im
    for name in ('store_header','store_home'):
        x,y,_,_=v.specs[name]['roi'];put(v.refs[name],x+4,y+4)
    im[70:98,73:141]=(140,170,200)
    variants=json.loads((root/'native_shop_variants.json').read_text())['free']
    for name,index,x,y in [('card_ruby',0,773,82),('card_ruby',1,323,307),
                         ('card_zero',0,770,60),('card_zero',1,322,284),
                         ('card_ad_icon',0,326,352),('card_ruby_icon',0,778,141)]:
        put(cv2.imdecode(np.frombuffer(base64.b64decode(variants[name][index]),np.uint8),1),x,y)
    return im
def modal_frame(offset=(145,46)):
    modal=case('boss');h,w=modal.shape[:2];x,y=offset
    im=np.zeros((540,960,3),np.uint8);im[y:y+h,x:x+w]=modal
    return im

class NativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.v=Vision()
    def test_mode_chooser_recognized_with_normal_button_at_three_capture_sizes(self):
        for offset in ((88,45),(145,46)):
            im=modal_frame(offset)
            for w in (640,960,1280):
                with self.subTest(offset=offset,width=w):
                    s=self.v.recognize(cv2.resize(im,(w,w*9//16)))
                    self.assertEqual(s.state,'boss_mode')
                    self.assertIn('x_boss_mode_normal',s.matches)
                    self.assertLess(s.matches['x_boss_mode_normal'].center[0],480)
    def test_dimmed_mode_never_authorizes_normal(self):
        s=self.v.recognize((modal_frame().astype(float)*.5).astype(np.uint8))
        self.assertNotIn('x_boss_mode_normal',s.matches)
    def test_native_summon_reports_exhausted_character_allowance(self):
        s=self.v.recognize(case('summon'))
        self.assertEqual(s.state,'free_summon_character')
        self.assertIn('daily_free_count_0',s.matches)
        self.assertIn('daily_free_identity_character',s.matches)
        self.assertNotIn('daily_free_summon',s.matches)
    def test_missing_either_label_or_close_never_authorizes_normal(self):
        for box in ((147,342,206,374),(408,342,535,374),(594,25,623,54)):
            im=modal_frame();x,y,r,b=box;im[y+46:b+46,x+145:r+145]=0
            s=self.v.recognize(im);self.assertNotIn('x_boss_mode_normal',s.matches)
    def test_cooldown_cards_are_done_without_purchase_buttons(self):
        s=self.v.recognize(case('store'));self.assertEqual(s.state,'free_store')
        for key in ('ruby','ruby_ad'):
            self.assertIn('daily_free_done_'+key,s.matches)
            self.assertNotIn('daily_free_open_'+key,s.matches)
    def test_zero_counter_without_item_identity_is_not_done(self):
        im=case('store');im[75:118,705:915]=0;im[309:343,255:465]=0
        s=self.v.recognize(im)
        self.assertNotIn('daily_free_done_ruby',s.matches)
        self.assertNotIn('daily_free_done_ruby_ad',s.matches)

class ExhaustedTests(unittest.TestCase):
    def test_prior_day_pending_and_current_zero_complete_without_confirming_old_request(self):
        helper=prior.RouteTests();self.addCleanup(helper.doCleanups)
        c,d=helper.summon(count=0);old=c.daily_detail()['input_request']['id']
        c.free_summon_step('character')
        self.assertTrue(c.daily_done('character'));self.assertEqual(d.clicks,[])
        self.assertFalse(c.daily_detail().get('pending'))
        h=next(h for h in c.daily_detail()['input_history'] if h['request']['id']==old)
        self.assertFalse(h['resolution']['confirmed'])
        self.assertEqual(h['resolution']['source'],'expired_daily_allowance')
    def test_invalid_origin_with_zero_stays_unresolved(self):
        helper=prior.RouteTests();self.addCleanup(helper.doCleanups)
        c,d=helper.summon(count=0,stamp='invalid')
        with self.assertRaises(Halt):c.free_summon_step('character')
        self.assertTrue(c.daily_detail().get('pending'));self.assertFalse(c.daily_done('character'))
        self.assertEqual(d.clicks,[])

class ModeRouteTests(unittest.TestCase):
    def route(self,*,stuck=False,changed=False,stopped=False,returning=False):
        def m(key,p):return Match(key,1,0,p)
        mode=Screen('boss_mode',{k:m(k,p) for k,p in [('x_boss_mode_title',(200,74)),
            ('x_boss_mode_close',(753,86)),('x_boss_mode_normal',(321,404)),
            ('x_boss_mode_integrated_label',(616,404))]})
        done=Screen('boss_select',{})
        class Device:
            clock=0.;reads=0;clicks=[];state=mode
            def capture(d):
                d.clock+=.1;d.reads+=1
                if changed and d.reads>=3:return Screen('unknown',{})
                return d.state
            def click(d,p):
                d.clicks.append(p)
                if not stuck:d.state=done
        d=Device();d.clicks=[]
        c=ExtraCollector(d,SimpleNamespace(recognize=lambda x:x),threading.Event(),lambda _:None)
        c.now=lambda:d.clock;c.pause=lambda n:setattr(d,'clock',d.clock+n)
        if stopped:c.stop.set()
        error=None
        try:s=c.return_to_boss_selection() if returning else c.wait_boss_selection()
        except Halt as e:error=e;s=None
        return c,d,s,error
    def test_normal_is_selected_once_before_boss_cards(self):
        c,d,s,e=self.route();self.assertIsNone(e);self.assertEqual(s.state,'boss_select')
        self.assertEqual(d.clicks,[(321,404)])
    def test_return_route_also_selects_normal(self):
        c,d,s,e=self.route(returning=True);self.assertIsNone(e)
        self.assertEqual(s.state,'boss_select');self.assertEqual(d.clicks,[(321,404)])
    def test_stopped_route_sends_no_input(self):
        c,d,s,e=self.route(stopped=True);self.assertIsNotNone(e);self.assertEqual(d.clicks,[])
    def test_return_base_handles_four_nested_boss_pages(self):
        pages=[Screen(k,{}) for k in ('boss_rank','boss','boss_select')]
        pages.append(Screen('boss_mode',{k:Match(k,1,0,p) for k,p in
            [('x_boss_mode_title',(200,74)),('x_boss_mode_close',(753,86))]}))
        pages.append(Screen('main',{}))
        class Device:
            index=0
            def capture(d):return pages[d.index]
            def click(d,p):d.index+=1
        d=Device();c=ExtraCollector(d,SimpleNamespace(recognize=lambda x:x),threading.Event(),lambda _:None)
        c.pause=lambda _:None
        self.assertEqual(c.return_base().state,'main')
        self.assertEqual(d.index,4)
    def test_return_base_closes_mode_using_recognized_close(self):
        c,d,_,_=self.route(stuck=True)
        d.clicks=[]
        c.wait_page=lambda states:Screen('main',{})
        s=c.screen();c.return_base(s)
        self.assertEqual(d.clicks,[(753,86)])
    def test_unchanged_mode_is_bounded(self):
        c,d,s,e=self.route(stuck=True);self.assertIsNotNone(e)
        self.assertGreater(len(d.clicks),0);self.assertLessEqual(len(d.clicks),3)
    def test_changed_mode_before_input_sends_nothing(self):
        c,d,s,e=self.route(changed=True);self.assertIsNotNone(e);self.assertEqual(d.clicks,[])

if __name__=='__main__':unittest.main()
