"""Image-driven free-key -> sweep -> reward -> exhaustion without mocked actions."""
from pathlib import Path
import tempfile,threading,unittest
import cv2,numpy as np
from vision import Vision
from extra_collector import ExtraCollector
from daily_state import DailyLedger,korea_day
from collector import Halt
from validate_overlays import composite

class SweepTransitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.vision=Vision()
    def daily_image(self,*names):
        im=np.full((540,960,3),110,np.uint8)
        for name in names:
            x,y,r,b=self.vision.daily.specs[name]['box'];im[y:b,x:r]=self.vision.daily.templates[name][0]
        return im
    def run_route(self,*,returns_room=False,reward_delay=0,stuck=False,stop_after_key=False,key='equipment',wrong_room=False):
        test=self;v=self.vision
        class Device:
            clock=0;state='room';free=True;sweeps=0;claims=0;opens=0;due=None
            stop=threading.Event()
            def capture(d):
                d.clock+=.08
                if d.due is not None and d.clock>=d.due and not stuck:d.state='reward';d.due=None
                if d.state=='reward':return composite(v,'reward_close')
                if d.state=='room':return test.daily_image('room_'+('summon' if wrong_room and not d.free else key),'d_close','d_sweep_open',*(('d_count_0','d_free_1') if d.free else ('d_enter',)))
                if d.state=='free':return cv2.imdecode(np.fromfile(Path(__file__).parent/'assets'/('diagnostic_sweep_'+key+'.png'),np.uint8),1)
                if d.state=='empty':return test.daily_image('sweep_title','sweep_close','sweep_count_0','sweep_free_0')
                return test.daily_image('sweep_title','sweep_close','sweep_action')
            def click(d,point):
                assert not d.stop.is_set()
                x,y=point
                if d.state=='room':d.opens+=1;d.state='free' if d.free else 'ready'
                elif d.state=='free':
                    d.claims+=1;d.free=False;d.state='room' if returns_room else 'ready'
                    if stop_after_key:d.stop.set()
                elif d.state=='ready':
                    d.sweeps+=1
                    if d.due is not None:raise AssertionError('duplicate pending sweep')
                    d.due=d.clock+reward_delay
                elif d.state=='reward':d.state='empty'
                elif d.state=='empty':d.state='room'
        d=Device();d.stop=threading.Event()
        with tempfile.TemporaryDirectory() as tmp:
            c=ExtraCollector(d,v,d.stop,lambda _:None);c.now=lambda:d.clock;c.pause=lambda n:setattr(d,'clock',d.clock+n)
            c.daily_task='daily_dungeons';c.daily_step=key;c.daily_ident='test';c.daily_day=korea_day()
            c.daily_ledger=DailyLedger(Path(tmp)/'daily.json');c.daily_performed=False;c.daily_reward_seen=False
            c.daily_find_dungeon=lambda _:c.daily_wait({'daily_room_'+key})
            c.daily_close_room=lambda _:None
            error=None
            try:c.daily_dungeon(key)
            except Halt as exc:error=exc
            return d,c.daily_done(key),c.daily_detail(),error
    def test_same_modal_free_key_runs_sweep_and_confirms_exhaustion(self):
        d,done,detail,error=self.run_route()
        self.assertIsNone(error);self.assertTrue(done);self.assertEqual((d.claims,d.sweeps),(1,1))
    def test_key_returning_to_room_reopens_sweep_and_finishes(self):
        d,done,detail,error=self.run_route(returns_room=True)
        self.assertIsNone(error);self.assertTrue(done);self.assertEqual((d.claims,d.sweeps,d.opens),(1,1,2))
    def test_delayed_reward_does_not_abort_or_repeat_sweep(self):
        d,done,detail,error=self.run_route(reward_delay=3)
        self.assertIsNone(error);self.assertTrue(done);self.assertEqual(d.sweeps,1)
    def test_unchanged_button_never_authorizes_duplicate_sweep(self):
        d,done,detail,error=self.run_route(stuck=True)
        self.assertIsNotNone(error);self.assertFalse(done);self.assertEqual(d.sweeps,1)
        self.assertEqual(detail.get('pending'),'sweep_action');self.assertLess(d.clock,50)
    def test_summon_free_key_return_and_delayed_reward_complete_together(self):
        d,done,detail,error=self.run_route(key='summon',returns_room=True,reward_delay=3)
        self.assertIsNone(error);self.assertTrue(done);self.assertEqual((d.claims,d.sweeps,d.opens),(1,1,2))
    def test_different_room_after_key_never_opens_or_sweeps(self):
        d,done,detail,error=self.run_route(returns_room=True,wrong_room=True)
        self.assertIsNotNone(error);self.assertFalse(done);self.assertEqual((d.claims,d.sweeps,d.opens),(1,0,1))
    def test_stop_after_key_prevents_sweep(self):
        d,done,detail,error=self.run_route(stop_after_key=True)
        self.assertIsNotNone(error);self.assertFalse(done);self.assertEqual((d.claims,d.sweeps),(1,0))

if __name__=='__main__':unittest.main()
