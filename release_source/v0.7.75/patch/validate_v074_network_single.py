"""One-button disconnect dialog: recorded game UI without account/desktop data."""
from pathlib import Path
import unittest
import cv2
import numpy as np
from collector import Halt
from network_notice import detect_network_notice, network_confirm
from validate_network_recovery import recovery, network_frame
from vision import Vision


def single_frame(offset=(250,132), scale=1.0):
    panel=cv2.imdecode(np.fromfile(Path(__file__).parent/'assets/network_single_confirm_panel.png',np.uint8),1)
    panel=cv2.resize(panel,None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA)
    frame=np.zeros((540,960,3),np.uint8)
    x,y=offset;h,w=panel.shape[:2];frame[y:y+h,x:x+w]=panel
    return frame


def single_recovery(stuck=False):
    a,d,r,taps=recovery()
    d.raw_capture=lambda:single_frame() if not taps or stuck else np.zeros((540,960,3),np.uint8)
    return a,d,r,taps


class SingleNetworkTests(unittest.TestCase):
    def test_reported_single_button_dialog_preempts_underlying_sleep(self):
        v=Vision();frame=single_frame()
        x,y,right,bottom=v.specs['sleep']['box']
        frame[y:bottom,x:right]=v.templates['sleep'][0]
        screen=v.recognize(frame)
        self.assertEqual(screen.state,'network_error')
        self.assertEqual(screen.matches['network_confirm'].center,(480,357))

    def test_scaled_and_translated_single_dialog_coordinates(self):
        for offset,scale in [((250,132),1),((260,180),.75),((100,70),1.25)]:
            with self.subTest(offset=offset,scale=scale):
                point=network_confirm(single_frame(offset,scale))
                self.assertIsNotNone(point)
                expected=(offset[0]+230*scale,offset[1]+225*scale)
                self.assertLessEqual(max(abs(point[i]-expected[i]) for i in (0,1)),3)

    def test_legacy_two_button_dialog_keeps_right_button(self):
        self.assertEqual(network_confirm(network_frame()),(575,355))

    def test_disabled_or_missing_single_button_blocks_other_actions(self):
        for kind in ('gray','missing'):
            with self.subTest(kind=kind):
                frame=single_frame();box=frame[327:387,400:560]
                box[:]=cv2.cvtColor(cv2.cvtColor(box,cv2.COLOR_BGR2GRAY),cv2.COLOR_GRAY2BGR) if kind=='gray' else (146,176,196)
                notice=detect_network_notice(frame)
                self.assertIsNotNone(notice);self.assertIsNone(notice.confirm)
                self.assertEqual(Vision().recognize(frame).state,'network_error')

    def test_button_without_disconnect_text_is_not_authorized(self):
        frame=single_frame();frame[199:247,315:645]=(146,176,196)
        self.assertIsNone(detect_network_notice(frame))

    def test_watch_confirms_reported_dialog_without_relaunch(self):
        from game_watch import GameWatch
        a,d,r,taps=single_recovery();watch=GameWatch(lambda _:None);watch.enable(True)
        def prepare(job,control):
            control.wait=a.stop.wait;a.stop=control;r.stop=control;return r
        watch.scan([{'id':'a','enabled':True}],prepare)
        self.assertEqual(taps,[[480,357]]);self.assertEqual(a.launches(),[])

    def test_high_resolution_device_receives_scaled_center(self):
        a,d,r,taps=single_recovery()
        d.raw_capture=lambda:cv2.resize(single_frame(),(1920,1080)) if not taps else np.zeros((1080,1920,3),np.uint8)
        self.assertTrue(r.recover());self.assertEqual(taps,[[960,714]])

    def test_changed_dialog_before_dispatch_sends_no_input(self):
        a,d,r,taps=single_recovery();frames=[single_frame(),single_frame(),network_frame()]
        d.raw_capture=lambda:frames.pop(0) if frames else np.zeros((540,960,3),np.uint8)
        r.recover();self.assertEqual(taps,[])

    def test_persistent_single_dialog_never_repeats_confirmation(self):
        from game_recovery import GameRecovery
        a,d,r,taps=single_recovery(stuck=True)
        with self.assertRaises(Halt):r.recover()
        fresh=GameRecovery(d,r.vision,a.stop,lambda:None,lambda _:None,clock=lambda:a.tick);fresh.startup=r.startup
        with self.assertRaises(Halt):fresh.recover()
        self.assertEqual(taps,[[480,357]])


if __name__=='__main__':unittest.main()
