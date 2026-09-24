"""Dungeon completion requires stable counters and an observed action outcome."""
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock
from daily_state import DailyLedger,korea_day
from daily_execution import OutcomeUnknown
from extra_collector import ExtraCollector
from vision import Screen,Match
from collector import ScreenChanged

def screen(state,*keys):
    return Screen(state,{'daily_'+k:Match('daily_'+k,1,0,(480,380)) for k in keys})

class DungeonConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        c=self.c=ExtraCollector(Mock(),Mock(),threading.Event(),Mock())
        c.daily_ident='vm';c.daily_task='daily_dungeons';c.daily_step='stone';c.daily_day=korea_day()
        c.daily_ledger=DailyLedger(Path(self.tmp.name)/'daily.json')
        c.daily_close_room=Mock();c.daily_tap=Mock();c.dismiss_overlay=Mock(return_value=False)
        self.clock=0;c.now=lambda:self.clock
        c.pause=lambda duration:setattr(self,'clock',self.clock+duration)
    def setup_room(self,key='stone'):
        c=self.c;c.daily_step=key;page='daily_room_'+key
        c.daily_find_dungeon=Mock(return_value=screen(page));c.daily_wait=Mock(return_value=screen(page))
        return page
    def test_battle_return_without_result_preserves_pending_and_never_completes(self):
        c=self.c;page=self.setup_room()
        c.daily_ready=Mock(side_effect=[screen(page,'d_enter'),screen(page,'d_count_0','d_free_0')])
        def committed(*args,**kwargs):c.daily_checkpoint('uncertain',pending='d_enter');return True
        c.daily_committed_tap=committed;c.daily_combat=Mock(return_value=(screen(page),False))
        with self.assertRaises(OutcomeUnknown):c.daily_dungeon('stone')
        self.assertFalse(c.daily_done('stone'));self.assertEqual(c.daily_detail()['pending'],'d_enter')
    def test_old_pending_entry_is_not_resolved_by_exhausted_counter(self):
        c=self.c;page=self.setup_room();c.daily_checkpoint('uncertain',pending='d_enter')
        c.daily_ready=Mock(return_value=screen(page,'d_count_0','d_free_0'))
        with self.assertRaises(OutcomeUnknown):c.daily_dungeon('stone')
        self.assertFalse(c.daily_done('stone'));self.assertEqual(c.daily_detail()['pending'],'d_enter')
    def test_old_pending_sweep_is_not_resolved_by_exhausted_counter(self):
        c=self.c;self.setup_room('equipment');c.daily_checkpoint('uncertain',pending='sweep_action')
        c.daily_ready=Mock(return_value=screen('daily_sweep','sweep_count_0','sweep_free_0'))
        with self.assertRaises(OutcomeUnknown):c.daily_dungeon('equipment')
        self.assertFalse(c.daily_done('equipment'));self.assertEqual(c.daily_detail()['pending'],'sweep_action')
    def test_single_zero_frame_never_proves_empty_dungeon(self):
        for page,free,zero in [('daily_room_stone','d_free_0','d_count_0'),('daily_sweep','sweep_free_0','sweep_count_0')]:
            with self.subTest(page=page):
                c=self.c;nonzero=screen(page,free);empty=screen(page,free,zero)
                c.screen=Mock(side_effect=[nonzero,empty,nonzero,nonzero])
                found=c.daily_ready({page},[free])
                self.assertNotIn('daily_'+zero,found.matches);self.assertEqual(c.screen.call_count,4)
    def test_empty_room_records_observed_completion_basis(self):
        c=self.c;page=self.setup_room();c.daily_ready=Mock(return_value=screen(page,'d_count_0','d_free_0'))
        c.daily_dungeon('stone');self.assertTrue(c.daily_done('stone'))
        self.assertEqual(c.daily_detail().get('completion_evidence'),{'kind':'no_entries','observations':2,'page':page,'revision':1})
    def test_clear_layout_is_a_dungeon_outcome_without_raid_result(self):
        c=self.c;page=self.setup_room();clear=screen('daily_clear','battle_leave');room=screen(page)
        c.screen=Mock(side_effect=[clear,clear,room,room])
        self.assertEqual(c.daily_combat({page},accept_clear=True),(room,True))
    def test_clear_does_not_satisfy_raid_result_contract(self):
        c=self.c;clear=screen('daily_clear','battle_leave');room=screen('daily_raid_map')
        c.screen=Mock(side_effect=[clear,clear,room,room])
        self.assertEqual(c.daily_combat({room.state}),(room,False))
    def test_clear_dungeon_can_finish_and_archive_input_basis(self):
        c=self.c;page=self.setup_room();clear=screen('daily_clear','battle_leave');room=screen(page)
        c.daily_ready=Mock(side_effect=[screen(page,'d_enter'),screen(page,'d_count_0','d_free_0')])
        def committed(*args,**kwargs):c.daily_checkpoint('uncertain',pending='d_enter');return True
        c.daily_committed_tap=committed;c.screen=Mock(side_effect=[clear,clear,room,room])
        c.daily_dungeon('stone');self.assertTrue(c.daily_done('stone'));self.assertIsNone(c.daily_detail()['pending'])
        self.assertEqual(c.daily_detail()['input_resolution']['source'],'daily_clear')
    def test_resolution_evidence_is_captured_on_result_before_leaving(self):
        for state,keys in [('daily_clear',('battle_leave',)),('daily_result',())]:
            with self.subTest(state=state):
                c=self.c;page=self.setup_room();result=screen(state,*keys);room=screen(page)
                c.daily_ready=Mock(side_effect=[screen(page,'d_enter'),screen(page,'d_count_0','d_free_0')])
                def committed(*args,**kwargs):c.daily_checkpoint('uncertain',pending='d_enter');return True
                c.daily_committed_tap=committed
                frames=iter([result,result,room,room]);observed=[]
                def capture():c.last_screen=next(frames);return c.last_screen
                c.screen=capture
                def evidence(phase,*args):
                    if phase=='resolved':observed.append(c.last_screen.state)
                c.daily_ledger.on_input_evidence=evidence;c.daily_dungeon('stone')
                self.assertEqual(observed,[state])
    def test_two_reward_observations_confirm_even_if_overlay_auto_closes_before_tap(self):
        c=self.c;c.daily_reward_seen=False
        reward=Screen('reward',{'reward_close':Match('reward_close',1,0,(640,520))})
        room=screen('daily_sweep','sweep_action')
        c.screen=Mock(side_effect=[reward,reward,room,room])
        c.dismiss_overlay=ExtraCollector.dismiss_overlay.__get__(c)
        c.tap=Mock(side_effect=ScreenChanged('auto closed'))
        self.assertEqual(c.daily_ready({room.state},['sweep_action']),room)
        self.assertTrue(c.daily_reward_seen)
        c.device.click.assert_not_called()
    def test_one_reward_observation_cannot_confirm_sweep(self):
        c=self.c;c.daily_reward_seen=False
        reward=Screen('reward',{'reward_close':Match('reward_close',1,0,(640,520))})
        room=screen('daily_sweep','sweep_action')
        c.screen=Mock(side_effect=[reward,room,room])
        c.dismiss_overlay=ExtraCollector.dismiss_overlay.__get__(c)
        c.daily_ready({room.state},['sweep_action']);self.assertFalse(c.daily_reward_seen)
    def test_auto_closed_reward_resolves_only_current_sweep(self):
        c=self.c;self.setup_room('equipment')
        reward=Screen('reward',{'reward_close':Match('reward_close',1,0,(640,520))})
        ready=screen('daily_sweep','sweep_action');empty=screen('daily_sweep','sweep_count_0','sweep_free_0')
        c.screen=Mock(side_effect=[ready,ready,reward,reward,empty,empty])
        c.dismiss_overlay=ExtraCollector.dismiss_overlay.__get__(c);c.tap=Mock(side_effect=ScreenChanged('auto closed'))
        def committed(*args,**kwargs):c.daily_checkpoint('uncertain',pending='sweep_action');return True
        c.daily_committed_tap=committed;c.daily_dungeon('equipment')
        self.assertTrue(c.daily_done('equipment'));self.assertIsNone(c.daily_detail()['pending'])
        self.assertEqual(c.daily_detail()['input_resolution']['source'],'reward')
    def test_readonly_verification_never_uses_entry_or_free_key(self):
        for key,keys in [('stone',('d_enter',)),('stone',('d_count_0','d_free_1')),('equipment',('sweep_action',))]:
            with self.subTest(key=key,keys=keys):
                c=self.c;page=self.setup_room(key)
                c.daily_ready=Mock(return_value=screen('daily_sweep' if key=='equipment' else page,*keys))
                c.daily_tap.reset_mock()
                with self.assertRaises(OutcomeUnknown):c.daily_dungeon(key,verification_only=True)
                self.assertFalse(c.daily_done(key))
                self.assertEqual([call.args[1] for call in c.daily_tap.call_args_list],['d_sweep_open'] if key=='equipment' else [])

if __name__=='__main__':unittest.main()
