"""New user runs resume current dungeon availability without inventing old success."""
import unittest
from unittest.mock import Mock
import validate_dungeon_confirmation as cases
from daily_actions import DailyActions
from daily_execution import OutcomeUnknown
from collector import ScreenChanged

class DungeonResumeTests(unittest.TestCase):
    def setUp(self):
        self.case=cases.DungeonConfirmationTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.c=self.case.c;self.c.daily_performed=False
    def pending(self,key,action):
        c=self.c;c.daily_step=key;c.daily_checkpoint('uncertain',pending=action)
        return c.daily_detail()['input_request']['id']
    def arm(self):self.c.arm_dungeon_resume()
    def route(self,key,free=False):
        c=self.c;page=self.case.setup_room(key);sweep=key in ('equipment','summon')
        state='daily_sweep' if sweep else page
        action='sweep_action' if sweep else 'd_enter'
        prefix='sweep_' if sweep else 'd_'
        frames=[]
        if free:
            frames.append(cases.screen(state,prefix+'count_0',prefix+'free_1'))
            if sweep:frames.append(cases.screen(state,action))
        frames.extend([cases.screen(state,action),cases.screen(state,prefix+'count_0',prefix+'free_0')])
        c.daily_ready=Mock(side_effect=frames);c.daily_wait_marker=Mock()
        clicks=[]
        def tap(screen,key=None,point=None,before_input=None,**kwargs):
            if before_input:before_input()
            clicks.append(key or 'free_key')
            if key==action:
                if sweep:c.daily_reward_seen=True
        c.daily_tap=tap
        c.daily_combat=Mock(side_effect=lambda *a,**k:(setattr(c,'daily_combat_evidence','daily_clear') or cases.screen(page),True))
        c.daily_dungeon(key)
        return clicks
    def test_old_pending_resumes_four_reported_dungeons_to_exhaustion(self):
        old_ids={key:self.pending(key,'sweep_action' if key in ('equipment','summon') else 'd_enter')
                 for key in ('equipment','summon','stone','treasure')}
        self.arm()
        for key in ('equipment','summon','stone','treasure'):
            with self.subTest(key=key):
                action='sweep_action' if key in ('equipment','summon') else 'd_enter'
                old=old_ids[key];clicks=self.route(key,free=key!='stone')
                self.assertTrue(self.c.daily_done(key));self.assertIsNone(self.c.daily_detail().get('pending'))
                history=self.c.daily_detail()['input_history'];prior=next(x for x in history if x['request']['id']==old)
                self.assertFalse(prior['resolution']['confirmed']);self.assertEqual(prior['resolution']['source'],'fresh_dungeon_run')
                self.assertEqual(clicks.count(action),1)
                if key!='stone':self.assertLess(clicks.index('free_key'),clicks.index(action))
    def test_unarmed_pending_remains_blocked(self):
        self.pending('stone','d_enter')
        with self.assertRaises(OutcomeUnknown):self.route('stone')
    def test_pending_from_current_run_cannot_be_rearmed(self):
        c=self.c;self.arm();old=self.pending('stone','d_enter')
        with self.assertRaises(OutcomeUnknown):self.route('stone')
        self.assertEqual(c.daily_detail()['input_request']['id'],old)
    def test_rejected_fresh_guard_preserves_old_request(self):
        c=self.c;old=self.pending('stone','d_enter');self.arm()
        c.daily_tap=DailyActions.daily_tap.__get__(c);c.tap=Mock(side_effect=ScreenChanged('changed'))
        self.assertFalse(c.daily_committed_tap(cases.screen('daily_room_stone','d_enter'),'d_enter'))
        self.assertEqual(c.daily_detail()['input_request']['id'],old)
    def test_transport_failure_does_not_allow_same_run_replay(self):
        c=self.c;old=self.pending('stone','d_enter');self.arm()
        def failed(screen,key=None,point=None,before_input=None,**kwargs):
            before_input();raise OSError('offline')
        c.daily_tap=failed
        with self.assertRaises(OSError):c.daily_committed_tap(cases.screen('daily_room_stone','d_enter'),'d_enter')
        self.assertNotEqual(c.daily_detail()['input_request']['id'],old)
        self.assertFalse(c.daily_can_resume_pending())
    def test_readonly_mode_never_retires_pending(self):
        c=self.c;old=self.pending('stone','d_enter');self.arm();c.daily_verification_only=True
        with self.assertRaises(OutcomeUnknown):self.route('stone')
        self.assertEqual(c.daily_detail()['input_request']['id'],old)
    def test_exhausted_current_state_preserves_old_uncertainty_in_archive(self):
        c=self.c;old=self.pending('stone','d_enter');self.arm();page=self.case.setup_room('stone')
        c.daily_ready=Mock(return_value=cases.screen(page,'d_count_0','d_free_0'))
        c.daily_dungeon('stone');self.assertTrue(c.daily_done('stone'));c.daily_tap.assert_not_called()
        self.assertFalse(c.daily_detail()['input_history'][0]['resolution']['confirmed'])
    def test_readonly_argument_never_retires_exhausted_pending(self):
        c=self.c;old=self.pending('stone','d_enter');self.arm();page=self.case.setup_room('stone')
        c.daily_ready=Mock(return_value=cases.screen(page,'d_count_0','d_free_0'))
        with self.assertRaises(OutcomeUnknown):c.daily_dungeon('stone',verification_only=True)
        self.assertEqual(c.daily_detail()['input_request']['id'],old)

    def test_permission_does_not_apply_to_guild(self):
        c=self.c;self.pending('stone','d_enter');self.arm();c.daily_task='daily_guild';c.daily_step='dungeon'
        c.daily_checkpoint('uncertain',pending='guild_fight')
        self.assertFalse(c.daily_can_resume_pending())

if __name__=='__main__':unittest.main()
