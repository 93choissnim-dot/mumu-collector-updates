"""Cross-feature regressions: facility recovery, free sweeps, workshop and startup."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch
import cv2
import numpy as np
from action_state import ActionState
from collector import Halt
from daily_state import DailyLedger,LedgerError,korea_day
from extra_collector import ExtraCollector
from vision import Vision,Screen,Match
import exe_updater
import validate_collection


def page(state,*keys):
    return Screen(state,{'daily_'+k:Match('daily_'+k,1,0,(500,352)) for k in keys})


class FacilityRecoveryTests(unittest.TestCase):
    def collector(self,**settings):
        c,d,clock,seen=validate_collection.CollectionRegression().run_flow(**settings)
        c.__class__=ExtraCollector
        c.now=clock.monotonic
        return c,d,seen
    def test_success_or_empty_resets_persistent_failure_sequence(self):
        for empty in (False,True):
            with self.subTest(empty=empty),tempfile.TemporaryDirectory() as tmp:
                c,d,seen=self.collector(initially_empty=empty)
                path=Path(tmp)/'actions.json';c.action_state=ActionState(path,'vm')
                c.action_state.fail('farm','entry','farm_wait','missing')
                self.assertEqual(c.cycle(['farm'])['farm'],'skipped' if empty else 'collected')
                state=ActionState(path,'vm')
                self.assertEqual(state.get('farm')['failures'],0)
                self.assertFalse(state.fail('farm','entry','farm_wait','missing'))
                self.assertEqual(len(seen),1)
    def test_repeated_unreadable_facility_is_blocked_but_other_rooms_continue(self):
        c,d,seen=self.collector(initial_modes={'farm':'wait'})
        self.assertEqual(c.cycle(['farm','wood'])['farm'],'unrecognized')
        self.assertEqual(c.cycle(['farm','wood'])['farm'],'deferred')
        opens=d.actions.count('open_farm')
        result=c.cycle(['farm','wood'])
        self.assertEqual(result,{'farm':'deferred','wood':'skipped'})
        self.assertEqual(d.actions.count('open_farm'),opens)
        self.assertEqual([result for room,result in seen if room=='farm'],['unrecognized','deferred','deferred'])
    def test_repeated_unconfirmed_claim_uses_same_failure_limit(self):
        c,d,seen=self.collector(post={'farm':'ready'})
        self.assertEqual(c.cycle(['farm'])['farm'],'attempted')
        self.assertEqual(c.cycle(['farm'])['farm'],'deferred')
        self.assertEqual(d.claims['farm'],6)
        self.assertEqual(c.cycle(['farm'])['farm'],'deferred')
        self.assertEqual(d.claims['farm'],6)
    def test_record_write_failure_is_not_reported_as_success(self):
        c,d,seen=self.collector(initially_empty=True)
        c.action_state.reset=Mock(side_effect=LedgerError('disk full'))
        with self.assertRaises(LedgerError):c.cycle(['farm','wood'])
        self.assertEqual(seen,[]);self.assertNotIn('open_wood',d.actions)


class SweepAndWorkshopTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        c=self.c=ExtraCollector(Mock(),Mock(),threading.Event(),Mock())
        c.daily_ledger=DailyLedger(Path(self.tmp.name)/'daily.json');c.daily_ident='vm'
        c.daily_day=korea_day();c.daily_task='daily_dungeons';c.daily_step='equipment'
        c.pause=Mock();c.post_input=Mock();c.daily_wait_marker=Mock()
    def sweep(self,key,ready,fresh):
        c=self.c;c.daily_step=key
        room=page('daily_room_'+key,'d_sweep_open')
        c.daily_find_dungeon=Mock(return_value=room);c.daily_wait=Mock(return_value=room);c.daily_close_room=Mock()
        c.daily_ready=Mock(side_effect=ready);c.screen=Mock(side_effect=[room]+fresh)
        c.daily_dungeon(key)
    def test_disappearing_free_key_never_clicks_replacement(self):
        free=page('daily_sweep','sweep_free_1','sweep_count_0','sweep_close')
        done=page('daily_sweep','sweep_free_0','sweep_count_0','sweep_close')
        self.sweep('equipment',[free,done],[done,done])
        self.assertTrue(self.c.daily_done('equipment'))
        self.assertEqual(self.c.device.click.call_count,2)  # open and close only
        self.c.daily_wait_marker.assert_not_called()
    def test_count_change_blocks_free_key_even_when_free_label_remains(self):
        free=page('daily_sweep','sweep_free_1','sweep_count_0','sweep_close')
        changed=page('daily_sweep','sweep_free_1','sweep_close')
        done=page('daily_sweep','sweep_free_0','sweep_count_0','sweep_close')
        self.sweep('summon',[free,done],[changed,done])
        self.assertTrue(self.c.daily_done('summon'));self.assertEqual(self.c.device.click.call_count,2)
    def test_transient_effect_rechecks_then_sweeps_once(self):
        free=page('daily_sweep','sweep_free_1','sweep_count_0','sweep_close')
        active=page('daily_sweep','sweep_action','sweep_close')
        done=page('daily_sweep','sweep_free_0','sweep_count_0','sweep_close')
        self.sweep('equipment',[free,free,active,done],[page('unknown'),free,active,done])
        self.assertTrue(self.c.daily_done('equipment'));self.assertEqual(self.c.device.click.call_count,4)
        self.assertEqual(sum(call.args[0]==(480,382) for call in self.c.device.click.call_args_list),1)
    def test_missing_sweep_action_rechecks_without_duplicate_input(self):
        active=page('daily_sweep','sweep_action','sweep_close')
        done=page('daily_sweep','sweep_free_0','sweep_count_0','sweep_close')
        self.sweep('summon',[active,done],[done,done])
        self.assertTrue(self.c.daily_done('summon'));self.assertEqual(self.c.device.click.call_count,2)
    def test_workshop_route_selects_center_once_and_skips_done_step(self):
        c=self.c;c.daily_task='daily_guild';c.daily_step='raid'
        c.daily_guild_page=Mock(return_value=page('daily_guild_battle'))
        c.daily_wait=Mock(side_effect=[page('daily_raid_map'),page('daily_raid_detail')])
        c.daily_tap=Mock()
        def combat(states,on_result):on_result();return page('daily_raid_map'),True
        c.daily_combat=Mock(side_effect=combat)
        c.daily_run_step('raid','공방 약탈',c.daily_guild_raid)
        c.daily_run_step('raid','공방 약탈',c.daily_guild_raid)
        self.assertEqual([a.args[1] for a in c.daily_tap.call_args_list],['guild_raid_open','raid_center','raid_fight'])
        self.assertTrue(c.daily_done('raid'));c.daily_combat.assert_called_once()
    def test_workshop_recognizer_only_targets_middle_even_with_side_distractors(self):
        v=Vision();dv=v.daily
        im=np.full((540,960,3),110,np.uint8)
        for name in ('raid_title','raid_center'):
            x,y,r,b=dv.specs[name]['box'];im[y:b,x:r]=dv.templates[name][0]
        tile=dv.templates['raid_center'][0];h,w=tile.shape[:2]
        for x in (110,740):im[290:290+h,x:x+w]=tile
        for width in (640,960,1280):
            s=v.recognize(cv2.resize(im,(width,width*9//16)))
            self.assertEqual(s.state,'daily_raid_map')
            self.assertTrue(440<s.matches['daily_raid_center'].center[0]<560)
        x,y,r,b=dv.specs['raid_center']['box'];im[y:b,x:r]=110
        self.assertNotIn('daily_raid_center',v.recognize(im).matches)


class UpdateRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
    def job(self,name,content):
        p=self.root/'updates'/('release-'+name)/'exe-job.json';p.parent.mkdir(parents=True)
        p.write_text(content,encoding='utf-8');return p
    def test_malformed_historical_records_do_not_prevent_startup(self):
        for index,raw in enumerate(('{broken','[]','null','{}','{"target":3}','{"target":""}')):
            self.job(str(index),raw)
        with patch.object(exe_updater,'start_helper') as helper:
            self.assertFalse(exe_updater.recover_pending(self.root));helper.assert_not_called()
        report=json.loads((self.root/'update_result.json').read_text(encoding='utf-8'))
        self.assertFalse(report['ok']);self.assertEqual(len(list(self.root.glob('updates/*/exe-job.json'))),6)
    def test_valid_interrupted_update_is_still_recovered_after_bad_record(self):
        bad=self.job('bad','{broken')
        good=self.job('good',json.dumps({'target':exe_updater.sys.executable,'status':'applying'}))
        with patch.object(Path,'glob',return_value=iter([bad,good])),patch.object(exe_updater,'start_helper') as helper:
            self.assertTrue(exe_updater.recover_pending(self.root));helper.assert_called_once_with(good,recover=True)
    def test_finished_and_other_install_updates_never_launch_helper(self):
        self.job('finished',json.dumps({'target':exe_updater.sys.executable,'status':'complete'}))
        self.job('other',json.dumps({'target':str(self.root/'other.exe'),'status':'applying'}))
        with patch.object(exe_updater,'start_helper') as helper:
            self.assertFalse(exe_updater.recover_pending(self.root));helper.assert_not_called()
        self.assertFalse((self.root/'update_result.json').exists())

if __name__=='__main__':unittest.main()
