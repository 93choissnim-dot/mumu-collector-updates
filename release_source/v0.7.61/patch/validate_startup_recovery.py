"""Only the supplied download notice and known offline reward can be confirmed."""
import unittest
from pathlib import Path
from types import SimpleNamespace
import cv2
import numpy as np
from collector import Halt
import validate_game_recovery as fixtures

def download_frame():
    atlas=cv2.imread(str(Path(__file__).parent/'assets/start_download_controls.png'))
    im=np.full((540,960,3),180,np.uint8)
    im[210:237,388:573]=atlas[:27];im[327:388,399:559]=atlas[27:88,:160]
    return im

class StartupRecoveryTests(unittest.TestCase):
    def test_exact_notice_and_active_button_required(self):
        from startup_notice import download_confirm
        im=download_frame();self.assertIsNotNone(download_confirm(im))
        im[210:237,388:573]=180;self.assertIsNone(download_confirm(im))
        im=download_frame();im[327:388,399:559]=180;self.assertIsNone(download_confirm(im))
        self.assertIsNone(download_confirm((download_frame()*.4).astype('uint8')))
    def test_download_confirm_once_then_wait_for_normal_screen(self):
        a,d,r,_=fixtures.GameRecoveryTests().setup_recovery();a.states=['unknown'];taps=[];frames=[download_frame(),download_frame()]
        d.raw_capture=lambda:frames.pop(0) if frames else np.zeros((540,960,3),np.uint8)
        r.vision.recognize=lambda im:SimpleNamespace(state='unknown' if im.mean()>0 else 'menu',matches={})
        original=a.run
        def run(args,**kw):
            if args[2:5]==['shell','input','tap']:taps.append(args[2:]);return b''
            return original(args,**kw)
        a.run=run
        self.assertTrue(r.recover());self.assertEqual(len(taps),1);self.assertEqual(taps[0][-2:],[479,357])
    def test_download_dialog_that_does_not_close_is_not_clicked_twice(self):
        a,d,r,_=fixtures.GameRecoveryTests().setup_recovery();a.states=['unknown'];taps=[]
        d.raw_capture=download_frame;original=a.run
        def run(args,**kw):
            if args[2:5]==['shell','input','tap']:taps.append(args);return b''
            return original(args,**kw)
        a.run=run
        with self.assertRaises(Halt):r.recover()
        self.assertEqual(len(taps),1)
    def test_offline_reward_confirm_then_continue_to_menu(self):
        a,d,r,_=fixtures.GameRecoveryTests().setup_recovery();taps=[];a.states=['offline_reward']
        def recognize(im):return SimpleNamespace(state='menu' if taps else 'offline_reward',matches={'offline_confirm':SimpleNamespace(center=(480,400))})
        r.vision.recognize=recognize;original=a.run
        def run(args,**kw):
            if args[2:5]==['shell','input','tap']:taps.append(args);return b''
            return original(args,**kw)
        a.run=run
        self.assertTrue(r.recover());self.assertEqual(len(taps),1)

class InterruptedStartupTests(unittest.TestCase):
    def test_cancel_after_launch_can_continue_exact_download_prompt(self):
        a,d,r,_=fixtures.GameRecoveryTests().setup_recovery();a.states=['unknown'];taps=[];cancel=[True]
        d.raw_capture=lambda:download_frame() if not taps else np.zeros((540,960,3),np.uint8)
        r.vision.recognize=lambda im:SimpleNamespace(state='unknown' if im.mean()>0 else 'menu',matches={})
        original=a.run
        def run(args,**kw):
            if args[2:5]==['shell','input','tap']:taps.append(args);return b''
            result=original(args,**kw)
            if args[2:5]==['shell','am','start'] and cancel[0]:a.stop.set()
            return result
        a.run=run
        with self.assertRaises(Halt):r.recover()
        a.stop.clear();cancel[0]=False
        self.assertTrue(r.recover());self.assertEqual(len(a.launches()),1);self.assertEqual(len(taps),1)
    def test_last_observed_edition_replaces_stale_saved_edition(self):
        a,d,r,_=fixtures.GameRecoveryTests().setup_recovery();a.focus='com.nns.genesis.onestore'
        self.assertFalse(r.recover())
        self.assertEqual(r.observed_package,'com.nns.genesis.onestore')
