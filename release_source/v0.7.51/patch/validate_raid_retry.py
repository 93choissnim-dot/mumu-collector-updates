"""Repeatable raid entry and uncertainty inspection regressions."""
import tempfile
import threading
import unittest
import json
import zipfile
from pathlib import Path
from unittest.mock import Mock
from collector import Halt,ScreenChanged
from daily_execution import OutcomeUnknown
from daily_state import DailyLedger,korea_day
from extra_collector import ExtraCollector
from retry_resolution import pending_choices
from vision import Screen,Match


def page(state,*keys):
    return Screen(state,{'daily_'+k:Match('daily_'+k,1,0,(480,380)) for k in keys})


class RaidRetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        c=self.c=ExtraCollector(Mock(),Mock(),threading.Event(),Mock())
        c.daily_ledger=DailyLedger(Path(self.tmp.name)/'daily_tasks.json');c.daily_ident='vm'
        c.daily_day=korea_day();c.daily_task='daily_guild';c.daily_step='raid'
        self.clock=0;c.now=lambda:self.clock
        c.pause=lambda n:setattr(self,'clock',self.clock+n)
        c.post_input=Mock();c.daily_recover=Mock();c.dismiss_overlay=Mock(return_value=False)
        self.guild=page('daily_guild_battle','guild_raid_open')
        self.map=page('daily_raid_map','raid_center')
        self.detail=page('daily_raid_detail','raid_fight')
        self.current=self.guild;self.clicked=[]
        c.daily_guild_page=lambda **kw:self.guild
        def capture():c.last_screen=self.current;return self.current
        c.screen=capture
        def click(point):
            self.clicked.append(self.current.state)
            self.current=self.map if self.current is self.guild else self.detail
        c.device.click=click
    def old_raid(self,status='uncertain'):
        self.c.daily_checkpoint(status,pending='raid_fight',values={'raid':'started'},failures=7)
    def test_old_pending_raid_reenters_once_then_timeout_stays_incomplete(self):
        self.old_raid();c=self.c
        c.daily_run_step('raid','공방 약탈',c.daily_guild_raid)
        self.assertEqual(self.clicked,['daily_guild_battle','daily_raid_map','daily_raid_detail'])
        self.assertFalse(c.daily_done('raid'));self.assertEqual(c.daily_detail()['pending'],'raid_fight')
        resolution=c.daily_detail()['input_resolution']
        self.assertEqual(resolution['kind'],'retry_authorized');self.assertFalse(resolution['confirmed'])
        self.assertEqual(resolution['source'],'repeat_allowed_raid')
        self.assertNotEqual(c.daily_detail()['last_input']['id'],c.daily_detail()['input_request']['id'])
    def test_legacy_started_without_pending_can_reenter_once(self):
        c=self.c;c.daily_mark('raid','started')
        with self.assertRaises(Halt):c.daily_guild_raid()
        self.assertEqual(self.clicked.count('daily_raid_detail'),1)
        self.assertFalse(c.daily_done('raid'))
    def test_blocked_legacy_raid_record_does_not_prevent_verified_entry(self):
        self.old_raid('blocked');c=self.c
        c.daily_run_step('raid','공방 약탈',c.daily_guild_raid)
        self.assertEqual(self.clicked.count('daily_raid_detail'),1)
        self.assertFalse(c.daily_done('raid'))
    def test_changed_fight_button_retains_old_pending_without_entry(self):
        self.old_raid();c=self.c;capture=c.screen;reads=0
        def capture_without_fight():
            nonlocal reads
            if self.current is self.detail:
                reads+=1
                if reads>=3:self.current=page('daily_raid_detail')
            return capture()
        c.screen=capture_without_fight
        with self.assertRaises(ScreenChanged):c.daily_guild_raid()
        self.assertEqual(self.clicked,['daily_guild_battle','daily_raid_map'])
        self.assertEqual(c.daily_detail()['pending'],'raid_fight')
        self.assertNotIn('retry_authorized',c.daily_detail());self.assertFalse(c.daily_done('raid'))
    def test_verified_result_completes_repeat_once_and_later_run_skips_it(self):
        import numpy as np
        from diagnostics import save_input_evidence
        c=self.c;c.daily_ident='a'*24;c.last_image=np.zeros((540,960,3),np.uint8)
        c.daily_ledger.update(c.daily_ident,'daily_guild',{'raid':'started','_steps':{
            'raid':{'status':'uncertain','pending':'raid_fight','failures':7}}})
        evidence=[]
        def record(phase,task,step,detail):
            evidence.append((phase,detail,c.last_screen.state))
            save_input_evidence(Path(self.tmp.name),c.daily_ident,c.daily_ident,task,step,phase,
                                detail,c.last_image,c.last_screen)
        c.daily_ledger.on_input_evidence=record
        click=c.device.click;capture=c.screen;result_reads=0
        result=page('daily_result')
        def fight(point):
            was_detail=self.current is self.detail
            click(point)
            if was_detail:self.current=result
        def capture_result():
            nonlocal result_reads
            if self.current is result:
                result_reads+=1
                if result_reads>2:self.current=self.map
            return capture()
        c.device.click=fight;c.screen=capture_result
        c.daily_run_step('raid','공방 약탈',c.daily_guild_raid)
        c.daily_run_step('raid','공방 약탈',c.daily_guild_raid)
        self.assertTrue(c.daily_done('raid'));self.assertIsNone(c.daily_detail()['pending'])
        self.assertEqual(self.clicked.count('daily_raid_detail'),1)
        resolution=c.daily_detail()['input_resolution']
        self.assertTrue(resolution['confirmed']);self.assertEqual(resolution['source'],'screen_confirmed')
        self.assertEqual([e[0] for e in evidence],['resolved','requested','resolved'])
        old=evidence[0][1]
        self.assertEqual(old['last_input']['origin'],'legacy_unknown')
        self.assertNotIn('requested_at',old['last_input'])
        self.assertFalse(old['input_resolution']['confirmed'])
        self.assertEqual(old['input_resolution']['source'],'repeat_allowed_raid')
        requested=evidence[1][1]['input_request'];resolved=evidence[2][1]['last_input']
        self.assertEqual(requested['id'],resolved['id'])
        self.assertEqual(requested['requested_at'],resolved['requested_at'])
        self.assertEqual(evidence[2][2],'daily_result')
        evidence_path=next(Path(self.tmp.name).glob('*_resolved_*.zip'))
        with zipfile.ZipFile(evidence_path) as archive:
            meta=json.loads(archive.read('evidence.json'))
            self.assertEqual(meta['state'],'daily_result')
            self.assertEqual(meta['detail']['last_input']['id'],requested['id'])
            self.assertTrue(meta['detail']['input_resolution']['confirmed'])
            self.assertIn('screen.jpg',archive.namelist())
    def test_repeatable_raid_is_not_a_manual_pending_choice(self):
        self.old_raid();c=self.c
        c.daily_ledger.checkpoint('vm','daily_guild','donation','uncertain',pending='donate_50')
        self.assertEqual([x['step'] for x in pending_choices(self.tmp.name,'vm','daily_guild')],['donation'])
    def test_resume_recovery_cannot_dispatch_another_raid_in_same_run(self):
        from run_control import ResumeRecognition
        from run_support import cycle_with_recovery
        from daily_state import DAILY_STEPS
        c=self.c;c.results={};c.claim_counts={};combat_calls=[]
        for step in DAILY_STEPS['daily_guild']:
            if step!='raid':c.daily_ledger.mark('vm','daily_guild',step)
        def combat(*args,**kwargs):
            combat_calls.append(True)
            if len(combat_calls)==1:raise ResumeRecognition()
            return self.map,False
        c.daily_combat=combat
        c.daily_guild=lambda:c.daily_run_step('raid','공방 약탈',c.daily_guild_raid)
        def cycle(rooms,restore):
            c.results={};c.claim_counts={};self.current=self.guild
            c.collect_daily('daily_guild')
            return c.results
        c.cycle=cycle
        device=Mock(package='game');device.current_package.return_value='game'
        results=cycle_with_recovery(c,['daily_guild'],False,Mock(),device,Mock(),c.stop,Mock())
        self.assertEqual(self.clicked.count('daily_raid_detail'),1)
        self.assertEqual(len(combat_calls),1)
        self.assertEqual(results['daily_guild'],'deferred')
        self.assertFalse(c.daily_done('raid'))
        self.assertEqual(c.daily_detail()['pending'],'raid_fight')
    def test_new_collector_can_retry_old_run_but_same_collector_cannot(self):
        c=self.c
        c.daily_run_step('raid','공방 약탈',c.daily_guild_raid)
        request=c.daily_detail()['input_request']['id'];self.current=self.guild
        c.daily_run_step('raid','공방 약탈',c.daily_guild_raid)
        self.assertEqual(self.clicked.count('daily_raid_detail'),1)
        self.assertEqual(c.daily_detail()['input_request']['id'],request)
        other=RaidRetryTests();other.setUp();self.addCleanup(other.tmp.cleanup)
        other.c.daily_ledger=DailyLedger(c.daily_ledger.path)
        other.c.daily_run_step('raid','공방 약탈',other.c.daily_guild_raid)
        self.assertEqual(other.clicked.count('daily_raid_detail'),1)
        self.assertNotEqual(other.c.daily_detail()['input_request']['id'],request)
        self.assertFalse(other.c.daily_done('raid'))
    def test_transport_error_after_reservation_consumes_current_run_budget(self):
        c=self.c;click=c.device.click
        def lost_input(point):
            fighting=self.current is self.detail
            click(point)
            if fighting:raise Halt('transport lost')
        c.device.click=lost_input
        with self.assertRaisesRegex(Halt,'transport lost'):c.daily_guild_raid()
        request=c.daily_detail()['input_request']['id'];self.current=self.guild
        with self.assertRaises(OutcomeUnknown):c.daily_guild_raid()
        self.assertEqual(self.clicked.count('daily_raid_detail'),1)
        self.assertEqual(c.daily_detail()['input_request']['id'],request)
        self.assertFalse(c.daily_done('raid'))
    def test_read_only_unknown_inspection_does_not_inflate_existing_failures(self):
        c=self.c;c.daily_step='donation';c.last_screen=page('daily_donate')
        c.daily_checkpoint('uncertain',pending='donate_50',failures=7)
        def inspect():raise OutcomeUnknown('이전 입력 결과 미확인')
        for _ in range(3):c.daily_run_step('donation','기부',inspect)
        self.assertEqual(c.daily_detail()['failures'],7)
        self.assertEqual(c.daily_detail()['pending'],'donate_50')
    def test_new_input_unknown_counts_once_but_later_inspection_does_not(self):
        c=self.c;c.daily_step='donation';self.current=page('daily_donate','donate_50')
        def attempt():
            c.daily_tap(self.current,'donate_50',before_input=lambda:c.daily_checkpoint('uncertain',pending='donate_50'))
            raise OutcomeUnknown('결과 미확인')
        c.daily_run_step('donation','기부',attempt)
        self.assertEqual(c.daily_detail()['failures'],1)
        def inspect():raise OutcomeUnknown('결과 미확인')
        c.daily_run_step('donation','기부',inspect)
        self.assertEqual(c.daily_detail()['failures'],1)

if __name__=='__main__':unittest.main()
