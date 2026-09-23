"""Recognition and recovery regressions; no external files or live game input."""
import json
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import cv2
import numpy as np
from collector import Collector, Halt
from extra_collector import ExtraCollector
from vision import Vision, Screen, Match
from diagnostics import save_collection_failure, export_diagnostics


def composite(vision, *names):
    image = np.full((540, 960, 3), 115, np.uint8)
    for name in names:
        if name.startswith('top_'):
            tile,box=vision.top_bar.references[name[4:]];x1,y1,x2,y2=box
            image[y1:y2,x1:x2]=tile;continue
        templates=vision if name in vision.specs else vision.autumn
        x1, y1, x2, y2 = templates.specs[name]['box']
        image[y1:y2, x1:x2] = templates.templates[name][0]
    return image


class RecognitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vision = Vision()

    def test_offline_requires_all_three_modal_markers(self):
        names = ('offline_title', 'offline_rewards', 'offline_confirm')
        for width in (640, 960, 1280):
            im = cv2.resize(composite(self.vision, *names), (width, width*9//16))
            s = self.vision.recognize(im)
            self.assertEqual(s.state, 'offline_reward')
            self.assertTrue(460 < s.matches['offline_confirm'].center[0] < 500)
        for missing in names:
            im = composite(self.vision, *(n for n in names if n != missing))
            self.assertNotEqual(self.vision.recognize(im).state, 'offline_reward')

    def test_offline_is_a_valid_game_binding_state(self):
        from adb_device import READY_STATES
        self.assertIn('offline_reward', READY_STATES)

    def test_adb_claim_alternates_do_not_match_inactive_buttons(self):
        # This isolates the legacy cropped-button fallback: mixing an original
        # room label with an ADB button is not a uniformly rendered full frame.
        # Full-screen calibrated classification is covered by validate_photometric.
        legacy=Vision()
        legacy.button_profiles.profiles={}
        for room in ('farm', 'wood'):
            for kind, template in [('ready', 'ready_'+room+'_adb'), ('empty', 'empty_'+room), ('empty', 'empty_'+room+'_video')]:
                for width in (640, 960, 1280):
                    im = composite(self.vision, 'room_'+room, template)
                    s = legacy.recognize(cv2.resize(im, (width, width*9//16)))
                    # Small video text crops lack their real surroundings at 640 px;
                    # native-size positives plus full-frame video replay cover them.
                    if width != 640 or not template.endswith('_video'):
                        self.assertEqual(s.state, room+'_'+kind, (room, template, width, s.state))
                    self.assertNotIn(('empty_' if kind == 'ready' else 'ready_')+room, s.matches)

    def test_ranking_color_shift_preserves_active_empty_distinction(self):
        for kind in ('active', 'empty'):
            image = composite(self.vision, 'x_rank_title', 'x_rank_tab', 'x_rank_'+kind)
            # Measured direct-ADB captures are brighter than the video templates.
            for gain in (1.0, 1.15, 1.22):
                im = np.clip(image.astype(np.float32)*gain, 0, 255).astype(np.uint8)
                s = self.vision.recognize(im)
                self.assertEqual(s.state, 'ranking')
                self.assertIn('x_rank_'+kind, s.matches)
                self.assertNotIn('x_rank_'+('empty' if kind == 'active' else 'active'), s.matches)


class OverlayTests(unittest.TestCase):
    def run_flow(self, collector_type, *, offline_taps=1, equipment_taps=1,
                 initial='sleep', stop_after=False, sequence=None, mode='menu'):
        stop = threading.Event()
        state = SimpleNamespace(value=initial, now=0., actions=[], reads=0, offline=0, equipment=0)
        frames = iter(sequence) if sequence is not None else None
        def capture():
            state.now += .1; state.reads += 1
            value = next(frames, 'main') if frames is not None else state.value
            matches = {}
            if value == 'offline_reward': matches['offline_confirm'] = Match('offline_confirm', 1, 0, (480, 443.5))
            if value == 'main': matches['main_menu'] = Match('main_menu', 1, 0, (920, 28))
            return Screen(value, matches)
        def click(point):
            self.assertFalse(stop.is_set())
            state.actions.append((state.value, point, state.reads))
            if state.value == 'offline_reward':
                self.assertEqual(point, (480, 443.5));state.offline += 1
                if state.offline >= offline_taps: state.value = 'equipment'
                if stop_after: stop.set()
            elif state.value == 'equipment':
                self.assertEqual(point, (940, 350));state.equipment += 1
                if state.equipment >= equipment_taps: state.value = 'main'
            elif state.value == 'main':
                self.assertEqual(point, (920, 28));state.value = 'menu'
            else: self.fail('Unexpected click on '+state.value)
        def drag(a,b):
            self.assertEqual(state.value, 'sleep');state.value = 'offline_reward'
        def pause(n):
            if stop.is_set(): raise Halt('Stopped')
            state.now += n
        device = SimpleNamespace(capture=capture, click=click, drag=drag)
        c = collector_type(device, SimpleNamespace(recognize=lambda x:x), stop, lambda x:None)
        c.pause = pause
        with patch('collector.time.monotonic', lambda:state.now):
            try:
                if mode == 'room':
                    result = c.wait_for_room('farm', allow_exit=True)
                elif mode == 'page':
                    result = c.wait_page({'main'})
                elif mode == 'wait':
                    result = c.wait_for({'main'})
                else:
                    result = c.ensure_menu()
            except Halt:
                result = 'halt'
        return state, result

    def test_wake_offline_equipment_then_menu(self):
        for cls in (Collector, ExtraCollector):
            state, result = self.run_flow(cls)
            self.assertEqual(result.state, 'menu')
            self.assertEqual([s for s, _, _ in state.actions], ['offline_reward','equipment','main'])

    def test_can_start_on_offline_modal(self):
        state, result = self.run_flow(ExtraCollector, initial='offline_reward')
        self.assertEqual(result.state, 'menu');self.assertEqual(state.offline, 1)
        self.assertGreaterEqual(state.actions[0][2], 2)

    def test_each_modal_gets_its_own_retry_budget(self):
        state, result = self.run_flow(ExtraCollector, offline_taps=3, equipment_taps=3)
        self.assertEqual(result.state, 'menu')
        self.assertEqual((state.offline, state.equipment), (3,3))

    def test_stuck_offline_stops_after_three_confirms(self):
        state, result = self.run_flow(ExtraCollector, offline_taps=999)
        self.assertEqual(result, 'halt');self.assertEqual(state.offline, 3)
        self.assertEqual(state.equipment, 0)

    def test_stop_after_confirm_prevents_following_clicks(self):
        state, result = self.run_flow(ExtraCollector, stop_after=True)
        self.assertEqual(result, 'halt');self.assertEqual(len(state.actions), 1)

    def test_transient_modal_is_not_clicked(self):
        for cls, mode in ((Collector, 'wait'), (ExtraCollector, 'page')):
            state, result = self.run_flow(cls, initial='main', mode=mode,
                sequence=['offline_reward','unknown','offline_reward','main','main'])
            self.assertEqual(result.state, 'main');self.assertFalse(state.actions)

    def test_unknown_frame_between_modals_resets_confirmation(self):
        state, result = self.run_flow(ExtraCollector, initial='main', mode='page',
            sequence=['equipment','unknown','equipment','main','main'])
        self.assertEqual(result.state, 'main');self.assertFalse(state.actions)

    def test_main_frames_separated_by_overlay_are_not_consecutive(self):
        state, result = self.run_flow(ExtraCollector, initial='main', mode='page',
            sequence=['main','offline_reward','main','main'])
        self.assertEqual(result.state,'main');self.assertEqual(state.reads,4)

    def test_modal_during_room_wait_is_dismissed_before_exit(self):
        state, result = self.run_flow(Collector, initial='offline_reward', mode='room')
        self.assertEqual(result.state, 'main');self.assertEqual(state.offline, 1)


class DiagnosticTests(unittest.TestCase):
    def test_later_room_failure_does_not_overwrite_earlier_room(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp); ident = 'a'*24
            for room, value in [('farm',20),('wood',80)]:
                save_collection_failure(p, ident, np.full((540,960,3),value,np.uint8),
                    Screen(room+'_wait',{}, {'sample':{'accepted':False}}), 'button missing', room)
            self.assertEqual(json.loads((p/f'last_{ident}_farm_error.json').read_text())['state'],'farm_wait')
            self.assertEqual(json.loads((p/f'last_{ident}_error.json').read_text())['state'],'wood_wait')
            archive = p/'diagnostics.zip';export_diagnostics(p,archive)
            with zipfile.ZipFile(archive) as z:
                for room in ('farm','wood'):
                    for suffix in ('png','json'):self.assertIn(f'last_{ident}_{room}_error.{suffix}',z.namelist())
            with self.assertRaises(ValueError):
                save_collection_failure(p, '../bad', np.zeros((540,960,3),np.uint8),Screen('unknown',{}),'bad')

if __name__ == '__main__': unittest.main()
