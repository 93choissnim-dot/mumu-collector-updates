"""Regression cases found during the v0.7.10 usability review."""
import copy
from datetime import datetime,timedelta,timezone
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from global_hotkey import KeyEdges
from profile_edits import merge_profiles,copy_settings
from history import History
from ui_state import retry_tasks,player_summary
from ui_layout import fit_size
from ui_updates import Updates
from run_control import RunControl
from fleet_runner import run_fleet
import exe_updater


def profiles():
    return {key:{'name':key,'serial':key,'enabled':key=='a','minutes':60,
                 'selected':{'farm':True,'ranking':True,'training':False},'restore_sleep':True} for key in ('a','b','c')}


class SettingsTests(unittest.TestCase):
    def test_saving_interval_preserves_new_roster_selection(self):
        original=profiles();draft=copy.deepcopy(original);current=copy.deepcopy(original)
        draft['a']['minutes']='30';current['b']['enabled']=True
        merged=merge_profiles(current,original,draft)
        self.assertTrue(merged['b']['enabled']);self.assertEqual(merged['a']['minutes'],30)
        self.assertEqual(current['a']['minutes'],60)

    def test_independent_task_edits_merge_and_new_players_survive(self):
        original=profiles();draft=copy.deepcopy(original);current=copy.deepcopy(original)
        draft['a']['selected']['farm']=False;current['a']['selected']['training']=True
        current['d']=copy.deepcopy(current['a'])
        merged=merge_profiles(current,original,draft)
        self.assertFalse(merged['a']['selected']['farm']);self.assertTrue(merged['a']['selected']['training'])
        self.assertEqual(merged['d'],current['d'])

    def test_conflicting_same_field_is_not_overwritten(self):
        original=profiles();draft=copy.deepcopy(original);current=copy.deepcopy(original)
        draft['a']['minutes']=30;current['a']['minutes']=15
        with self.assertRaises(ValueError):merge_profiles(current,original,draft)
        self.assertEqual(current['a']['minutes'],15)

    def test_bulk_copy_changes_draft_fields_only(self):
        current=profiles();draft=copy.deepcopy(current);draft['a']['minutes']=15
        draft['a']['selected']['farm']=False;draft['a']['restore_sleep']=False
        self.assertEqual(copy_settings(draft,'a',['b'],['selected','minutes']),1)
        self.assertEqual(draft['b']['minutes'],15);self.assertFalse(draft['b']['selected']['farm'])
        self.assertFalse(draft['b']['enabled']);self.assertTrue(draft['b']['restore_sleep'])
        self.assertEqual(current['b']['minutes'],60);self.assertEqual(draft['c'],current['c'])
        draft['a']['selected']['farm']=True;self.assertFalse(draft['b']['selected']['farm'])

    def test_invalid_bulk_targets_and_selection(self):
        with self.assertRaises(ValueError):copy_settings(profiles(),'a',['a'],['minutes'])
        with self.assertRaises(ValueError):copy_settings(profiles(),'a',['b'],['enabled'])
        original=profiles();draft=copy.deepcopy(original);draft['a']['selected']={}
        with self.assertRaises(ValueError):merge_profiles(original,original,draft)

    def test_sleep_restore_is_mandatory_even_for_old_disabled_setting(self):
        original=profiles();original['a']['restore_sleep']=False
        merged=merge_profiles(original,copy.deepcopy(original),copy.deepcopy(original))
        self.assertTrue(merged['a']['restore_sleep'])
        from fleet_ui import FleetUI
        app=SimpleNamespace(config={'players':copy.deepcopy(original),'restore_sleep':False})
        FleetUI.init_fleet(app)
        self.assertTrue(app.config['restore_sleep']);self.assertTrue(app.players['a']['restore_sleep'])


class KeyTests(unittest.TestCase):
    def test_brief_press_is_latched_without_polling(self):
        key=KeyEdges('F8')
        self.assertTrue(key.event(0x77,True));self.assertFalse(key.event(0x77,False))

    def test_repeat_and_held_key_never_retrigger(self):
        key=KeyEdges('F8',[0x77])
        self.assertFalse(key.event(0x77,True));key.event(0x77,False)
        self.assertTrue(key.event(0x77,True));self.assertFalse(key.event(0x77,True))

    def test_exact_modifiers_and_both_sides(self):
        key=KeyEdges('Ctrl+F8')
        key.event(0xa2,True);key.event(0xa3,True);key.event(0xa2,False)
        self.assertTrue(key.event(0x77,True));key.event(0x77,False)
        key.event(0xa0,True);self.assertFalse(key.event(0x77,True));key.event(0x77,False)
        key.event(0xa0,False);key.event(0xa3,False);self.assertFalse(key.event(0x77,True))

    def test_unrelated_typed_keys_are_not_retained(self):
        key=KeyEdges('F8')
        for code in range(65,91):self.assertFalse(key.event(code,True))
        self.assertEqual(key.down,set())


class UpdatePauseTests(unittest.TestCase):
    def test_paused_update_stops_without_another_collection(self):
        control=RunControl();pending=threading.Event();waiting=threading.Event();seen=[]
        def event(kind,value):
            if kind=='fleet_wait':control.pause();waiting.set()
        def execute(job,rooms):seen.append(job['id']);return {r:'skipped' for r in rooms}
        worker=threading.Thread(target=run_fleet,args=([{'id':'a','name':'a','rooms':['farm'],'minutes':60}],True,control,pending,execute,event),daemon=True)
        worker.start()
        try:
            self.assertTrue(waiting.wait(2))
            app=SimpleNamespace(update_continue_scheduled=False,closing=False,update_requested=True,update_applying=False,
                update_busy=lambda:False,update_meta={'version':'test'},update_pending=pending,busy=worker.is_alive,
                update_message=Mock(),schedule_update_continue=Mock(),apply_update=Mock(),stop=control,stop_run=control.set)
            Updates.continue_update(app);worker.join(1)
            self.assertFalse(worker.is_alive());self.assertEqual(seen,['a'])
            Updates.continue_update(app);app.apply_update.assert_called_once()
        finally:control.set();worker.join(2)

    def test_active_work_is_allowed_to_finish(self):
        control=RunControl();stop_run=Mock()
        app=SimpleNamespace(update_continue_scheduled=False,closing=False,update_requested=True,update_applying=False,
            update_busy=lambda:False,update_meta={'version':'test'},update_pending=threading.Event(),busy=lambda:True,
            update_message=Mock(),schedule_update_continue=Mock(),apply_update=Mock(),stop=control,stop_run=stop_run)
        Updates.continue_update(app);stop_run.assert_not_called();app.apply_update.assert_not_called()
        self.assertTrue(app.update_pending.is_set())


class HistoryTests(unittest.TestCase):
    def test_kst_midnight_counter_ignores_host_timezone(self):
        with tempfile.TemporaryDirectory() as folder:
            h=History(Path(folder)/'history.json')
            h.record('a','farm','collected',now='2026-09-21T14:59:59+00:00')
            h.record('a','farm','collected',now='2026-09-21T15:00:00+00:00')
            self.assertEqual(h.stats('a',day='2026-09-21')['today'],1)
            self.assertEqual(h.stats('a',day='2026-09-22')['today'],1)
            with patch('history.datetime',wraps=datetime) as clock:
                clock.now.return_value=datetime(2026,9,21,15,1,tzinfo=timezone.utc)
                self.assertEqual(h.stats('a')['today'],1)

    def test_failed_write_never_changes_live_or_restarted_history(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'history.json';h=History(path)
            h.record('a','farm','failed',reason='original')
            before=h.get('a','farm');disk=path.read_bytes()
            for operation in (lambda:h.record('a','farm','collected'),lambda:h.issue('a','farm','new reason'),lambda:h.record('b','farm','collected')):
                with patch.object(Path,'replace',side_effect=OSError('disk failure')):
                    with self.assertRaises(OSError):operation()
                self.assertEqual(h.get('a','farm'),before)
                self.assertEqual(h.get('b','farm'),{})
                self.assertEqual(path.read_bytes(),disk)
                self.assertEqual(History(path).get('a','farm'),before)
            h.record('a','farm','collected')
            self.assertEqual(sum(h.get('a','farm')['daily'].values()),1)

    def test_read_result_cannot_mutate_stored_nested_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            h=History(Path(folder)/'history.json');h.record('a','farm','collected')
            result=h.get('a','farm');result['daily'].clear()
            self.assertEqual(sum(h.get('a','farm')['daily'].values()),1)

    def test_player_snapshot_preserves_legacy_fallback_without_aliasing(self):
        with tempfile.TemporaryDirectory() as folder:
            h=History(Path(folder)/'history.json')
            h.record('serial','farm','collected')
            h.record('player','wood','failed')
            snapshot=h.snapshot('player','serial')
            self.assertEqual(snapshot['farm']['result'],'collected')
            self.assertEqual(snapshot['wood']['result'],'failed')
            snapshot['farm']['daily'].clear()
            self.assertTrue(h.get('serial','farm')['daily'])
            h.record('player','farm','skipped')
            self.assertEqual(h.snapshot('player','serial')['farm']['result'],'skipped')

    def test_legacy_results_survive_and_unknown_old_counts_are_not_invented(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'history.json'
            path.write_text(json.dumps({'a':{'farm':{'result':'collected','collected_at':'2026-09-19T10:00:00+00:00'}}}))
            history=History(path)
            self.assertEqual(history.stats('a',day='2026-09-19')['today'],0)
            history.record('a','farm','failed',now='2026-09-20T10:00:00+00:00',reason='연결 끊김')
            self.assertEqual(history.get('a','farm')['collected_at'],'2026-09-19T10:00:00+00:00')
            self.assertEqual(History(path).get('a','farm')['reason'],'연결 끊김')

    def test_daily_successes_failure_streak_and_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'history.json';h=History(path)
            stamp=datetime.now().astimezone().replace(hour=12).isoformat();day=datetime.fromisoformat(stamp).date().isoformat()
            h.record('a','farm','collected',now=stamp);h.record('a','farm','collected',now=stamp)
            h.record('a','farm','attempted',now=stamp);h.record('a','farm','failed',now=stamp)
            h.issue('a','farm','화면 인식 실패')
            self.assertEqual(h.get('a','farm')['consecutive_failures'],2)
            self.assertEqual(History(path).stats('a',day=day)['today'],2)
            self.assertEqual(h.get('a','farm')['reason'],'화면 인식 실패')
            h.record('a','farm','skipped',now=stamp)
            self.assertEqual(h.get('a','farm')['consecutive_failures'],0)
            self.assertEqual(h.get('a','farm')['reason'],'')
            self.assertEqual(h.stats('a',day=(datetime.fromisoformat(stamp)+timedelta(days=1)).date().isoformat())['today'],0)

    def test_daily_counters_have_bounded_retention(self):
        with tempfile.TemporaryDirectory() as folder:
            h=History(Path(folder)/'history.json')
            for day in range(45):h.record('a','farm','collected',now=(datetime(2026,1,1,12,tzinfo=timezone.utc)+timedelta(days=day)).isoformat())
            self.assertEqual(len(h.get('a','farm')['daily']),30)

    def test_retry_only_currently_selected_failed_tasks(self):
        p=profiles()['a'];entries={'farm':{'result':'collected'},'ranking':{'result':'attempted'},'training':{'result':'failed'}}
        self.assertEqual(retry_tasks(p,entries),['ranking'])
        self.assertEqual(retry_tasks(p,entries,['farm','training']),[])
        self.assertEqual(retry_tasks(p,entries,['ranking']),['ranking'])

    def test_persisted_issue_does_not_fake_progress(self):
        p=profiles()['a'];s=player_summary(p,{'history_issue':True,'status':'수령 중','rooms':['farm'],'results':{}},True,True,False,10)
        self.assertEqual(s['completed'],0);self.assertEqual(s['status'],'수령 중');self.assertTrue(s['issue'])

    def test_stale_or_other_task_snapshot_not_shown(self):
        from diagnostics import failure_snapshot
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);ident='a'*24;stem=root/('last_'+ident+'_farm_error')
            stem.with_suffix('.png').write_bytes(b'fixture')
            stem.with_suffix('.json').write_text(json.dumps({'task':'farm','created_at':'2026-09-20T12:00:00+00:00'}))
            self.assertIsNotNone(failure_snapshot(root,ident,'farm','2026-09-20T11:00:00+00:00'))
            self.assertIsNone(failure_snapshot(root,ident,'farm','2026-09-20T13:00:00+00:00'))
            self.assertIsNone(failure_snapshot(root,ident,'ranking'))
            self.assertIsNone(failure_snapshot(root,'../../outside','farm'))


class LayoutTests(unittest.TestCase):
    def test_scaled_clients_fit_entire_monitor_work_area(self):
        for width,height in [(1366,728),(1024,728),(1920,1040)]:
            for scale in (1,1.25,1.5):
                with self.subTest(width=width,height=height,scale=scale):
                    size,minimum=fit_size((0,0,width,height),scale,(1220,820),(680,430))
                    self.assertLessEqual(size[0]*scale+24,width);self.assertLessEqual(size[1]*scale+60,height)
                    self.assertTrue(all(minimum[i]<=size[i] for i in (0,1)))


class CleanupTests(unittest.TestCase):
    def test_only_old_completed_jobs_for_this_exe_are_deleted(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);data=root/'data';target=root/'app.exe';target.write_bytes(b'old')
            workspaces={}
            for index,status in enumerate(['complete','complete','rolled_back','prepared','applying']):
                work=data/'updates'/('release-'+str(index));work.mkdir(parents=True);workspaces[index]=work
                (work/'stage').mkdir();(work/'stage'/'incoming.exe').write_bytes(b'new')
                for name in ['download.zip','helper.exe','backup.exe']:(work/name).write_bytes(b'fixture')
                job=work/'exe-job.json';job.write_text(json.dumps({'format':'exe','target':str(target),'work':str(work),'status':status}))
                os.utime(job,(100+index,100+index))
            other=data/'updates'/'release-other';other.mkdir()
            (other/'exe-job.json').write_text(json.dumps({'format':'exe','target':str(root/'other.exe'),'work':str(other),'status':'complete'}))
            unknown=data/'updates'/'release-unknown';unknown.mkdir();(unknown/'private.txt').write_text('preserve')
            exe_updater.cleanup_updates(data,target=target)
            self.assertFalse(workspaces[0].exists())
            for i in (1,2):
                self.assertTrue((workspaces[i]/'backup.exe').exists());self.assertFalse((workspaces[i]/'download.zip').exists());self.assertFalse((workspaces[i]/'stage').exists())
            for i in (3,4):self.assertTrue((workspaces[i]/'stage'/'incoming.exe').exists())
            self.assertTrue(other.exists());self.assertTrue((unknown/'private.txt').exists())

    def test_source_cleanup_preserves_exe_jobs(self):
        from updater import cleanup_updates
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder);work=data/'updates'/'release-exe';work.mkdir(parents=True)
            (work/'exe-job.json').write_text('{}');(work/'backup.exe').write_bytes(b'old')
            cleanup_updates(data);self.assertTrue((work/'backup.exe').exists())

    def test_updates_directory_link_is_not_followed(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);data=root/'data';data.mkdir();outside=root/'outside';outside.mkdir()
            try:(data/'updates').symlink_to(outside,target_is_directory=True)
            except OSError:self.skipTest('Symlinks not available')
            exe_updater.cleanup_updates(data,target=root/'app.exe');self.assertTrue(outside.exists())


if __name__=='__main__':unittest.main()
