"""Repeatable donation and explicit dungeon retry regressions from September 24."""
import unittest
from unittest.mock import Mock,patch
import numpy as np
import validate_training_completion as training_cases
import validate_completion_recheck as completion_cases
from daily_execution import OutcomeUnknown

class NativeTrainingRetryTests(unittest.TestCase):
    def test_missing_level_does_not_block_donation(self):
        d=training_cases.TrainingTests().device(lost=1)
        d.capture=lambda:np.full((540,960,3),60,np.uint8)
        c,result=training_cases.TrainingTests().run_claim(d)
        self.assertEqual((result,d.claims),('collected',2))
    def test_unknown_button_records_current_failure(self):
        from extra_collector import ExtraCollector
        from vision import Screen
        issue=Mock();d=training_cases.TrainingTests().device()
        d.screen=lambda:Screen('training',{})
        with patch.object(training_cases,'ExtraCollector',side_effect=lambda *a,**k:ExtraCollector(*a,**k,on_issue=issue)):
            c,result=training_cases.TrainingTests().run_claim(d)
        self.assertEqual((result,d.claims),('deferred',0));issue.assert_called_once()
        self.assertIn('버튼',issue.call_args.args[1])
    def test_transport_error_is_not_retried_in_place(self):
        d=training_cases.TrainingTests().device();click=d.click
        def disconnected(point):click(point);raise OSError('device offline')
        d.click=disconnected
        with self.assertRaises(OSError):training_cases.TrainingTests().run_claim(d)
        self.assertEqual(d.claims,1)

class ExplicitDungeonRetryTests(unittest.TestCase):
    def setUp(self):
        self.case=completion_cases.CompletionRecheckTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.c=self.case.c;self.c.daily_verification_only=False
    def test_retry_rechecks_even_previously_verified_exhaustion(self):
        c=self.c;c.daily_checkpoint('done',completion_evidence={
            'revision':1,'kind':'no_entries','observations':2,'page':'daily_room_rune'})
        action=Mock(side_effect=lambda:c.daily_mark('rune'))
        c.daily_run_step('rune','룬 동굴',action)
        action.assert_called_once();self.assertIn('previous_completion',c.daily_detail())
    def test_retry_uses_normal_live_guards_for_legacy_completion(self):
        c=self.c;action=Mock(side_effect=lambda:c.daily_mark('rune'))
        c.daily_dungeon=Mock();c.daily_run_step('rune','룬 동굴',action)
        action.assert_called_once();c.daily_dungeon.assert_not_called()
    def test_review_button_remains_readonly(self):
        c=self.c;c.daily_verification_only=True
        c.daily_dungeon=Mock(side_effect=OutcomeUnknown('남은 무료 열쇠 있음'))
        action=Mock();c.daily_run_step('rune','룬 동굴',action)
        action.assert_not_called();c.daily_dungeon.assert_called_once_with('rune',verification_only=True)
        self.assertFalse(c.daily_done('rune'))

if __name__=='__main__':unittest.main()
