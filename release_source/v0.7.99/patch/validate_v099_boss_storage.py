"""Notification-covered boss selection and bounded Windows journal recovery."""
import base64
import errno
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import cv2
import numpy as np
from vision import Vision,Match
from validate_overlays import composite
import validate_world_boss
from run_journal import RunJournal
from daily_state import LedgerError
from record_storage import save_json

class CoveredCardsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v=Vision()
        cls.refs=json.loads((Path(__file__).parent/'assets/boss_cards.json').read_text())
    def image(self):
        im=composite(self.v,'x_boss_select_title')
        for spec in self.refs.values():
            x,y,r,b=spec['box']
            im[y:b,x:r]=cv2.imdecode(np.frombuffer(base64.b64decode(spec['png']),np.uint8),1)
        # Simulate a banner hiding names and red badges; no personal screenshot.
        im[139:189,220:740]=(25,80,110)
        return im
    def test_covered_names_use_all_lower_labels_and_close(self):
        for width in (640,960,1280):
            s=self.v.recognize(cv2.resize(self.image(),(width,width*9//16)))
            self.assertEqual(s.state,'boss_select')
            self.assertIn('x_boss_notices_unreadable',s.matches)
            for name in ('x_boss_card','x_boss_card_kraken','x_boss_card_void'):
                self.assertGreater(s.matches[name].center[1],189)
    def test_clear_names_keep_safe_card_coordinates_without_unreadable_marker(self):
        im=self.image()
        for name in ('x_boss_card','x_boss_card_kraken','x_boss_card_void'):
            x,y,r,b=self.v.specs[name]['box'];im[y:b,x:r]=self.v.templates[name][0]
        clear=self.v.recognize(im);covered=self.v.recognize(self.image())
        self.assertEqual(clear.state,'boss_select')
        self.assertNotIn('x_boss_notices_unreadable',clear.matches)
        for name in ('x_boss_card','x_boss_card_kraken','x_boss_card_void'):
            self.assertEqual(clear.matches[name].center,covered.matches[name].center)

    def test_any_missing_lower_label_or_close_blocks_fallback(self):
        for spec in self.refs.values():
            im=self.image();x,y,r,b=spec['box'];im[y:b,x:r]=0
            self.assertNotEqual(self.v.recognize(im).state,'boss_select')
    def test_missing_title_or_dim_modal_does_not_authorize_navigation(self):
        im=self.image();im[65:110,110:230]=0
        self.assertNotEqual(self.v.recognize(im).state,'boss_select')
        self.assertNotEqual(self.v.recognize((self.image()*.35).astype(np.uint8)).state,'boss_select')

class CoveredRouteTests(unittest.TestCase):
    def run_flow(self,**options):
        pending=options.pop("pending",False)
        def setup(d,c):
            original=d.screen
            def covered():
                s=original()
                if s.state=='boss_select':
                    for k in list(s.matches):
                        if k.startswith('x_boss_notice_'):del s.matches[k]
                    s.matches['x_boss_notices_unreadable']=Match('x_boss_notices_unreadable',1,0,(0,0))
                return s
            d.screen=covered
            if pending:c.action_state.reserve('worldboss','kraken')
        return validate_world_boss.RouteTests().run_flow(['cerberus','kraken','void'],before_run=setup,**options)
    def test_obscured_notices_check_each_non_preparing_boss_once(self):
        d,c,r=self.run_flow(preparing=['void'],empty=['cerberus'])
        self.assertEqual(d.entered,['cerberus','kraken'])
        self.assertEqual(d.claims,{'cerberus':0,'kraken':1,'void':0})
        self.assertEqual(r,{'worldboss':'collected'})
    def test_obscured_notices_do_not_override_pending_claim(self):
        d,c,r=self.run_flow(preparing=['void'],empty=['cerberus'],pending=True)
        self.assertEqual(d.entered,['cerberus','kraken'])
        self.assertEqual(sum(d.claims.values()),0)
        self.assertEqual(r,{'worldboss':'deferred'})
    def test_all_empty_is_skipped_without_claim(self):
        d,c,r=self.run_flow(empty=['cerberus','kraken','void'])
        self.assertEqual(len(d.entered),3)
        self.assertEqual(sum(d.claims.values()),0)
        self.assertEqual(r,{'worldboss':'skipped'})

class AccessDeniedTests(unittest.TestCase):
    def error(self):
        exc=PermissionError(errno.EACCES,'Access denied');exc.winerror=5;return exc
    def test_transient_access_denied_journal_retries_same_atomic_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'run_progress.json';j=RunJournal(path);j.begin('a',['farm'])
            original=Path.replace;attempts=[]
            def replace(source,target):
                attempts.append(source)
                if len(attempts)<3:raise self.error()
                return original(source,target)
            with patch.object(Path,'replace',replace),patch('time.sleep'):
                j.result('a','farm','collected')
            self.assertEqual(len(attempts),3);self.assertEqual(len(set(attempts)),1)
            self.assertEqual(json.loads(path.read_text())['a']['results'],{'farm':'collected'})
            self.assertEqual(list(Path(directory).iterdir()),[path])
    def test_permanent_access_denied_keeps_journal_and_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'run_progress.json';j=RunJournal(path);j.begin('a',['farm']);before=path.read_bytes()
            with patch.object(Path,'replace',side_effect=self.error()) as replace,patch('time.sleep'):
                with self.assertRaises(LedgerError):j.result('a','farm','collected')
            self.assertEqual(replace.call_count,3);self.assertEqual(path.read_bytes(),before)
            self.assertEqual(j.data,json.loads(before));self.assertEqual(list(Path(directory).iterdir()),[path])
    def test_shared_record_writer_retries_access_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'record.json';save_json(path,{'old':True});original=Path.replace;attempts=[]
            def replace(source,target):
                attempts.append(source)
                if len(attempts)<2:raise self.error()
                return original(source,target)
            with patch.object(Path,'replace',replace),patch('time.sleep'):
                save_json(path,{'new':True})
            self.assertEqual(len(attempts),2);self.assertEqual(json.loads(path.read_text()),{'new':True})

if __name__=='__main__':unittest.main()
