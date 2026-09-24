"""Repeatable training donations, fresh screen guards and durable request history."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import cv2
import numpy as np
from action_state import ActionState
from extra_collector import ExtraCollector
from validate_extra import Device


def training_frame(level):
    glyphs=json.loads((Path(__file__).parent/'assets/training_glyphs.json').read_text())
    image=np.full((540,960,3),60,np.uint8)
    label=np.array(glyphs['label'],np.uint8)*180
    image[88:106,655:724]=np.repeat((label+60)[:,:,None],3,axis=2)
    x=728
    for char in str(level):
        glyph=np.array(glyphs[char],np.uint8)*180;h,w=glyph.shape
        image[90:90+h,x:x+w]=np.repeat((glyph+60)[:,:,None],3,axis=2);x+=w+2
    return image


class TrainingDevice(Device):
    def __init__(self,levels=(652,653),active_after=True):
        super().__init__('training');self.state='training';self.levels=levels;self.active_after=active_after
    def capture(self):
        self.clock+=.1
        return training_frame(self.levels[min(self.claims,len(self.levels)-1)])
    def click(self,point):
        self.claims+=1;self.actions.append((self.state,point));self.empty=not self.active_after


class TrainingTests(unittest.TestCase):
    def run_claim(self,device,state=None):
        class Vision:
            def recognize(self,image):return device.screen()
        collector=ExtraCollector(device,Vision(),device.stop,lambda _:None)
        if state is not None:collector.action_state=state
        collector.pause=lambda n:setattr(device,'clock',device.clock+n)
        with patch('extra_collector.time.monotonic',lambda:device.clock):
            result=collector.claim_extra('training',collector.screen())
        return collector,result

    def device(self,**kw):
        d=Device('training',**kw);d.state='training';return d

    def test_repeats_active_donation_until_disabled_without_level_change(self):
        d=self.device(lost=2)
        d.capture=lambda:np.zeros((540,960,3),np.uint8)
        c,r=self.run_claim(d)
        self.assertEqual((r,d.claims),('collected',3));self.assertFalse(c.action_state.pending('training'))

    def test_changing_numbers_do_not_end_active_donation(self):
        d=self.device(lost=2)
        d.capture=lambda:training_frame(999-d.claims*10)
        c,r=self.run_claim(d);self.assertEqual((r,d.claims),('collected',3))

    def test_legacy_pending_allows_guarded_repeat_and_keeps_origin(self):
        state=ActionState();state.reserve('training');old=state.pending('training')['id']
        d=self.device();c,r=self.run_claim(d,state)
        self.assertEqual((r,d.claims),('collected',1))
        entry=c.action_state.get('training')['input_history'][0]
        self.assertEqual(entry['request']['id'],old)
        self.assertFalse(entry['resolution']['confirmed'])
        self.assertEqual(entry['resolution']['source'],'repeatable_training_donation')

    def test_empty_initial_button_skips_without_input(self):
        d=self.device(empty=True);c,r=self.run_claim(d)
        self.assertEqual((r,d.claims),('skipped',0))

    def test_empty_button_resolves_old_pending_without_new_input(self):
        state=ActionState();state.reserve('training');d=self.device(empty=True)
        c,r=self.run_claim(d,state);self.assertEqual((r,d.claims),('collected',0))
        self.assertFalse(state.pending('training'))

    def test_empty_legacy_pending_does_not_block_repeat(self):
        state=ActionState();state.update('training',pending={'claim':{}})
        d=self.device();c,r=self.run_claim(d,state)
        self.assertEqual((r,d.claims),('collected',1))

    def test_other_task_pending_is_unchanged(self):
        state=ActionState();state.reserve('wood');before=state.get('wood')
        self.run_claim(self.device(lost=2),state);self.assertEqual(state.get('wood'),before)

    def test_each_dispatch_has_durable_request(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'actions.json';state=ActionState(path);d=self.device(lost=2)
            click=d.click;ids=[]
            def checked(point):
                request=ActionState(path).pending('training');ids.append(request['id'])
                self.assertEqual(request['evidence']['mode'],'repeatable_donation');click(point)
            d.click=checked
            c,r=self.run_claim(d,state);self.assertEqual(r,'collected');self.assertEqual(len(set(ids)),3)

    def test_stuck_active_button_is_bounded_and_can_retry(self):
        d=self.device(lost=999);state=ActionState()
        c,r=self.run_claim(d,state);self.assertEqual(r,'deferred');self.assertGreater(d.claims,1)
        self.assertLess(d.clock,80);before=d.claims;d.lost=before
        c,r=self.run_claim(d,state);self.assertEqual((r,d.claims),('collected',before+1))

    def test_screen_departure_prevents_further_donation(self):
        d=self.device(unknown=True);c,r=self.run_claim(d)
        self.assertEqual((r,d.claims),('deferred',1))

    def test_fresh_guard_rejects_page_departure(self):
        from vision import Screen
        d=self.device();screen=d.screen;calls=0
        def changing():
            nonlocal calls
            calls+=1
            return screen() if calls<=3 else Screen('menu',{})
        d.screen=changing;c,r=self.run_claim(d);self.assertEqual(d.claims,0)
        self.assertEqual(r,'deferred')

    def test_conflicting_button_markers_never_receive_input(self):
        from vision import Screen,Match
        d=self.device();d.screen=lambda:Screen('training',{n:Match(n,1,0,(400,400)) for n in ('x_train_active','x_train_empty')})
        c,r=self.run_claim(d);self.assertEqual((r,d.claims),('deferred',0))

    def test_stop_after_first_donation_prevents_repeat(self):
        from collector import Halt
        d=self.device(lost=9,stop_after=True)
        with self.assertRaises(Halt):self.run_claim(d)
        self.assertEqual(d.claims,1)

if __name__=='__main__':unittest.main()
