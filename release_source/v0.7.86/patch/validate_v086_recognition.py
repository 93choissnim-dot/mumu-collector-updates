"""Excavation panel variants and toast-occluded free product identity."""
import base64,json,unittest
from pathlib import Path
import cv2
import numpy as np
from vision import Vision
from validate_overlays import composite

ASSETS=Path(__file__).parent/'assets'
def excavation_frame(v,state='active',title='x_relic_title'):
    im=composite(v,title)
    spec=json.loads((ASSETS/'button_profiles.json').read_text())['excavation_panel']
    def paste(box,file):
        x,y,r,b=box;crop=cv2.imread(str(ASSETS/file))
        im[y-7:b+7,x-7:r+7]=cv2.copyMakeBorder(crop,7,7,7,7,cv2.BORDER_REPLICATE)
    for control in spec['anchors']:paste(control['box'],control['file'])
    paste(spec['box'],spec[state+'_file'])
    return im

class RecognitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.v=Vision()
    def test_both_titles_and_absent_resource_bar_preserve_button_state(self):
        for title in ('x_relic_title','x_dig_title'):
            for state in ('active','empty'):
                for width in (640,960,1280,1920):
                    with self.subTest(title=title,state=state,width=width):
                        s=self.v.recognize(cv2.resize(excavation_frame(self.v,state,title),(width,width*9//16)))
                        self.assertEqual(s.state,'excavation')
                        self.assertIn('x_dig_'+state,s.matches)
                        self.assertNotIn('x_dig_'+('empty' if state=='active' else 'active'),s.matches)
    def test_partial_panel_and_dimmed_button_never_become_claimable_page(self):
        for box in ((45,185,94,225),(748,66,848,99),(73,8,190,47)):
            im=excavation_frame(self.v);x,y,r,b=box;im[y:b,x:r]=0
            self.assertNotEqual(self.v.recognize(im).state,'excavation')
        s=self.v.recognize((excavation_frame(self.v)*.4).astype(np.uint8))
        self.assertNotIn('x_dig_active',s.matches);self.assertNotIn('x_dig_empty',s.matches)
    def test_missing_or_ambiguous_button_does_not_claim_or_confirm(self):
        a=excavation_frame(self.v);e=excavation_frame(self.v,'empty')
        missing=a.copy();missing[466:511,771:924]=0
        for im in (missing,cv2.addWeighted(a,.5,e,.5,0)):
            s=self.v.recognize(im);self.assertEqual(s.state,'excavation')
            self.assertNotIn('x_dig_active',s.matches);self.assertNotIn('x_dig_empty',s.matches)
    def test_toast_over_gem_keeps_only_correct_literal_free_confirmation(self):
        for name,key in [('ruby_modal','ruby'),('ruby_ad_modal','ruby_ad')]:
            im=cv2.imread(str(ASSETS/('free_daily_fixture_'+name+'.png')))
            im[202:256,285:665]=(35,80,50)
            s=self.v.recognize(im)
            self.assertEqual(s.state,'free_store_confirm_'+key)
            self.assertIn('daily_free_confirm_'+key,s.matches)
            self.assertNotIn('daily_free_confirm_'+('ruby' if key=='ruby_ad' else 'ruby_ad'),s.matches)
    def test_occluded_modal_still_requires_title_close_gem_and_free(self):
        original=cv2.imread(str(ASSETS/'free_daily_fixture_ruby_modal.png'))
        original[202:256,285:665]=(35,80,50)
        for box in ((300,60,430,115),(605,57,670,112),(398,165,570,329),(389,348,573,430)):
            im=original.copy();x,y,r,b=box;im[y:b,x:r]=0
            s=self.v.recognize(im)
            self.assertFalse(any(k.startswith('daily_free_confirm_') for k in s.matches))

class MigrationTests(unittest.TestCase):
    def pending(self,**kw):
        import validate_v079_rewards as old
        return old.MigrationTests().pending('excavation',version='0.7.85',**kw)
    def test_v085_excavation_retries_once_and_keeps_previous_result_unknown(self):
        c,d,slot,old=self.pending()
        self.assertEqual(c.claim_extra('excavation',d.screen()),'collected')
        self.assertEqual(d.claims,1)
        history=c.action_state.get('excavation')['input_history']
        prior=next(h for h in history if h['request']['id']==old)
        self.assertFalse(prior['resolution']['confirmed'])
    def test_failed_migration_cannot_repeat_on_next_run(self):
        c,d,slot,old=self.pending(lost=99)
        for _ in range(2):self.assertEqual(c.claim_extra('excavation',d.screen()),'deferred')
        self.assertEqual(d.claims,1)
        self.assertNotEqual(c.action_state.pending('excavation')['id'],old)
    def test_other_tasks_new_requests_and_invalid_provenance_stay_held(self):
        from legacy_free_recovery import eligible
        from datetime import datetime,timezone
        now=datetime(2026,10,9,tzinfo=timezone.utc)
        request=dict(id='old',action='claim',version='0.7.85',requested_at='2026-10-08T21:50:00+09:00')
        for task in ('ranking','worldboss','training','daily_store','daily_dungeons'):
            self.assertFalse(eligible(task,'claim',request,now=now))
        for change in ({'version':'0.7.86'},{'action':'paid'},{'id':''},
                       {'requested_at':'bad'},{'requested_at':'2030-01-01T00:00:00+09:00'}):
            self.assertFalse(eligible('excavation','claim',request|change,now=now))

class ImageRouteTests(unittest.TestCase):
    def test_claim_to_resource_bar_absence_completes_once_with_real_vision(self):
        import threading
        from extra_collector import ExtraCollector
        v=Vision();frames=[excavation_frame(v),excavation_frame(v,'empty','x_dig_title')]
        class Device:
            clock=0;index=0
            def __init__(self):self.clicks=[]
            def capture(d):d.clock+=.1;return frames[d.index].copy()
            def click(d,point):d.clicks.append(point);d.index=1
        d=Device();c=ExtraCollector(d,v,threading.Event(),lambda _:None)
        c.now=lambda:d.clock;c.pause=lambda n:setattr(d,'clock',d.clock+n);c.trace.task='excavation'
        self.assertEqual(c.claim_extra('excavation',c.screen()),'collected')
        self.assertEqual(d.clicks,[(847.5,488.5)])
        self.assertFalse(c.action_state.pending('excavation'))

class PackagedHealthTests(unittest.TestCase):
    def test_packaged_health_executes_new_regressions_before_reporting_success(self):
        import tempfile
        from unittest.mock import patch
        from frozen_entry import health_check
        class Checked(Exception):pass
        calls=0
        def run(suite,output):
            nonlocal calls
            calls+=1
            if calls==1:return unittest.TestResult()
            def cases(node):
                for item in node:
                    if isinstance(item,unittest.TestSuite):yield from cases(item)
                    else:yield item
            ids={case.id() for case in cases(suite)}
            self.assertTrue(any(i.startswith('validate_v086_recognition.RecognitionTests.') for i in ids))
            self.assertTrue(any(i.startswith('validate_v086_recognition.MigrationTests.') for i in ids))
            raise Checked()
        with tempfile.TemporaryDirectory() as folder,patch('health_progress.run_suite',side_effect=run):
            with self.assertRaises(Checked):health_check(Path(folder)/'health.json')

if __name__=='__main__':unittest.main()
