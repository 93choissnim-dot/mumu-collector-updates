"""Interrupted navigation and generic purchase-offer close regressions."""
import base64,json,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import cv2
import numpy as np
from collector import Collector,Halt
from extra_collector import ExtraCollector
from vision import Vision,Screen,Match
from validate_overlays import composite
import validate_navigation_recovery as nav


def offer_image(v,missing=()):
    im=composite(v,'main_menu','main_character','main_pet','top_pass')
    specs=json.loads((Path(__file__).parent/'assets/package_offer.json').read_text())
    for key,spec in specs.items():
        if key in missing:continue
        x,y,r,b=spec['box'];tile=cv2.imdecode(np.frombuffer(base64.b64decode(spec['png']),np.uint8),1)
        im[y:b,x:r]=tile
    return im


def blue_pass(v):
    im=composite(v,'main_menu','main_character','main_pet','top_pass')
    y,x=np.indices((32,34));wash=((np.sin(x*.8+y*.3)+1)*80).astype(np.float32)
    roi=im[12:44,582:616].astype(np.float32)
    roi[:,:,0]=np.clip(roi[:,:,0]+wash,0,255)
    roi[:,:,1]=np.clip(roi[:,:,1]+wash*.65,0,255)
    im[12:44,582:616]=roi.astype(np.uint8)
    return im

class OfferVisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.v=Vision()
    def test_complete_offer_preempts_background_and_exposes_only_close(self):
        for width in (640,960,1280,1920):
            s=self.v.recognize(cv2.resize(offer_image(self.v),(width,width*9//16)))
            with self.subTest(width=width):
                self.assertEqual(s.state,'package_offer')
                self.assertEqual(set(s.matches),{'package_offer_close'})
                x,y=s.matches['package_offer_close'].center
                self.assertTrue(750<x<786 and 77<y<111)
    def test_incomplete_dimmed_or_absent_offer_never_exposes_close(self):
        for missing in (('timer',),('limit',),('close',),('timer','limit','close')):
            s=self.v.recognize(offer_image(self.v,missing))
            self.assertNotIn('package_offer_close',s.matches)
            if missing==('close',):self.assertEqual(s.state,'package_offer')
        s=self.v.recognize((offer_image(self.v)*.4).astype(np.uint8))
        self.assertNotIn('package_offer_close',s.matches)
    def test_blue_combat_light_preserves_pass_identity(self):
        for width in (640,960,1280,1920):
            s=self.v.recognize(cv2.resize(blue_pass(self.v),(width,width*9//16)))
            with self.subTest(width=width):self.assertIn('top_pass',s.matches)
    def test_new_pass_candidate_rejects_dim_or_wrong_icons(self):
        for key in ('event','worldboss'):
            im=blue_pass(self.v);im[12:44,582:616]=cv2.resize(self.v.top_bar.references[key][0],(34,32))
            self.assertNotIn('top_pass',self.v.recognize(im).matches)
        self.assertNotIn('top_pass',self.v.recognize((blue_pass(self.v)*.35).astype(np.uint8)).matches)

OFFER=Screen('package_offer',{'package_offer_close':Match('package_offer_close',1,0,(768,94))})
PARTIAL=Screen('package_offer',{})
MAIN=Screen('main',{'top_pass':Match('top_pass',1,0,(599,28))})

class OfferRouteTests(unittest.TestCase):
    def collector(self,frames,cls=Collector):return nav.NavigationChangeTests().collector(frames,cls)
    def test_top_navigation_closes_offer_then_opens_pass_once(self):
        c,d,actions,frames=self.collector([MAIN,OFFER,OFFER,OFFER,OFFER,OFFER])
        def clicked(point):
            actions.append(point);frames[:]=[MAIN]*6
        d.click.side_effect=clicked
        c.top_bar_tap(c.screen(),'pass')
        self.assertEqual(actions,[(768,94),(599,28)])
    def test_daily_and_extra_waits_dismiss_without_resolving_pending(self):
        for method in ('daily_wait','wait_page'):
            c,d,actions,frames=self.collector([OFFER]*6,ExtraCollector)
            c.daily_ledger=SimpleNamespace(manual=True)
            c.action_state.reserve('training');before=c.action_state.pending('training')
            def clicked(point):actions.append(point);frames[:]=[MAIN]*6
            d.click.side_effect=clicked
            self.assertEqual(getattr(c,method)({'main'}).state,'main')
            self.assertEqual(actions,[(768,94)])
            self.assertEqual(c.action_state.pending('training'),before)
    def test_vanished_or_partial_offer_never_sends_close(self):
        for frames in ([OFFER,OFFER,MAIN,MAIN,MAIN],[PARTIAL]*8+[MAIN]*4):
            c,d,actions,_=self.collector(frames)
            self.assertEqual(c.wait_for({'main'}).state,'main');self.assertEqual(actions,[])
    def test_persistent_offer_and_lost_ack_are_bounded(self):
        c,d,actions,_=self.collector([OFFER])
        with self.assertRaises(Halt):c.wait_for({'main'})
        self.assertEqual(len(actions),3)
        c,d,actions,_=self.collector([OFFER]);d.click.side_effect=Halt('lost ack')
        with self.assertRaisesRegex(Halt,'lost ack'):c.wait_for({'main'})
        self.assertEqual(d.click.call_count,1)
    def test_stop_prevents_offer_close(self):
        c,d,actions,_=self.collector([OFFER]);c.stop.set()
        with self.assertRaises(Halt):c.wait_for({'main'})
        self.assertEqual(actions,[])
    def test_startup_closes_offer_and_partial_never_uses_escape(self):
        from start_navigation import prepare_start
        c,d,actions,frames=self.collector([OFFER]*8)
        def clicked(point):actions.append(point);frames[:]=[MAIN]*6
        d.click.side_effect=clicked
        self.assertEqual(prepare_start(c).state,'main')
        self.assertEqual(actions,[(768,94)]);d.back.assert_not_called()
        c,d,actions,_=self.collector([PARTIAL])
        with self.assertRaises(Halt):prepare_start(c)
        self.assertEqual(actions,[]);d.back.assert_not_called()

class OfferBindingTests(unittest.TestCase):
    def test_offer_binds_only_supported_game_editions(self):
        from adb_device import AdbDevice
        for package in ('com.nns.genesis','com.nns.genesis.onestore','com.browser.app'):
            d=AdbDevice(Mock(stop=threading.Event()),'127.0.0.1:16384')
            d.current_package=Mock(return_value=package)
            d.raw_capture=Mock(return_value=np.zeros((540,960,3),np.uint8))
            v=SimpleNamespace(recognize=lambda _:OFFER)
            if package=='com.browser.app':
                with self.assertRaises(Halt):d.bind_game(v)
                self.assertIsNone(d.package)
            else:self.assertEqual(d.bind_game(v).state,'package_offer')
    def test_reconnect_accepts_known_offer_without_purchase_input(self):
        import validate_game_recovery as recovery
        a,d,r,_=recovery.GameRecoveryTests().setup_recovery();a.states=['package_offer']
        self.assertTrue(r.recover());self.assertEqual(len(a.launches()),1)
        self.assertFalse(any('input' in c for c in a.calls))

if __name__=='__main__':unittest.main()
