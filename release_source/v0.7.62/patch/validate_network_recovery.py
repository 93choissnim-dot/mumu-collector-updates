"""Network modal identity and real Android input boundaries, without account frames."""
from pathlib import Path
from types import SimpleNamespace
import unittest
import cv2
import numpy as np
from collector import Halt
import validate_game_recovery as fixtures

def network_frame(offset=(250,130),scale=1.0):
    atlas=cv2.imdecode(np.fromfile(Path(__file__).parent/'assets/network_disconnect_controls.png',np.uint8),cv2.IMREAD_COLOR)
    panel=np.full((276,460,3),(146,176,196),np.uint8)
    panel[67:115,65:395]=atlas[:48]
    panel[195:255,55:215]=atlas[48:108,:160]
    panel[195:255,245:405]=atlas[108:168,:160]
    panel=cv2.resize(panel,None,fx=scale,fy=scale)
    im=np.zeros((540,960,3),np.uint8);x,y=offset;h,w=panel.shape[:2];im[y:y+h,x:x+w]=panel
    return im

def recovery(stuck=False):
    a,d,r,_=fixtures.GameRecoveryTests().setup_recovery();a.focus=fixtures.GAME;a.alive=True;taps=[]
    modal=network_frame();normal=np.zeros((540,960,3),np.uint8)
    d.raw_capture=lambda:modal.copy() if not taps or stuck else normal.copy()
    r.vision.recognize=lambda im:SimpleNamespace(state='unknown' if im.any() else 'menu',matches={})
    original=a.run
    def run(args,**kw):
        if args[2:5]==['shell','input','tap']:taps.append(args[5:]);return b''
        return original(args,**kw)
    a.run=run
    return a,d,r,taps

class NetworkRecoveryTests(unittest.TestCase):
    def test_running_game_confirms_right_button_without_relaunch(self):
        a,d,r,taps=recovery()
        self.assertTrue(r.recover());self.assertEqual(taps,[[575,355]]);self.assertEqual(a.launches(),[])
    def test_persistent_popup_never_repeats_confirmation_across_recovery_objects(self):
        from game_recovery import GameRecovery
        a,d,r,taps=recovery(stuck=True)
        with self.assertRaises(Halt):r.recover()
        fresh=GameRecovery(d,r.vision,a.stop,lambda:None,lambda _:None,clock=lambda:a.tick);fresh.startup=r.startup
        with self.assertRaises(Halt):fresh.recover()
        self.assertEqual(taps,[[575,355]]);self.assertEqual(a.launches(),[])
    def test_popup_changes_before_touch_sends_no_input(self):
        a,d,r,taps=recovery();frames=[network_frame(),network_frame(),np.zeros((540,960,3),np.uint8)]
        d.raw_capture=lambda:frames.pop(0) if frames else np.zeros((540,960,3),np.uint8)
        r.recover();self.assertEqual(taps,[])
    def test_stop_during_final_capture_sends_no_input(self):
        a,d,r,taps=recovery();captures=[]
        def capture():
            captures.append(1)
            if len(captures)==3:a.stop.set()
            return network_frame()
        d.raw_capture=capture
        with self.assertRaises(Halt):r.recover()
        self.assertEqual(taps,[])
    def test_foreground_changes_during_final_capture_sends_no_input(self):
        a,d,r,taps=recovery();captures=[]
        def capture():
            captures.append(1)
            if len(captures)==3:a.focus='com.browser.app'
            return network_frame()
        d.raw_capture=capture
        with self.assertRaises(Halt):r.recover()
        self.assertEqual(taps,[])
    def test_new_incident_after_verified_recovery_can_confirm_once(self):
        a,d,r,taps=recovery();self.assertTrue(r.recover())
        d.raw_capture=lambda:network_frame() if len(taps)==1 else np.zeros((540,960,3),np.uint8)
        self.assertTrue(r.recover());self.assertEqual(taps,[[575,355],[575,355]])
    def test_independent_watch_handles_network_without_collection(self):
        from game_watch import GameWatch
        a,d,r,taps=recovery();watch=GameWatch(lambda _:None);watch.enable(True)
        def prepare(job,control):
            control.wait=a.stop.wait;a.stop=control;r.stop=control;return r
        watch.scan([{'id':'a','enabled':True}],prepare)
        self.assertEqual(taps,[[575,355]]);self.assertEqual(a.launches(),[])
    def test_network_confirmation_can_lead_to_offline_reward(self):
        a,d,r,taps=recovery()
        r.vision.recognize=lambda im:SimpleNamespace(state='unknown' if not taps else ('offline_reward' if len(taps)==1 else 'menu'),matches={'offline_confirm':SimpleNamespace(center=(480,400))})
        self.assertTrue(r.recover());self.assertEqual(taps,[[575,355],[480,400]])
    def test_network_during_app_launch_is_confirmed_before_ready(self):
        a,d,r,taps=recovery();a.focus=fixtures.HOME;a.alive=False
        self.assertTrue(r.recover());self.assertEqual(taps,[[575,355]]);self.assertEqual(len(a.launches()),1)
    def test_confirm_that_exits_to_home_relaunches_and_resumes(self):
        a,d,r,taps=recovery();original=a.run
        def run(args,**kw):
            result=original(args,**kw)
            if args[2:5]==['shell','input','tap']:a.focus=fixtures.HOME;a.alive=False
            return result
        a.run=run
        self.assertTrue(r.recover());self.assertEqual(taps,[[575,355]]);self.assertEqual(len(a.launches()),1)
    def test_high_resolution_input_uses_actual_device_coordinates(self):
        a,d,r,taps=recovery();d.raw_capture=lambda:cv2.resize(network_frame(),(1920,1080)) if not taps else np.zeros((1080,1920,3),np.uint8)
        self.assertTrue(r.recover());self.assertEqual(taps,[[1150,710]])
    def test_unconfirmed_incident_clears_only_after_normal_screen(self):
        a,d,r,taps=recovery(stuck=True)
        with self.assertRaises(Halt):r.recover()
        d.raw_capture=lambda:np.zeros((540,960,3),np.uint8)
        self.assertTrue(r.recover());self.assertEqual(len(taps),1)
        d.raw_capture=lambda:network_frame() if len(taps)==1 else np.zeros((540,960,3),np.uint8)
        self.assertTrue(r.recover());self.assertEqual(len(taps),2)

class NetworkRecognitionTests(unittest.TestCase):
    def test_exact_network_modal_preempts_collection(self):
        from vision import Vision
        screen=Vision().recognize(network_frame())
        self.assertEqual(screen.state,'network_error');self.assertEqual(screen.matches['network_confirm'].center,(575,355))
    def test_translated_scaled_dialog_preserves_right_button_location(self):
        from network_notice import network_confirm
        for offset,scale,want in [((180,60),1,(505,285)),((260,180),.75,(504,349)),((100,70),1.25,(506,351))]:
            point=network_confirm(network_frame(offset,scale));self.assertIsNotNone(point)
            self.assertLessEqual(abs(point[0]-want[0])+abs(point[1]-want[1]),3)
    def test_missing_text_dim_or_wrong_button_is_rejected(self):
        from network_notice import network_confirm
        for kind in ('text','dim','gray','swapped'):
            im=network_frame()
            if kind=='text':im[197:245,315:645]=(146,176,196)
            if kind=='dim':im=(im*.4).astype('uint8')
            if kind=='gray':im[325:385,495:655]=cv2.cvtColor(cv2.cvtColor(im[325:385,495:655],cv2.COLOR_BGR2GRAY),cv2.COLOR_GRAY2BGR)
            if kind=='swapped':im[325:385,495:655]=im[325:385,305:465]
            self.assertIsNone(network_confirm(im),kind)
    def test_collector_stops_before_any_game_action_on_network_modal(self):
        from collector import Collector
        from vision import Vision
        a,d,r,taps=recovery();d.capture=lambda:network_frame()
        c=Collector(d,Vision(),a.stop,lambda _:None)
        with self.assertRaisesRegex(Halt,'네트워크'):c.screen()
        self.assertEqual(taps,[])
    def test_disabled_confirm_does_not_fall_through_to_exit_dialog(self):
        from vision import Vision
        im=network_frame();im[325:385,495:655]=cv2.cvtColor(cv2.cvtColor(im[325:385,495:655],cv2.COLOR_BGR2GRAY),cv2.COLOR_GRAY2BGR)
        screen=Vision().recognize(im)
        self.assertEqual(screen.state,'network_error');self.assertNotIn('network_confirm',screen.matches)
