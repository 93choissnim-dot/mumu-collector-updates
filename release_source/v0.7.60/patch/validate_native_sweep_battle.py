"""Real 213124 control pixels: enabled sweep and treasure battle identity."""
from pathlib import Path
import unittest
import cv2
import numpy as np
from vision import Vision
import tempfile,threading
from extra_collector import ExtraCollector
from daily_state import DailyLedger,korea_day

class NativeSweepBattleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v=Vision();cls.atlas=cv2.imdecode(np.fromfile(Path(__file__).parent/'assets/native_213124_controls.png',np.uint8),1)
    def rendered(self,*names):
        im=np.full((540,960,3),110,np.uint8)
        for name in names:
            x,y,r,b=self.v.daily.specs[name]['box'];im[y:b,x:r]=self.v.daily.templates[name][0]
        return im
    def sweep(self):
        im=np.full((540,960,3),110,np.uint8)
        im[131:158,294:336]=self.atlas[0:27,100:142]
        im[130:160,647:679]=self.atlas[34:64,100:132]
        im[367:397,453:507]=self.atlas[0:30,0:54]
        return im
    def battle(self,skip=True):
        names=['treasure_battle_header','treasure_battle_hud']
        if skip:names.append('treasure_battle_skip')
        return self.rendered(*names)
    def test_native_enabled_sweep_at_common_capture_sizes(self):
        for width in (960,1280,1920):
                with self.subTest(width=width):
                    s=self.v.recognize(cv2.resize(self.sweep(),(width,width*9//16)))
                    self.assertEqual(s.state,'daily_sweep')
                    self.assertIn('daily_sweep_action',s.matches)
    def test_disabled_or_missing_sweep_never_clickable(self):
        for mode in ('gray','dark','missing'):
            im=self.sweep();p=im[350:413,383:575]
            if mode=='gray':p[:]=cv2.cvtColor(cv2.cvtColor(p,cv2.COLOR_BGR2GRAY),cv2.COLOR_GRAY2BGR)
            elif mode=='dark':p[:]=(p*.35).astype(np.uint8)
            else:p[:]=110
            with self.subTest(mode=mode):self.assertNotIn('daily_sweep_action',self.v.recognize(im).matches)
    def test_native_treasure_battle_is_recognized(self):
        for width in (960,1280,1920):
            s=self.v.recognize(cv2.resize(self.battle(),(width,width*9//16)))
            self.assertEqual(s.state,'daily_battle')
            self.assertIn('daily_battle_skip',s.matches)
    def test_partial_treasure_identity_never_authorizes_skip(self):
        for box in ((30,17,140,45),(348,14,378,48)):
            im=self.battle();x,y,r,b=box;im[y:b,x:r]=110
            s=self.v.recognize(im)
            self.assertNotEqual(s.state,'daily_battle')
    def test_treasure_sequence_remains_battle_when_skip_disappears(self):
        for i,skip in enumerate((False,False,True)):
            with self.subTest(frame=i):
                s=self.v.recognize(self.battle(skip))
                self.assertEqual(s.state,'daily_battle')
                if i<2:self.assertNotIn('daily_battle_skip',s.matches)
    def test_native_battle_waits_for_visible_skip_then_confirms_result(self):
        v=self.v
        def rendered(*names):
            im=np.full((540,960,3),110,np.uint8)
            for name in names:
                x,y,r,b=v.daily.specs[name]['box'];im[y:b,x:r]=v.daily.templates[name][0]
            return im
        class Device:
            captures=0;clicks=0;result_frames=0
            def capture(d):
                d.captures+=1
                if d.clicks:
                    d.result_frames+=1
                    return rendered('battle_result') if d.result_frames<=3 else rendered('room_treasure','d_close')
                return test.battle(d.captures>=5)
            def click(d,point):
                assert d.captures>=5,'clicked before SKIP appeared'
                assert 17<=point[0]<=143 and 486<=point[1]<=530,'wrong control'
                d.clicks+=1
        test=self;device=Device();clock=[0.]
        with tempfile.TemporaryDirectory() as tmp:
            c=ExtraCollector(device,v,threading.Event(),lambda _:None)
            c.daily_ident='test';c.daily_task='daily_dungeons';c.daily_step='treasure';c.daily_day=korea_day()
            c.daily_ledger=DailyLedger(Path(tmp)/'ledger.json');c.daily_checkpoint('uncertain',pending='d_enter')
            c.now=lambda:clock[0];c.pause=lambda n:clock.__setitem__(0,clock[0]+n)
            screen,confirmed=c.daily_combat({'daily_room_treasure'},on_result=lambda:c.daily_confirm_input(c.daily_combat_evidence))
            self.assertTrue(confirmed);self.assertEqual(screen.state,'daily_room_treasure')
            self.assertEqual(device.clicks,1);self.assertIsNone(c.daily_detail().get('pending'))

if __name__=='__main__':unittest.main()
