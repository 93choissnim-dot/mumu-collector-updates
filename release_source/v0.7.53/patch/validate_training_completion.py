"""Numeric completion evidence, bounded input and crash/resume regression."""
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

    def test_stable_level_rise_finishes_with_active_button_after_one_input(self):
        device=TrainingDevice();collector,result=self.run_claim(device)
        self.assertEqual(result,'collected');self.assertEqual(device.claims,1)
        self.assertFalse(collector.action_state.pending('training'))

    def test_arbitrary_changed_pixels_and_empty_button_are_not_numeric_proof(self):
        device=TrainingDevice((652,652),False)
        collector,result=self.run_claim(device)
        self.assertEqual(result,'deferred');self.assertEqual(device.claims,1)
        self.assertTrue(collector.action_state.pending('training'))

    def test_legacy_pending_never_reclicks_or_infers_old_success(self):
        state=ActionState();state.reserve('training')
        device=TrainingDevice();collector,result=self.run_claim(device,state)
        self.assertEqual(result,'deferred');self.assertEqual(device.claims,0)

    def test_preinput_baseline_is_durable_and_resume_confirms_without_input(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'actions.json';state=ActionState(path)
            device=TrainingDevice((652,652));collector,result=self.run_claim(device,state)
            self.assertEqual(result,'deferred');self.assertEqual(device.claims,1)
            stored=ActionState(path).pending('training')
            self.assertEqual(stored.get('evidence',{}).get('training_level'),652)
            device=TrainingDevice((653,));collector,result=self.run_claim(device,ActionState(path))
            self.assertEqual(result,'collected');self.assertEqual(device.claims,0)

    def test_decreasing_level_does_not_confirm(self):
        collector,result=self.run_claim(TrainingDevice((652,651)))
        self.assertEqual(result,'deferred');self.assertTrue(collector.action_state.pending('training'))

    def test_multi_level_jump_does_not_confirm_single_training_input(self):
        collector,result=self.run_claim(TrainingDevice((652,655)))
        self.assertEqual(result,'deferred')

    def test_empty_legacy_pending_object_never_authorizes_new_input(self):
        state=ActionState();state.update('training',pending={'claim':{}})
        device=TrainingDevice();collector,result=self.run_claim(device,state)
        self.assertEqual(result,'deferred');self.assertEqual(device.claims,0)

    def test_malformed_saved_baseline_is_deferred_without_input(self):
        for evidence in (None,[],{'training_level':True},{'training_level':'652'}):
            with self.subTest(evidence=evidence):
                state=ActionState();state.update('training',pending={'claim':{'evidence':evidence}})
                device=TrainingDevice();collector,result=self.run_claim(device,state)
                self.assertEqual(result,'deferred');self.assertEqual(device.claims,0)

    def test_single_rise_frame_cannot_confirm(self):
        class Flicker(TrainingDevice):
            after=0
            def capture(self):
                image=super().capture()
                if self.claims:
                    self.after+=1
                    return training_frame(653 if self.after==3 else 652)
                return image
        device=Flicker();collector,result=self.run_claim(device)
        self.assertEqual(result,'deferred');self.assertEqual(device.claims,1)

    def test_unreadable_baseline_blocks_input(self):
        class Blank(TrainingDevice):
            def capture(self):
                self.clock+=.1
                return np.zeros((540,960,3),np.uint8)
        device=Blank();collector,result=self.run_claim(device)
        self.assertEqual(result,'deferred');self.assertEqual(device.claims,0)

    def test_fresh_guard_rejects_changing_baseline(self):
        class Changing(TrainingDevice):
            captures=0
            def capture(self):
                self.clock+=.1;self.captures+=1
                return training_frame(653 if self.captures%3==0 else 652)
        device=Changing();collector,result=self.run_claim(device)
        self.assertEqual(result,'deferred');self.assertEqual(device.claims,0)
        self.assertFalse(collector.action_state.pending('training'))

    def test_request_callback_sees_durable_baseline_before_device_input(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'actions.json';state=ActionState(path);device=TrainingDevice()
            events=[]
            def evidence(phase,task,slot,entry):
                if phase=='requested':
                    events.append((device.claims,ActionState(path).pending(task)['evidence']['training_level']))
            state.on_input_evidence=evidence
            self.run_claim(device,state)
            self.assertEqual(events,[(0,652)])

    def test_real_held_out_header_reads_652_and_missing_or_dim_header_is_unknown(self):
        from training_evidence import read_training_level
        crop=cv2.imread(str(Path(__file__).parent/'assets/training_header_652.png'))
        image=np.zeros((540,960,3),np.uint8);image[84:110,625:795]=crop
        self.assertEqual(read_training_level(image),652)
        self.assertIsNone(read_training_level((image*.4).astype(np.uint8)))
        image[84:110,744:795]=0
        self.assertIsNone(read_training_level(image))
        image[84:110,725:795]=0
        self.assertIsNone(read_training_level(image))

if __name__=='__main__':unittest.main()
