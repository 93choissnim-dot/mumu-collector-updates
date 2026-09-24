"""Pre-input animation changes, counters, close acknowledgement and old blocks."""
from pathlib import Path
import tempfile,threading,unittest
from unittest.mock import Mock
from collector import Halt,ScreenChanged
from daily_state import DailyLedger,LedgerError,korea_day
from extra_collector import ExtraCollector
from vision import Screen,Match

def page(state,*keys):
    return Screen(state,{'daily_'+k:Match('daily_'+k,1,0,(744,440)) for k in keys})

class TransitionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        c=self.c=ExtraCollector(Mock(),Mock(),threading.Event(),Mock())
        c.daily_ledger=DailyLedger(Path(self.tmp.name)/'daily.json');c.daily_ident='vm'
        c.daily_day=korea_day();c.daily_task='daily_dungeons';c.daily_step='relic'
        self.clock=0;c.now=lambda:self.clock
        c.pause=lambda n:setattr(self,'clock',self.clock+n)
        c.post_input=Mock();c.daily_combat=Mock()
    def test_animation_rejects_input_then_rechecks_free_key_and_completes(self):
        c=self.c;state='daily_room_relic'
        free=page(state,'d_free_1','d_count_0');enter=page(state,'d_enter');done=page(state,'d_free_0','d_count_0')
        c.daily_find_dungeon=Mock(return_value=free);c.daily_close_room=Mock();c.daily_wait_marker=Mock()
        c.daily_ready=Mock(side_effect=[free,free,enter,done])
        c.screen=Mock(side_effect=[page('unknown'),free,enter]);c.daily_combat.return_value=(done,True)
        c.daily_dungeon('relic')
        self.assertTrue(c.daily_done('relic'));self.assertEqual(c.device.click.call_count,2)
        c.daily_combat.assert_called_once();c.daily_close_room.assert_called_once_with(state)
    def test_free_key_disappearing_before_input_never_clicks_paid_replacement(self):
        c=self.c;state='daily_room_relic';free=page(state,'d_free_1','d_count_0');done=page(state,'d_free_0','d_count_0')
        c.daily_find_dungeon=Mock(return_value=free);c.daily_close_room=Mock()
        c.daily_ready=Mock(side_effect=[free,done]);c.screen=Mock(return_value=done)
        c.daily_dungeon('relic');c.device.click.assert_not_called();self.assertTrue(c.daily_done('relic'))
    def test_fight_waits_for_counter_after_rejected_preinput_without_duplicate(self):
        c=self.c;c.daily_task='daily_guild';c.daily_step='dungeon'
        fight=page('daily_guild_dungeon','guild_fight','guild_count_3')
        unknown=page('daily_guild_dungeon','guild_fight')
        done=page('daily_guild_dungeon','guild_fight','guild_count_0','guild_loot_zero')
        c.daily_guild_page=Mock(return_value=page('daily_guild_battle'))
        c.daily_ready=Mock(side_effect=[fight,fight,done]);c.daily_tap=Mock(side_effect=[None,ScreenChanged('counter faded'),None])
        c.daily_guild_dungeon()
        self.assertEqual([x.args[1] for x in c.daily_tap.call_args_list],['guild_dungeon_open','guild_fight','guild_fight'])
        c.daily_combat.assert_called_once();self.assertTrue(c.daily_done('dungeon'))
    def test_zero_counter_at_fresh_capture_blocks_fight_and_rechecks(self):
        c=self.c;c.daily_task='daily_guild';c.daily_step='dungeon'
        start=page('daily_guild_battle','guild_dungeon_open')
        fight=page('daily_guild_dungeon','guild_fight','guild_count_3')
        done=page('daily_guild_dungeon','guild_fight','guild_count_0','guild_loot_zero')
        c.daily_guild_page=Mock(return_value=start);c.daily_ready=Mock(side_effect=[fight,done])
        c.screen=Mock(side_effect=[start,done]);c.daily_guild_dungeon()
        self.assertEqual(c.device.click.call_count,1);c.daily_combat.assert_not_called();self.assertTrue(c.daily_done('dungeon'))
    def test_unreadable_counter_never_fights_or_completes(self):
        c=self.c;c.daily_task='daily_guild';c.daily_step='dungeon'
        c.daily_guild_page=Mock();c.daily_tap=Mock();c.daily_ready=Mock(side_effect=Halt('counter timeout'))
        with self.assertRaises(Halt):c.daily_guild_dungeon()
        c.daily_combat.assert_not_called();self.assertFalse(c.daily_done('dungeon'))
        self.assertEqual(c.daily_tap.call_count,1)
    def test_close_retries_only_while_same_verified_room_remains(self):
        c=self.c;room=page('daily_room_rune','d_close');listing=page('daily_dungeons')
        c.daily_wait=Mock(side_effect=[room,room,listing]);c.screen=Mock(return_value=room)
        c.daily_close_room(room.state);self.assertEqual(c.device.click.call_count,2)
    def test_changed_room_before_close_sends_no_stale_click(self):
        c=self.c;room=page('daily_room_rune','d_close');listing=page('daily_dungeons')
        c.daily_wait=Mock(side_effect=[room,listing]);c.screen=Mock(return_value=listing)
        c.daily_close_room(room.state);c.device.click.assert_not_called()
    def test_close_attempts_have_a_limit(self):
        c=self.c;room=page('daily_room_rune','d_close')
        c.daily_wait=Mock(side_effect=[room]*3+[Halt('close timeout')]);c.screen=Mock(return_value=room)
        with self.assertRaises(Halt):c.daily_close_room(room.state)
        self.assertEqual(c.device.click.call_count,3)
    def test_device_and_ledger_errors_are_never_retried(self):
        for error in (Halt('adb transport'),LedgerError('disk full')):
            self.c.daily_tap=Mock(side_effect=error)
            with self.assertRaises(type(error)):self.c.daily_try_tap(page('daily_room_relic'),'d_enter')
            self.c.daily_tap.assert_called_once()
    def test_stop_and_midnight_prevent_retry_input(self):
        c=self.c;c.stop.set()
        with self.assertRaises(Halt):c.daily_try_tap(page('daily_room_relic'),'d_enter')
        c.stop.clear();c.daily_day='2000-01-01'
        with self.assertRaises(Halt):c.daily_try_tap(page('daily_room_relic'),'d_enter')
        c.device.click.assert_not_called()
    def test_completed_dungeon_keeps_done_status_when_navigation_fails(self):
        c=self.c;c.daily_recover=Mock()
        def action():
            c.daily_mark('relic');raise Halt('close failed')
        c.daily_run_step('relic','유물',action)
        self.assertTrue(c.daily_done('relic'));self.assertEqual(c.daily_detail()['status'],'done')
        c.daily_recover.assert_called_once()
    def test_old_relic_block_is_rechecked_once_then_repeat_limit_still_applies(self):
        c=self.c;c.daily_task='daily_guild';c.daily_recover=Mock();c.last_screen=page('daily_relic')
        reason='일일 작업 버튼 확인 시간 초과: relic_claim, relic_empty'
        c.daily_checkpoint('blocked',reason=reason,failures=2)
        action=Mock(side_effect=Halt(reason))
        for _ in range(3):c.daily_run_step('relic','성물',action)
        self.assertEqual(action.call_count,2);self.assertEqual(c.daily_detail()['status'],'blocked')
        self.assertEqual(c.daily_detail()['relic_rule_revision'],1)
    def test_old_relic_block_with_pending_input_is_not_restarted(self):
        c=self.c;c.daily_task='daily_guild'
        c.daily_checkpoint('blocked',reason='일일 작업 버튼 확인 시간 초과: relic_claim, relic_empty',pending='unknown')
        action=Mock();c.daily_run_step('relic','성물',action);action.assert_not_called()
    def test_completed_relic_is_not_restarted_by_recognition_revision(self):
        c=self.c;c.daily_task='daily_guild';c.daily_mark('relic')
        action=Mock();c.daily_run_step('relic','성물',action);action.assert_not_called()

class NativeControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from vision import Vision
        cls.v=Vision()
    def frame(self,*names):
        import numpy as np,cv2
        im=np.full((540,960,3),70,np.uint8)
        for n in names:
            x,y,r,b=self.v.daily.specs[n]['box'];t=self.v.daily.templates[n][0]
            im[y-3:b+3,x-3:r+3]=cv2.copyMakeBorder(t,3,3,3,3,cv2.BORDER_REPLICATE)
        return im
    def test_native_relic_claim_and_disabled_are_distinct(self):
        import numpy as np,cv2
        for label,expected in [('relic_claim','daily_relic_claim'),('relic_empty','daily_relic_empty')]:
            im=self.frame('relic_title','relic_list','relic_close',label)
            for gain,offset in (([1,1,1],[0,0,0]),([1.22,1.17,1.12],[22,2,-4])):
                native=np.clip(im.astype(float)*gain+offset,0,255).astype(np.uint8)
                for width in (640,960,1280):
                    s=self.v.recognize(cv2.resize(native,(width,width*9//16)))
                    self.assertEqual(s.state,'daily_relic');self.assertIn(expected,s.matches)
                    self.assertNotIn('daily_relic_empty' if expected.endswith('claim') else 'daily_relic_claim',s.matches)
    def test_native_three_count_is_not_zero_or_two(self):
        import cv2
        im=self.frame('guild_dungeon_rank','guild_fight','guild_count_3')
        for width in (640,960,1280):
            s=self.v.recognize(cv2.resize(im,(width,width*9//16)))
            self.assertEqual(s.state,'daily_guild_dungeon')
            self.assertEqual([k for k in s.matches if k.startswith('daily_guild_count_')],['daily_guild_count_3'])
    def test_missing_counter_preserves_page_but_no_entry_evidence(self):
        s=self.v.recognize(self.frame('guild_dungeon_rank','guild_fight'))
        self.assertEqual(s.state,'daily_guild_dungeon')
        self.assertFalse(any(k.startswith('daily_guild_count_') for k in s.matches))

if __name__=='__main__':unittest.main()
