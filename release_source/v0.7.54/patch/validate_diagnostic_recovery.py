"""September 24 regressions using anonymized, small generic UI crops only."""
from pathlib import Path
import json, tempfile, threading, unittest
from unittest.mock import Mock
import cv2
import numpy as np
from vision import Vision, Screen, Match
from collector import Collector, Halt
from extra_collector import ExtraCollector
from daily_state import DailyLedger, korea_day
from daily_execution import OutcomeUnknown

ASSETS=Path(__file__).parent/'assets'
def page(state,*keys):
    return Screen(state,{'daily_'+k:Match('daily_'+k,1,0,(744,348)) for k in keys})

class DiagnosticRecognitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.v=Vision()
    def frame(self,scene):
        return cv2.imdecode(np.fromfile(ASSETS/('diagnostic_'+scene+'.png'),np.uint8),1)
    def test_native_buttons_and_catalog(self):
        cases=[('rune_entry','daily_room_rune','daily_d_enter'),
               ('sweep_equipment','daily_sweep','daily_sweep_free_1'),
               ('sweep_summon','daily_sweep','daily_sweep_free_1'),
               ('guild_combat','daily_battle','daily_battle_skip'),
               ('guild_loot','daily_guild_dungeon','daily_guild_loot_available'),
               ('guild_claim_soft','daily_guild_dungeon','daily_guild_loot_claim'),
               ('shop_catalog','daily_shop','daily_shop_exchange')]
        for scene,state,key in cases:
            for width in (960,1280,1920):
                with self.subTest(scene=scene,width=width):
                    im=cv2.resize(self.frame(scene),(width,width*9//16))
                    s=self.v.recognize(im)
                    self.assertEqual(s.state,state);self.assertIn(key,s.matches)
    def test_gray_or_missing_entry_is_not_clickable(self):
        for mode in ('gray','missing','dark'):
            im=self.frame('rune_entry');crop=im[418:462,709:777]
            if mode=='gray':crop[:]=cv2.cvtColor(cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY),cv2.COLOR_GRAY2BGR)
            elif mode=='missing':crop[:]=110
            else:crop[:]=(crop*.4).astype(np.uint8)
            self.assertNotIn('daily_d_enter',self.v.recognize(im).matches)
    def test_disabled_guild_fight_is_not_clickable(self):
        for scene in ('guild_loot','guild_claim_soft'):
            for mode in ('gray','dark'):
                im=self.frame(scene);crop=im[470:511,822:888]
                if mode=='gray':crop[:]=cv2.cvtColor(cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY),cv2.COLOR_GRAY2BGR)
                else:crop[:]=(crop*.4).astype(np.uint8)
                self.assertNotIn('daily_guild_fight',self.v.recognize(im).matches)
    def test_partial_battle_identity_is_not_a_battle(self):
        for box in ([108,0,188,33],[17,468,141,514]):
            im=self.frame('guild_combat');x,y,r,b=box;im[y:b,x:r]=110
            self.assertNotEqual(self.v.recognize(im).state,'daily_battle')
    def test_blank_or_disabled_loot_button_is_not_available(self):
        for mode in ('blank','gray','dark'):
            im=self.frame('guild_loot');crop=im[323:374,699:816]
            if mode=='blank':crop[:]=110
            elif mode=='gray':crop[:]=cv2.cvtColor(cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY),cv2.COLOR_GRAY2BGR)
            else:crop[:]=(crop*.4).astype(np.uint8)
            self.assertNotIn('daily_guild_loot_available',self.v.recognize(im).matches)

class DiagnosticFlowTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.c=ExtraCollector(Mock(),Mock(),threading.Event(),lambda _:None)
        c=self.c;c.daily_ident='test';c.daily_task='daily_guild';c.daily_step='dungeon';c.daily_day=korea_day()
        c.daily_ledger=DailyLedger(Path(tmp.name)/'daily.json');self.clock=0
        c.now=lambda:self.clock;c.pause=lambda n:setattr(self,'clock',self.clock+n)
    def test_loading_frame_waits_for_menu_without_clicks(self):
        c=self.c;unknown=Screen('unknown',{});menu=Screen('menu',{})
        c.last_screen=unknown;c.screen=Mock(side_effect=[unknown,menu,menu])
        self.assertIs(c.return_base(unknown),menu);c.device.click.assert_not_called()
    def test_base_collector_also_waits_for_unknown_transition(self):
        c=self.c;unknown=Screen('unknown',{});menu=Screen('menu',{})
        c.last_screen=unknown;c.wait_for=Mock(return_value=menu)
        self.assertIs(Collector.ensure_menu(c,unknown),menu);c.device.click.assert_not_called()
    def test_extra_collector_preserves_contextual_facility_exit(self):
        c=self.c;menu=Screen('menu',{})
        known=Screen('unknown',{'empty_farm':Match('empty_farm',1,0,(774,500))})
        c.last_screen=known;c.leave_room=Mock(return_value=menu)
        c.wait_page=Mock(side_effect=Halt('must use recognized facility route'))
        self.assertIs(c.return_base(known,'farm'),menu)
        c.leave_room.assert_called_once_with('farm',known)
    def test_facility_marker_disappearing_before_exit_sends_no_back(self):
        from validate_navigation_recovery import NavigationChangeTests,page as navigation_page
        c,d,actions,_=NavigationChangeTests().collector([
            navigation_page('unknown','empty_farm'),navigation_page('unknown'),
            navigation_page('menu'),navigation_page('menu')])
        self.assertEqual(c.leave_room('farm',c.screen()).state,'menu')
        self.assertEqual(actions,[])
    def test_stable_unknown_remains_bounded_and_sends_no_input(self):
        c=self.c;c.last_image=np.zeros((540,960,3),np.uint8)
        unknown=Screen('unknown',{});c.last_screen=unknown;c.screen=Mock(return_value=unknown)
        with self.assertRaises(Halt):c.return_base(unknown)
        self.assertLessEqual(self.clock,36);c.device.click.assert_not_called()
    def test_arbitrary_positive_loot_claim_requires_empty_confirmation(self):
        c=self.c;available=page('daily_guild_dungeon','guild_count_0','guild_loot_available','guild_loot_claim')
        empty=page('daily_guild_dungeon','guild_count_0','guild_loot_zero')
        c.daily_guild_page=Mock();c.daily_tap=Mock();c.daily_ready=Mock(side_effect=[available,available]);c.daily_wait=Mock(return_value=empty)
        c.daily_guild_dungeon();self.assertTrue(c.daily_done('dungeon'))
        self.assertEqual([x.args[1] for x in c.daily_tap.call_args_list],['guild_dungeon_open','guild_loot_claim'])
    def test_loot_still_visible_after_claim_cannot_complete(self):
        c=self.c;available=page('daily_guild_dungeon','guild_count_0','guild_loot_available','guild_loot_claim')
        c.daily_guild_page=Mock();c.daily_tap=Mock();c.daily_ready=Mock(return_value=available);c.daily_wait=Mock(return_value=available)
        with self.assertRaises(Halt):c.daily_guild_dungeon()
        self.assertFalse(c.daily_done('dungeon'))
    def test_uncertain_old_fight_remains_unresolved_even_with_loot(self):
        c=self.c;c.daily_checkpoint('uncertain',pending='guild_fight')
        c.daily_guild_page=Mock();c.daily_tap=Mock();c.daily_ready=Mock(return_value=page('daily_guild_dungeon','guild_count_0','guild_loot_available','guild_loot_claim'))
        with self.assertRaises(OutcomeUnknown):c.daily_guild_dungeon()
        self.assertEqual(c.daily_detail()['pending'],'guild_fight');self.assertFalse(c.daily_done('dungeon'))
    def test_exhausted_equipment_room_does_not_open_unavailable_sweep(self):
        c=self.c;c.daily_task='daily_dungeons';c.daily_step='equipment'
        empty=page('daily_room_equipment','d_count_0','d_free_0','d_sweep_open')
        c.daily_find_dungeon=Mock(return_value=empty);c.daily_ready=Mock(return_value=empty)
        c.daily_tap=Mock();c.daily_wait=Mock(side_effect=Halt('unavailable sweep'))
        c.daily_close_room=Mock()
        c.daily_dungeon('equipment')
        self.assertTrue(c.daily_done('equipment'));c.daily_tap.assert_not_called()
        self.assertEqual(c.daily_detail()['completion_evidence']['page'],'daily_room_equipment')
    def test_exhausted_room_does_not_erase_uncertain_sweep(self):
        c=self.c;c.daily_task='daily_dungeons';c.daily_step='equipment'
        c.daily_checkpoint('uncertain',pending='sweep_action')
        empty=page('daily_room_equipment','d_count_0','d_free_0','d_sweep_open')
        c.daily_find_dungeon=Mock(return_value=empty);c.daily_ready=Mock(return_value=empty)
        c.daily_tap=Mock();c.daily_wait=Mock(return_value=empty)
        with self.assertRaises(OutcomeUnknown):c.daily_dungeon('equipment')
        self.assertEqual(c.daily_detail()['pending'],'sweep_action')
        self.assertFalse(c.daily_done('equipment'))
    def test_changed_shop_inventory_is_already_claimed_without_purchase(self):
        c=self.c;c.daily_step='shop';s=page('daily_shop','shop_cube','shop_exchange')
        c.daily_guild_page=Mock();c.daily_tap=Mock();c.daily_wait=Mock(return_value=s)
        c.daily_guild_shop();self.assertTrue(c.daily_done('shop'))
        self.assertEqual([x.args[1] for x in c.daily_tap.call_args_list],['guild_shop_open'])

if __name__=='__main__':unittest.main()
