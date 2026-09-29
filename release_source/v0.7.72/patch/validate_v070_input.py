"""Final input recognition survives durable reservation and slow capture guards."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from action_state import ActionState
from adb_device import AdbDevice
from collector import Collector, Halt, ScreenChanged
from run_control import RunControl, ResumeRecognition
from vision import Match, Screen


class FinalInputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'actions.json'
        self.state = ActionState(self.path, 'probe')
        self.stop = RunControl()
        self.page = 'farm_ready'
        self.matches = {'ready_farm': Match('ready_farm', 1, 0, (780, 499)),
                        'room_farm': Match('room_farm', 1, 0, (20, 20))}
        self.inputs = []
        owner = self

        class Transport:
            stop = owner.stop
            def run(self, args, **kwargs):
                if 'dumpsys' in args:
                    return b'mCurrentFocus=Window{a u0 com.nns.genesis/Main}'
                if 'input' in args:
                    owner.inputs.append((owner.page, tuple(args[-2:])))
                return b''

        self.device = AdbDevice(Transport(), '127.0.0.1:16384')
        self.device.package = 'com.nns.genesis'
        self.device.size = (960, 540)
        self.device.raw_capture = lambda: np.zeros((540, 960, 3), np.uint8)
        vision = SimpleNamespace(recognize=lambda image: Screen(self.page, dict(self.matches)))
        self.collector = Collector(self.device, vision, self.stop, lambda _: None)
        self.original = self.collector.screen()

    def reserve_after(self, change):
        replace = Path.replace
        def save_and_change(source, target):
            result = replace(source, target)
            change()
            return result
        with patch.object(Path, 'replace', save_and_change):
            return self.collector.tap(self.original, 'ready_farm', required=('room_farm',),
                                      before_input=lambda: self.state.reserve('farm'))

    def assert_pending_without_input(self):
        self.assertEqual(self.inputs, [])
        self.assertTrue(ActionState(self.path, 'probe').pending('farm'))

    def test_same_package_page_change_during_durable_reserve_blocks_touch(self):
        with self.assertRaises(ScreenChanged):
            self.reserve_after(lambda: setattr(self, 'page', 'daily_shop_confirm'))
        self.assert_pending_without_input()

    def test_button_disappearing_during_reserve_blocks_touch(self):
        with self.assertRaises(ScreenChanged):
            self.reserve_after(lambda: self.matches.pop('ready_farm'))
        self.assert_pending_without_input()

    def test_conflicting_button_after_reserve_blocks_touch(self):
        with self.assertRaises(Halt):
            self.reserve_after(lambda: self.matches.update(
                empty_farm=Match('empty_farm', 1, 0, (780, 499))))
        self.assert_pending_without_input()

    def test_required_marker_disappearing_after_reserve_blocks_touch(self):
        with self.assertRaises(ScreenChanged):
            self.reserve_after(lambda: self.matches.pop('room_farm'))
        self.assert_pending_without_input()

    def test_current_button_position_is_used_after_reserve(self):
        self.reserve_after(lambda: self.matches.update(
            ready_farm=Match('ready_farm', 1, 0, (800, 490))))
        self.assertEqual(self.inputs, [('farm_ready', (800, 490))])
        self.assertTrue(ActionState(self.path, 'probe').pending('farm'))

    def test_screen_change_during_evidence_encoding_blocks_fixed_point(self):
        frame = self.collector.trace.frame
        def evidence(image, screen):
            frame(image, screen)
            self.page = 'daily_shop_confirm'
        with patch.object(self.collector.trace, 'frame', evidence):
            with self.assertRaises(ScreenChanged):
                self.collector.tap(self.original, point=(780, 499),
                                   before_input=lambda: self.state.reserve('farm'))
        self.assert_pending_without_input()

    def test_stop_during_reserve_preserves_pending_without_touch(self):
        with self.assertRaises(Halt):
            self.reserve_after(self.stop.set)
        self.assert_pending_without_input()

    def test_pause_resume_during_reserve_requires_replanning(self):
        def transition():
            self.stop.pause()
            self.stop.resume()
        with self.assertRaises(ResumeRecognition):
            self.reserve_after(transition)
        self.assert_pending_without_input()


class CaptureAgeTests(unittest.TestCase):
    def setUp(self):
        self.clock = [100.]
        self.device = AdbDevice(SimpleNamespace(stop=RunControl()), '127.0.0.1:16384')
        self.device.size = (960, 540)
        self.device.raw_capture = lambda: np.zeros((540, 960, 3), np.uint8)
        self.timer = patch('adb_device.time.monotonic', side_effect=lambda: self.clock[0])
        self.timer.start()
        self.addCleanup(self.timer.stop)

    def test_slow_post_capture_guard_does_not_refresh_old_pixels(self):
        calls = [0]
        def guard():
            calls[0] += 1
            if calls[0] == 2:
                self.clock[0] += 7
        self.device.guard_package = guard
        self.device.capture()
        with self.assertRaises(Halt):
            self.device.position((780, 499))

    def test_slow_capture_transport_counts_toward_pixel_age(self):
        self.device.guard_package = lambda: None
        def capture():
            self.clock[0] += 7
            return np.zeros((540, 960, 3), np.uint8)
        self.device.raw_capture = capture
        self.device.capture()
        with self.assertRaises(Halt):
            self.device.position((780, 499))

    def test_binding_guard_delay_does_not_refresh_old_pixels(self):
        calls = [0]
        def package():
            calls[0] += 1
            if calls[0] == 2:
                self.clock[0] += 7
            return 'com.nns.genesis'
        self.device.current_package = package
        self.device.bind_game(SimpleNamespace(recognize=lambda im: Screen('main', {})))
        with self.assertRaises(Halt):
            self.device.position((780, 499))


if __name__ == '__main__':
    unittest.main()
