"""Duplicate-session recovery using generic text/control crops, no account frame."""
import base64
import json
from pathlib import Path
import unittest
import cv2
import numpy as np
from collector import Halt
from network_notice import detect_network_notice, network_confirm
from validate_network_recovery import recovery
from vision import Vision


def duplicate_frame(offset=(250,130), scale=1.0):
    data=json.loads((Path(__file__).parent/'assets/network_duplicate_controls.json').read_text())
    atlas=cv2.imdecode(np.frombuffer(base64.b64decode(data['png']),np.uint8),1)
    panel=np.full((276,460,3),(146,176,196),np.uint8)
    panel[67:115,65:395]=atlas[:48]
    panel[195:255,150:310]=atlas[48:108,:160]
    panel=cv2.resize(panel,None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA)
    frame=np.zeros((540,960,3),np.uint8)
    x,y=offset;h,w=panel.shape[:2];frame[y:y+h,x:x+w]=panel
    return frame


def duplicate_recovery(stuck=False):
    a,d,r,taps=recovery()
    d.raw_capture=lambda:duplicate_frame() if not taps or stuck else np.zeros((540,960,3),np.uint8)
    return a,d,r,taps


class DuplicateSessionTests(unittest.TestCase):
    def test_duplicate_login_preempts_sleep(self):
        v=Vision();frame=duplicate_frame()
        x,y,right,bottom=v.specs['sleep']['box'];frame[y:bottom,x:right]=v.templates['sleep'][0]
        screen=v.recognize(frame)
        self.assertEqual(screen.state,'network_error')
        self.assertEqual(screen.matches['network_confirm'].center,(480,355))

    def test_scaled_translated_duplicate_dialog(self):
        for offset,scale in [((250,130),1),((200,110),.66),((260,180),.75),((100,70),1.25)]:
            with self.subTest(scale=scale):
                point=network_confirm(duplicate_frame(offset,scale))
                self.assertIsNotNone(point)
                expected=(offset[0]+230*scale,offset[1]+225*scale)
                self.assertLessEqual(max(abs(point[i]-expected[i]) for i in (0,1)),3)

    def test_inactive_button_blocks_actions_without_tapping(self):
        for kind in ('gray','missing'):
            frame=duplicate_frame();box=frame[325:385,400:560]
            box[:]=cv2.cvtColor(cv2.cvtColor(box,cv2.COLOR_BGR2GRAY),cv2.COLOR_GRAY2BGR) if kind=='gray' else (146,176,196)
            with self.subTest(kind=kind):
                notice=detect_network_notice(frame)
                self.assertIsNotNone(notice);self.assertIsNone(notice.confirm)
                self.assertEqual(Vision().recognize(frame).state,'network_error')

    def test_unrelated_beige_confirm_is_not_authorized(self):
        frame=duplicate_frame();frame[197:245,315:645]=(146,176,196)
        self.assertIsNone(detect_network_notice(frame))

    def test_duplicate_confirmation_waits_for_verified_ready(self):
        a,d,r,taps=duplicate_recovery()
        self.assertTrue(r.recover());self.assertEqual(taps,[[480,355]])
        self.assertEqual(a.launches(),[]);self.assertFalse(r.startup.get('network_unconfirmed'))

    def test_watch_detects_confirms_then_reports_recovery(self):
        from game_watch import GameWatch
        a,d,r,taps=duplicate_recovery();now=[0];reports=[]
        watch=GameWatch(reports.append,clock=lambda:now[0]);watch.enable(True)
        def prepare(job,control):
            control.wait=a.stop.wait;a.stop=control;r.stop=control;return r
        job={'id':'a','enabled':True}
        watch.scan([job],prepare)
        self.assertEqual(taps,[[480,355]]);self.assertNotIn('a',watch.last_checked)
        self.assertIn('재접속 결과 확인 중',reports[-1])
        for _ in range(2):now[0]+=1;watch.scan([job],prepare)
        self.assertIn('재접속 완료',reports[-1]);self.assertEqual(len(taps),1)

    def test_duplicate_confirm_exit_relaunches_exact_game(self):
        import validate_game_recovery as fixtures
        a,d,r,taps=duplicate_recovery();original=a.run
        def run(args,**kwargs):
            result=original(args,**kwargs)
            if args[2:5]==['shell','input','tap']:a.focus=fixtures.HOME;a.alive=False
            return result
        a.run=run
        self.assertTrue(r.recover());self.assertEqual(taps,[[480,355]])
        self.assertEqual(len(a.launches()),1)

    def test_high_resolution_duplicate_confirm(self):
        a,d,r,taps=duplicate_recovery()
        d.raw_capture=lambda:cv2.resize(duplicate_frame(),(1920,1080)) if not taps else np.zeros((1080,1920,3),np.uint8)
        self.assertTrue(r.recover());self.assertEqual(taps,[[960,710]])

    def test_persistent_duplicate_never_reconfirms_across_recovery(self):
        from game_recovery import GameRecovery
        a,d,r,taps=duplicate_recovery(stuck=True)
        with self.assertRaises(Halt):r.recover()
        fresh=GameRecovery(d,r.vision,a.stop,lambda:None,lambda _:None,clock=lambda:a.tick);fresh.startup=r.startup
        with self.assertRaises(Halt):fresh.recover()
        self.assertEqual(taps,[[480,355]])

    def test_changed_dialog_at_final_capture_sends_no_input(self):
        a,d,r,taps=duplicate_recovery();frames=[duplicate_frame(),duplicate_frame(),np.zeros((540,960,3),np.uint8)]
        d.raw_capture=lambda:frames.pop(0) if frames else np.zeros((540,960,3),np.uint8)
        r.recover();self.assertEqual(taps,[])

    def test_disabled_button_at_final_capture_sends_no_input(self):
        a,d,r,taps=duplicate_recovery();disabled=duplicate_frame()
        disabled[325:385,400:560]=(146,176,196)
        frames=[duplicate_frame(),duplicate_frame(),disabled]
        d.raw_capture=lambda:frames.pop(0) if frames else np.zeros((540,960,3),np.uint8)
        r.recover();self.assertEqual(taps,[])

    def test_uncertain_input_is_not_repeated(self):
        a,d,r,taps=duplicate_recovery(stuck=True);original=a.run
        def run(args,**kwargs):
            result=original(args,**kwargs)
            if args[2:5]==['shell','input','tap']:raise TimeoutError('transport acknowledgement lost')
            return result
        a.run=run
        with self.assertRaises(TimeoutError):r.recover()
        self.assertTrue(r.startup.get('network_unconfirmed'))
        with self.assertRaises(Halt):r.recover()
        self.assertEqual(taps,[[480,355]])

    def test_paused_watch_sends_no_input(self):
        from game_watch import GameWatch
        from run_control import RunControl
        a,d,r,taps=duplicate_recovery();parent=RunControl();parent.pause()
        watch=GameWatch(lambda _:None);watch.enable(True)
        watch.scan([{'id':'a','enabled':True}],lambda job,control:self.fail('paused watcher prepared recovery'),parent)
        self.assertEqual(taps,[])

    def test_stop_at_final_capture_sends_no_input(self):
        a,d,r,taps=duplicate_recovery();captures=[]
        def capture():
            captures.append(1)
            if len(captures)==3:a.stop.set()
            return duplicate_frame()
        d.raw_capture=capture
        with self.assertRaises(Halt):r.recover()
        self.assertEqual(taps,[])


if __name__=='__main__':unittest.main()
