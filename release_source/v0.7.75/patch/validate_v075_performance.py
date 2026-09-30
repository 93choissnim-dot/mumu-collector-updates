"""Reference preparation must be reused without changing recognition decisions."""
from pathlib import Path
import unittest
from unittest.mock import patch
import cv2,numpy as np
from vision import Vision

class ReferenceReuseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.v=Vision()
    def test_free_page_does_not_resize_immutable_templates_per_frame(self):
        frame=cv2.imdecode(np.fromfile(Path(__file__).parent/'assets/free_daily_fixture_cube_card.png',np.uint8),1)
        with patch('free_daily_vision.cv2.resize',wraps=cv2.resize) as resize:
            a=self.v.free_daily.recognize(frame);b=self.v.free_daily.recognize(frame.copy())
        self.assertEqual(a,b);self.assertEqual(a[0],'free_store')
        self.assertEqual(resize.call_count,0,'reference scale preparation repeated for each frame')
    def test_top_icons_do_not_rebuild_reference_masks_per_frame(self):
        frame=np.zeros((540,960,3),np.uint8)
        for key,(ref,(x,y,r,b)) in self.v.top_bar.references.items():frame[y:b,x:r]=ref
        with patch('top_bar.cv2.dilate',wraps=cv2.dilate) as dilate:
            a=self.v.top_bar.recognize(frame);b=self.v.top_bar.recognize(frame.copy())
        self.assertEqual(a,b);self.assertTrue(a[0]);self.assertEqual(dilate.call_count,0)
