"""Regression: recorded reveal screens must advance before free count checks."""
import json
import unittest
from pathlib import Path
import cv2
import numpy as np
from vision import Vision
from validate_v072_free_daily import RouteHarness


class RecordedRevealTests(RouteHarness, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=Path(__file__).parent/'assets'
        atlas=cv2.imdecode(np.fromfile(root/'free_summon_flow_frames.png',np.uint8),1)
        cases=json.loads((root/'free_summon_flow_cases.json').read_text())
        cls.frames={}
        for name,case in cases.items():
            i=case['frame'];x=(i%2)*960;y=(i//2)*540
            cls.frames[name]=atlas[y:y+540,x:x+960].copy()
        cls.observer=Vision()

    def test_reported_and_recorded_reveal_prompts_are_recognized(self):
        for name,frame in self.frames.items():
            if 'reveal_' not in name and name!='reported_character':continue
            kind='character' if name=='reported_character' else name.split('_')[0]
            with self.subTest(frame=name):
                s=self.observer.recognize(frame)
                self.assertEqual(s.state,'free_summon_reveal_'+kind)
                self.assertIn('daily_free_reveal',s.matches)
                self.assertNotIn('daily_free_summon',s.matches)

    def run_recorded_flow(self,kind,resume=False):
        stages=['two','reveal_one','result_one','one','reveal_zero','result_zero','zero']
        if resume:stages=stages[1:]
        frames=[self.frames[kind+'_'+stage] for stage in stages]
        c,d=self.make('daily_summon',kind,[self.screen('unknown')]*len(frames))
        c.vision=self.observer
        reads={}
        def capture():
            reads[d.index]=reads.get(d.index,0)+1
            d.clock+=10 if reads[d.index]>12 else .1
            return frames[d.index].copy()
        def click(point):
            stage=stages[d.index]
            expected=(230,500) if stage in ('two','one') else (480,505) if stage.startswith('reveal') else (370,495)
            self.assertLessEqual(max(abs(point[i]-expected[i]) for i in (0,1)),5,(stage,point))
            d.clicks.append((stage,point));d.index=min(d.index+1,len(frames)-1)
        d.capture=capture;d.click=click
        if resume:c.daily_checkpoint('uncertain',pending='free_summon',before_count=2)
        try:c.free_summon_step(kind)
        except Exception as exc:self.fail('Recorded flow stopped at '+stages[d.index]+': '+str(exc))
        self.assertTrue(c.daily_done(kind))
        self.assertFalse(c.daily_detail().get('pending'))
        self.assertEqual([stage for stage,_ in d.clicks],stages[:-1])

    def test_all_three_recorded_flows_use_both_free_attempts(self):
        for kind in ('character','skill','pet'):
            with self.subTest(kind=kind):self.run_recorded_flow(kind)

    def test_interrupted_reveal_resumes_without_repeating_first_summon(self):
        for kind in ('character','skill','pet'):
            with self.subTest(kind=kind):self.run_recorded_flow(kind,resume=True)

    def test_prompt_and_species_identity_are_both_required(self):
        for kind in ('character','skill','pet'):
            for box in [(390,485,575,530),(710,0,760,55)]:
                im=self.frames[kind+'_reveal_one'].copy();x,y,r,b=box;im[y:b,x:r]=0
                self.assertNotIn('daily_free_reveal',self.observer.recognize(im).matches)


class RevealInputTests(RouteHarness,unittest.TestCase):
    def test_stalled_reveal_is_bounded_and_keeps_pending(self):
        from collector import Halt
        c,d=self.make('daily_summon','character',[self.screen('free_summon_reveal_character',reveal=(480,505),identity_character=(735,29))],stuck=True)
        c.daily_checkpoint('uncertain',pending='free_summon',before_count=1)
        with self.assertRaises(Halt):c.free_summon_step('character')
        self.assertGreater(len(d.clicks),0)
        self.assertLessEqual(len(d.clicks),3)
        self.assertTrue(c.daily_detail().get('pending'))
        self.assertFalse(c.daily_done('character'))

    def test_reveal_disappearing_before_touch_does_not_click_result_button(self):
        stale=self.screen('free_summon_reveal_character',reveal=(480,505),identity_character=(735,29))
        c,d=self.make('daily_summon','character',[self.screen('free_summon_result_character',1,result_close=(370,495))])
        self.assertFalse(c.daily_try_tap(stale,'free_reveal',required=('free_identity_character',)))
        self.assertEqual(d.clicks,[])

    def test_other_species_reveal_is_closed_before_target_tab(self):
        c,d=self.make('daily_summon','character',[
            self.screen('free_summon_reveal_pet',reveal=(480,505),identity_pet=(735,29)),
            self.screen('free_summon_result_pet',1,result_close=(370,495)),
            self.screen('free_summon_pet',1,tab_character=(67,75)),
            self.screen('free_summon_character',0,identity_character=(840,125))])
        c.free_summon_step('character')
        self.assertEqual([p for _,p in d.clicks],[(480,505),(370,495),(67,75)])
        self.assertTrue(c.daily_done('character'))
        self.assertFalse(c.daily_done('pet'))
        self.assertFalse(c.daily_detail().get('pending'))

    def test_startup_uses_reveal_close_and_home_without_back_or_summoning(self):
        from start_navigation import prepare_start
        for kind in ('character','skill','pet'):
            with self.subTest(kind=kind):
                c,d=self.make('daily_summon',kind,[
                    self.screen('free_summon_reveal_'+kind,reveal=(480,505),**{'identity_'+kind:(735,29)}),
                    self.screen('free_summon_result_'+kind,1,result_close=(370,495)),
                    self.screen('free_summon_'+kind,1,home=(919,28)),self.screen('main')])
                del c.daily_day
                try:s=prepare_start(c)
                except Exception as exc:self.fail('Startup reveal recovery failed: '+str(exc))
                self.assertEqual(s.state,'main')
                self.assertEqual([p for _,p in d.clicks],[(480,505),(370,495),(919,28)])


class UnsentReservationTests(RouteHarness,unittest.TestCase):
    def test_screen_change_after_reservation_releases_only_unsent_input(self):
        ready=self.screen('free_summon_character',2,summon=(230,500),identity_character=(840,125))
        changed=self.screen('free_summon_character',2,identity_character=(840,125))
        c,d=self.make('daily_summon','character',[ready,changed])
        checkpoint=c.daily_checkpoint
        def reserve_then_change(*a,**kw):checkpoint(*a,**kw);d.index=1
        c.daily_checkpoint=reserve_then_change
        self.assertFalse(c.free_commit(ready,'summon',2,required=('free_count_2','free_identity_character')))
        self.assertEqual(d.clicks,[])
        self.assertFalse(c.daily_detail().get('pending'))
        resolution=c.daily_detail()['input_resolution']
        self.assertEqual(resolution['kind'],'not_sent')
        self.assertIs(resolution['confirmed'],False)
        c.daily_checkpoint=checkpoint;d.index=0
        self.assertTrue(c.free_commit(ready,'summon',2,required=('free_count_2','free_identity_character')))
        self.assertEqual(len(d.clicks),1)

    def test_dispatch_error_keeps_pending(self):
        from collector import Halt
        ready=self.screen('free_summon_character',2,summon=(230,500),identity_character=(840,125))
        c,d=self.make('daily_summon','character',[ready])
        d.click=lambda p:(_ for _ in ()).throw(Halt('transport response lost'))
        with self.assertRaises(Halt):c.free_commit(ready,'summon',2,required=('free_count_2','free_identity_character'))
        self.assertTrue(c.daily_detail().get('pending'))


if __name__=='__main__':unittest.main()
