"""Settlement and one-time free reward recovery without live input."""
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import validate_world_boss as boss_tests
from vision import Match
from action_state import ActionState
from retry_resolution import pending_choices,resolve_choice

class SettlementTests(unittest.TestCase):
    run_flow=boss_tests.RouteTests.run_flow
    def test_settlement_keeps_uncertainty_without_rank_or_claim_input(self):
        def setup(d,c):
            c.action_state.reserve('worldboss','kraken')
            screen=d.screen
            def seasonal():
                s=screen()
                if s.state=='boss':s.matches['x_boss_settlement']=Match('x_boss_settlement',1,0,(824,404))
                return s
            d.screen=seasonal
        d,c,r=self.run_flow(['kraken'],before_run=setup)
        self.assertEqual(d.rank_opens,0)
        self.assertEqual(sum(d.claims.values()),0)
        self.assertEqual(r,{'worldboss':'waiting'})
        self.assertTrue(c.action_state.pending('worldboss','kraken'))
        self.assertIn('정산',c.wait_reasons['worldboss'])

    def test_legacy_free_boss_claim_is_retried_once_on_current_active_button(self):
        def setup(d,c):
            c.action_state.reserve('worldboss','kraken')
            e=c.action_state.get('worldboss');e['pending']['kraken'].update(version='0.7.64',requested_at='2026-09-27T22:51:29+09:00')
            c.action_state.update('worldboss',**e)
        d,c,r=self.run_flow(['kraken'],before_run=setup)
        self.assertEqual(d.claims['kraken'],1)
        self.assertEqual(r,{'worldboss':'collected'})
        self.assertFalse(c.action_state.pending('worldboss','kraken'))
        self.assertTrue(any(x['resolution'].get('source')=='legacy_free_claim_recovery' for x in c.action_state.get('worldboss')['input_history']))

class FreeRecoveryRules(unittest.TestCase):
    def test_only_dated_old_free_claims_are_eligible(self):
        import legacy_free_recovery as m
        now=datetime(2026,9,28,14,tzinfo=timezone.utc)
        old={'id':'old','version':'0.7.65','requested_at':'2026-09-28T07:49:31+09:00'}
        self.assertTrue(m.eligible('mine','claim',old,now=now))
        self.assertTrue(m.eligible('worldboss','kraken',old,now=now))
        for task,slot in [('training','claim'),('daily_guild','donation'),('daily_dungeons','equipment'),('worldboss','claim')]:
            self.assertFalse(m.eligible(task,slot,old,now=now))
        for change in ({'version':'0.7.70'},{'version':'0.8.0'},{'version':'broken'},{'requested_at':'bad'},{'requested_at':'2030-01-01T00:00:00+09:00'},{'id':''}):
            self.assertFalse(m.eligible('mine','claim',{**old,**change},now=now))

    def test_manual_free_resolution_archives_only_selected_boss(self):
        with tempfile.TemporaryDirectory() as td:
            a=ActionState(Path(td)/'action_state.json','vm')
            a.reserve('worldboss','kraken');a.reserve('worldboss','void')
            choices=pending_choices(td,'vm','worldboss')
            self.assertEqual({c['step'] for c in choices},{'kraken','void'})
            choice=next(c for c in choices if c['step']=='kraken')
            self.assertFalse(resolve_choice(td,'vm','worldboss',choice,'completed',confirmed=True))
            self.assertIsNone(a.pending('worldboss','kraken'))
            self.assertIsNotNone(a.pending('worldboss','void'))
            with self.assertRaises(ValueError):resolve_choice(td,'vm','worldboss',choice,'completed',confirmed=True)

class LegacyRoomTests(unittest.TestCase):
    def test_old_mine_request_recovers_once_but_new_uncertainty_does_not_repeat(self):
        from validate_collection import CollectionRegression
        helper=CollectionRegression()
        for lost in (False,True):
            c,d,clock,_=helper.run_flow(post={'mine':'ready'} if lost else {})
            c.action_state.reserve('mine')
            old=c.action_state.get('mine');old['pending']['claim'].update(version='0.7.65',requested_at='2026-09-28T07:49:31+09:00')
            c.action_state.update('mine',**old)
            helper.cycle(c,clock,['mine'])
            self.assertEqual(d.claims['mine'],1)
            self.assertEqual(bool(c.action_state.pending('mine')),lost)
            if lost:
                helper.cycle(c,clock,['mine'])
                self.assertEqual(d.claims['mine'],1)
                self.assertEqual(c.action_state.pending('mine')['version'],__import__('version').VERSION)

class LegacyAutumnTests(unittest.TestCase):
    def test_legacy_autumn_recovers_once_and_archives_uncertainty(self):
        from validate_autumn import RouteTests
        d,c=RouteTests().collector()
        c.action_state.reserve('autumn')
        old=c.action_state.get('autumn');old['pending']['claim'].update(version='0.7.65',requested_at='2026-09-28T07:49:31+09:00')
        c.action_state.update('autumn',**old)
        self.assertEqual(c.cycle(['autumn']),{'autumn':'collected'})
        self.assertEqual(d.claims,1)
        self.assertTrue(any(x['resolution']['source']=='legacy_free_claim_recovery' for x in c.action_state.get('autumn')['input_history']))

class SettlementVisionTests(unittest.TestCase):
    def test_actual_diagnostic_label_is_detected_on_boss_page_only(self):
        import cv2,numpy as np,json,base64
        from vision import Vision
        from validate_overlays import composite
        v=Vision()
        data=json.loads((Path(__file__).parent/'assets/boss_settlement.json').read_text())
        tile=cv2.imdecode(np.frombuffer(base64.b64decode(data['png']),np.uint8),cv2.IMREAD_COLOR)
        im=composite(v,'x_boss_mission','x_boss_rank_open','x_boss_supply')
        x,y,r,b=data['box'];im[y:b,x:r]=tile
        self.assertIn('x_boss_settlement',v.recognize(im).matches)
        no_boss=np.zeros_like(im);no_boss[y:b,x:r]=tile
        self.assertNotIn('x_boss_settlement',v.recognize(no_boss).matches)
        self.assertNotIn('x_boss_settlement',v.recognize((im*.3).astype(np.uint8)).matches)
        weather=im.copy();weather[y:b,x:r]=np.clip(tile.astype(float)+40,0,255).astype(np.uint8)
        self.assertIn('x_boss_settlement',v.recognize(weather).matches)
        for gain in (.9,1.,1.1):
            self.assertIn('x_boss_settlement',v.recognize(np.clip(im*gain,0,255).astype(np.uint8)).matches)
        for width in (640,1280):
            self.assertIn('x_boss_settlement',v.recognize(cv2.resize(im,(width,width*9//16))).matches)

if __name__=='__main__':unittest.main()
