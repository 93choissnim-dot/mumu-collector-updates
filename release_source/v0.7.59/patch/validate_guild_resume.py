"""New-run guild retry keeps old uncertainty and blocks same-run duplicates."""
import unittest
from unittest.mock import Mock
from daily_actions import DailyActions
from daily_execution import OutcomeUnknown
from collector import ScreenChanged
from collector import Halt
from vision import Vision
from pathlib import Path
import cv2
import numpy as np
import validate_dungeon_confirmation as cases

class GuildResumeTests(unittest.TestCase):
    def setUp(self):
        self.case=cases.DungeonConfirmationTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        c=self.c=self.case.c;c.daily_task='daily_guild';c.daily_step='dungeon'
        c.daily_performed=False
    def pending(self):
        self.c.daily_checkpoint('uncertain',pending='guild_fight')
        return self.c.daily_detail()['input_request']['id']
    def route(self,confirmed=True,zero=False):
        c=self.c
        c.daily_guild_page=Mock(return_value=cases.screen('daily_guild_battle','guild_dungeon_open'))
        active=cases.screen('daily_guild_dungeon','guild_count_2','guild_fight')
        empty=cases.screen('daily_guild_dungeon','guild_count_0','guild_loot_zero','guild_fight')
        c.daily_ready=Mock(side_effect=[empty] if zero else [active,empty])
        self.clicks=[]
        def tap(screen,key=None,point=None,before_input=None,**kw):
            if before_input:before_input()
            self.clicks.append(key)
        c.daily_tap=tap
        def combat(*args,on_result=None,**kw):
            c.daily_combat_evidence='daily_clear' if confirmed else None
            if confirmed and on_result:on_result()
            return empty,confirmed
        c.daily_combat=combat;c.daily_guild_dungeon()
    def test_new_run_resumes_remaining_guild_entries_preserving_old_uncertainty(self):
        old=self.pending();self.c.arm_guild_resume();self.route()
        self.assertEqual(self.clicks.count('guild_fight'),1)
        self.assertTrue(self.c.daily_done('dungeon'))
        prior=next(x for x in self.c.daily_detail()['input_history'] if x['request']['id']==old)
        self.assertFalse(prior['resolution']['confirmed'])
        self.assertEqual(prior['resolution']['source'],'fresh_guild_run')
    def test_current_run_pending_cannot_be_rearmed(self):
        self.c.arm_guild_resume();old=self.pending();self.c.arm_guild_resume()
        with self.assertRaises(OutcomeUnknown):self.route()
        self.assertNotIn('guild_fight',self.clicks)
        self.assertEqual(self.c.daily_detail()['input_request']['id'],old)
    def test_missing_result_keeps_new_pending_and_blocks_repeat(self):
        self.pending();self.c.arm_guild_resume()
        with self.assertRaises(OutcomeUnknown):self.route(confirmed=False)
        self.assertEqual(self.clicks.count('guild_fight'),1)
        self.assertFalse(self.c.daily_can_resume_pending())
        with self.assertRaises(OutcomeUnknown):self.route()
        self.assertNotIn('guild_fight',self.clicks)
    def test_rejected_guard_does_not_retire_old_request(self):
        old=self.pending();c=self.c;c.arm_guild_resume()
        c.daily_tap=DailyActions.daily_tap.__get__(c);c.tap=Mock(side_effect=ScreenChanged('changed'))
        self.assertFalse(c.daily_committed_tap(cases.screen('daily_guild_dungeon','guild_fight','guild_count_2'),'guild_fight',required=('guild_count_2',)))
        self.assertEqual(c.daily_detail()['input_request']['id'],old)
    def test_readonly_never_retires_guild_pending(self):
        old=self.pending();self.c.arm_guild_resume();self.c.daily_verification_only=True
        with self.assertRaises(OutcomeUnknown):self.route()
        self.assertEqual(self.c.daily_detail()['input_request']['id'],old)
    def test_exhaustion_archives_uncertainty_without_extra_fight(self):
        old=self.pending();self.c.arm_guild_resume();self.route(zero=True)
        self.assertNotIn('guild_fight',self.clicks);self.assertTrue(self.c.daily_done('dungeon'))
        prior=next(x for x in self.c.daily_detail()['input_history'] if x['request']['id']==old)
        self.assertFalse(prior['resolution']['confirmed'])
    def test_real_native_fresh_guard_controls_retirement_and_click(self):
        v=Vision();image=np.full((540,960,3),110,np.uint8)
        for name in ('guild_dungeon_rank_diagnostic','guild_fight_diagnostic','guild_count_2'):
            x,y,r,b=v.daily.specs[name]['box'];image[y:b,x:r]=v.daily.templates[name][0]
        initial=v.recognize(image)
        self.assertEqual(initial.state,'daily_guild_dungeon')
        self.assertIn('daily_guild_count_2',initial.matches)
        for mode in ('same','missing_counter','disabled_fight','stop'):
            with self.subTest(mode=mode):
                case=cases.DungeonConfirmationTests();case.setUp()
                try:
                    c=case.c;c.daily_task='daily_guild';c.daily_step='dungeon';c.vision=v
                    c.daily_tap=DailyActions.daily_tap.__get__(c)
                    c.daily_checkpoint('uncertain',pending='guild_fight')
                    old=c.daily_detail()['input_request']['id'];c.arm_guild_resume()
                    fresh=image.copy()
                    if mode=='missing_counter':fresh[418:452,684:831]=110
                    if mode=='disabled_fight':fresh[465:519,810:906]=110
                    c.device.capture.return_value=fresh
                    if mode=='stop':
                        c.stop.set()
                        with self.assertRaises(Halt):c.daily_committed_tap(initial,'guild_fight',required=('guild_count_2',))
                    else:
                        result=c.daily_committed_tap(initial,'guild_fight',required=('guild_count_2',))
                        self.assertEqual(result,mode=='same')
                    if mode=='same':
                        c.device.click.assert_called_once()
                        self.assertNotEqual(c.daily_detail()['input_request']['id'],old)
                    else:
                        c.device.click.assert_not_called()
                        self.assertEqual(c.daily_detail()['input_request']['id'],old)
                finally:case.doCleanups()

if __name__=='__main__':unittest.main()
