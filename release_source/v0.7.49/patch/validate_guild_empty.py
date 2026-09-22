"""Guild count/loot recognition across native rendering and moving scenery."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock
import cv2
import numpy as np
from daily_state import DailyLedger,korea_day
from daily_vision import DailyVision
from extra_collector import ExtraCollector
from vision import Match,Screen


class GuildEmptyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v=DailyVision(Path(__file__).parent/'assets');cls.v.diagnostics={}

    def test_soft_context_can_use_strict_independent_exposure_anchor(self):
        v=self.v
        located={name:(score,v.templates[name][0],0,0,0,0)
                 for name,score in [('guild_dungeon_rank',.96),('guild_fight',.925)]}
        exposure=v.exposure(located)
        self.assertIsNotNone(exposure)
        self.assertEqual(exposure[2]['anchors'],['guild_dungeon_rank'])
        located['guild_fight']=(.91,*located['guild_fight'][1:])
        self.assertIsNone(v.exposure(located))

    def loot_frame(self,name):
        im=np.full((540,960,3),110,np.uint8)
        x,y,r,b=self.v.specs[name]['box'];ref=self.v.templates[name][0].astype(np.float32)
        rows,cols=np.indices(ref.shape[:2]);delta=np.sin(cols/6)*14+np.cos(rows/7)*8
        im[y:b,x:r]=np.clip(ref+delta[:,:,None]+[7,12,14],0,255).astype(np.uint8)
        return im

    def found(self):return {n:Match('daily_'+n,1,0,(0,0)) for n in ('guild_dungeon_rank','guild_fight')}
    def exposure(self):return np.ones(3),np.zeros(3),{}

    def test_complete_suffix_separates_zero_from_ten_twenty_thirty(self):
        for name in ('guild_loot_zero','guild_loot_10','guild_loot_20','guild_loot_30'):
            with self.subTest(name=name):
                found=self.found();self.v.guild_loot_counter(self.loot_frame(name),self.exposure(),found)
                self.assertEqual([n for n in found if n.startswith('guild_loot')],[name])

    def test_missing_number_or_page_control_cannot_be_zero(self):
        im=self.loot_frame('guild_loot_zero');x,y,r,b=self.v.specs['guild_loot_zero']['box']
        im[y:b,x+36:r]=110
        found=self.found();self.v.guild_loot_counter(im,self.exposure(),found)
        self.assertNotIn('guild_loot_zero',found)
        for missing in ('guild_dungeon_rank','guild_fight'):
            found=self.found();found.pop(missing)
            self.v.guild_loot_counter(self.loot_frame('guild_loot_zero'),self.exposure(),found)
            self.assertNotIn('guild_loot_zero',found)

    def test_no_exposure_means_no_fallback(self):
        found=self.found();self.v.guild_loot_counter(self.loot_frame('guild_loot_zero'),None,found)
        self.assertNotIn('guild_loot_zero',found)

    def collector(self,tmp):
        c=ExtraCollector(Mock(),Mock(),threading.Event(),Mock(),on_issue=Mock())
        c.daily_ledger=DailyLedger(Path(tmp)/'daily.json');c.daily_ident='test'
        c.daily_day=korea_day();c.daily_task='daily_guild';c.daily_step='dungeon'
        c.daily_recover=Mock()
        return c

    def test_zero_entries_and_zero_loot_complete_without_fight_or_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=self.collector(tmp);c.daily_guild_page=Mock();c.daily_tap=Mock()
            c.daily_ready=Mock(return_value=Screen('daily_guild_dungeon',{
                'daily_'+n:Match('daily_'+n,1,0,(0,0)) for n in ('guild_count_0','guild_loot_zero')}))
            c.daily_guild_dungeon();self.assertTrue(c.daily_done('dungeon'))
            self.assertEqual([call.args[1] for call in c.daily_tap.call_args_list],['guild_dungeon_open'])
            c.device.click.assert_not_called()

    def test_only_identified_old_blocks_are_reopened_without_pending_input(self):
        reasons=('일일 작업 버튼 확인 시간 초과: guild_count_0, guild_count_1, guild_count_2, guild_count_3',
                 '길드 전리품 개수 확인이 필요합니다.')
        for reason in reasons:
            with tempfile.TemporaryDirectory() as tmp:
                c=self.collector(tmp);c.daily_checkpoint('blocked',reason=reason,failures=2)
                action=Mock(side_effect=lambda:c.daily_mark('dungeon'))
                c.daily_run_step('dungeon','길드 던전',action)
                action.assert_called_once();self.assertTrue(c.daily_done('dungeon'))
        with tempfile.TemporaryDirectory() as tmp:
            c=self.collector(tmp);c.daily_checkpoint('blocked',reason=reasons[0],pending='guild_fight')
            action=Mock();c.daily_run_step('dungeon','길드 던전',action);action.assert_not_called()


if __name__=='__main__':unittest.main()
