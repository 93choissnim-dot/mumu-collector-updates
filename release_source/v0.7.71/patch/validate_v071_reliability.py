"""Storage failures stop automation; pending evidence and waiting UI stay truthful."""
import errno
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from action_state import ActionState
from daily_state import LedgerError, ManualQuestLedger
from fleet_runner import run_fleet
from history import History
from run_support import cycle_with_recovery
from ui_state import player_summary


class FatalStorageTests(unittest.TestCase):
    def test_storage_error_cannot_launch_game_or_repeat_cycle(self):
        from validate_game_recovery import GameRecoveryTests
        android, device, recovery, _ = GameRecoveryTests().setup_recovery()
        android.is_connected = lambda _: True
        calls=[]
        collector=SimpleNamespace(results={},claim_counts={},action_state=ActionState(),
            daily_ledger=None,forget_observations=lambda:None)
        def cycle(rooms,restore):
            calls.append(list(rooms))
            if len(calls)==1:raise LedgerError('disk full')
            return {'farm':'skipped'}
        collector.cycle=cycle
        with self.assertRaisesRegex(LedgerError,'disk full'):
            cycle_with_recovery(collector,['farm'],False,android,device,recovery.vision,
                android.stop,lambda _:None,game_recovery=recovery)
        self.assertEqual(android.launches(),[])
        self.assertEqual(calls,[['farm']])

    def test_storage_error_stops_remaining_accounts_and_retry_schedule(self):
        jobs=[{'id':key,'name':key,'rooms':['farm'],'minutes':1} for key in ('a','b')]
        calls=[]
        def execute(job,rooms):
            calls.append(job['id'])
            if job['id']=='a':raise LedgerError('disk full')
            return {'farm':'skipped'}
        with self.assertRaises(LedgerError):
            run_fleet(jobs,False,threading.Event(),threading.Event(),execute,lambda *_:None)
        self.assertEqual(calls,['a'])

    def test_real_fleet_launch_propagates_damaged_ledger_before_device_input(self):
        from validate_fleet import ManualLaunchTests
        import app
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'action_state.json').write_text('{broken')
            a=ManualLaunchTests().app();a.log=lambda _:None;a.history=History(root/'history.json')
            with patch.object(app,'DATA',root):
                with self.assertRaises(LedgerError):a.launch('once')
            self.assertEqual((root/'action_state.json').read_text(),'{broken')
            self.assertFalse((root/'history.json').exists())

    def test_worker_disables_independent_recovery_after_storage_error(self):
        import queue
        from app import App
        from game_watch import GameWatch
        from run_control import RunControl
        watch=GameWatch(lambda _:None);watch.enable(True)
        a=SimpleNamespace(busy=lambda:False,update_applying=False,update_pending=threading.Event(),
            game_watch=watch,stop=RunControl(),status=SimpleNamespace(set=lambda _:None),
            stop_hotkey=SimpleNamespace(reset=lambda:None),set_busy=lambda _:None,
            device_lane=threading.Lock(),events=queue.Queue(),log=lambda _:None,sync_stop_key=lambda:None)
        def operation():raise LedgerError('disk full')
        App.run_worker(a,operation,'running');a.worker.join(timeout=5)
        self.assertFalse(a.worker.is_alive());self.assertFalse(watch.enabled)
        self.assertTrue(any(kind=='failed' for kind,value in list(a.events.queue)))


class WaitingSummaryTests(unittest.TestCase):
    def render(self,results):
        player={'id':'a','name':'a','enabled':True,'rooms':list(results),
                'selected':{k:True for k in results},'minutes':60}
        state={}
        def event(kind,value):
            if kind=='fleet_status':state.update(value[1])
        run_fleet([player],False,threading.Event(),threading.Event(),lambda *_:results,event)
        state['results']=results
        return player_summary(player,state,True,False,False,0)
    def test_waiting_only_is_not_a_failure(self):
        result=self.render({'worldboss':'waiting'})
        self.assertEqual(result['status'],'정산 대기');self.assertFalse(result['issue'])
    def test_waiting_with_completed_rooms_is_not_a_failure(self):
        result=self.render({'worldboss':'waiting','farm':'collected'})
        self.assertEqual(result['status'],'정산 대기');self.assertFalse(result['issue'])
    def test_real_failure_still_takes_priority_over_waiting(self):
        result=self.render({'worldboss':'waiting','farm':'failed'})
        self.assertEqual(result['status'],'확인 필요');self.assertTrue(result['issue'])


class OtherRecordsStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
    def writer(self,kind):
        path=self.root/(kind+'.json')
        if kind=='history':
            obj=History(path);obj.record('a','farm','failed')
            write=lambda:obj.record('b','wood','collected')
        else:
            obj=ManualQuestLedger(path)
            obj.checkpoint('a','daily_guild','donation','uncertain',pending='donate_50')
            if kind=='daily':write=lambda:obj.mark('b','daily_guild','attendance')
            else:write=lambda:obj.begin_run('b',tasks=['daily_guild'])
        return path,obj,write
    def test_transient_windows_lock_retries_and_keeps_other_accounts(self):
        original=Path.replace
        for kind in ('daily','manual_begin','history'):
            for code in (32,33):
                with self.subTest(kind=kind,code=code):
                    path,obj,write=self.writer(kind);prior=json.loads(path.read_text(encoding='utf-8'))['a'];calls=[]
                    def replace(src,dst):
                        calls.append(1)
                        if len(calls)<3:
                            exc=PermissionError(errno.EACCES,'sharing violation');exc.winerror=code;raise exc
                        return original(src,dst)
                    with patch.object(Path,'replace',replace):write()
                    saved=json.loads(path.read_text(encoding='utf-8'))
                    self.assertEqual(saved['a'],prior);self.assertIn('b',saved)
                    self.assertEqual(len(calls),3)
                    path.unlink()
    def test_permanent_failure_preserves_memory_disk_and_pending(self):
        for kind in ('daily','manual_begin','history'):
            with self.subTest(kind=kind):
                path,obj,write=self.writer(kind);before=path.read_bytes();cached=json.dumps(obj.data,sort_keys=True)
                with patch.object(Path,'replace',side_effect=OSError(errno.ENOSPC,'disk full')):
                    with self.assertRaises((OSError,LedgerError)):write()
                self.assertEqual(path.read_bytes(),before)
                self.assertEqual(json.dumps(obj.data,sort_keys=True),cached)
                self.assertEqual(list(self.root.glob('*.tmp')),[])
                path.unlink()
    def test_fsync_failure_does_not_publish_new_record(self):
        for kind in ('daily','manual_begin','history'):
            with self.subTest(kind=kind):
                path,obj,write=self.writer(kind);before=path.read_bytes()
                with patch('os.fsync',side_effect=OSError(errno.ENOSPC,'disk full')):
                    with self.assertRaises((OSError,LedgerError)):write()
                self.assertEqual(path.read_bytes(),before)
                self.assertEqual(list(self.root.glob('*.tmp')),[])
                path.unlink()
    def test_unique_temporary_files_do_not_touch_someone_elses_file(self):
        for kind in ('daily','manual_begin','history'):
            with self.subTest(kind=kind):
                path,obj,write=self.writer(kind);other=path.with_suffix('.tmp');other.write_text('owned elsewhere')
                write()
                self.assertTrue(other.exists())
                self.assertEqual(other.read_text(),'owned elsewhere')
                other.unlink();path.unlink()
    def test_persistent_windows_lock_has_bounded_attempts(self):
        for kind in ('daily','manual_begin','history'):
            with self.subTest(kind=kind):
                path,obj,write=self.writer(kind);before=path.read_bytes();calls=[]
                def replace(src,dst):
                    calls.append(1);exc=PermissionError(errno.EACCES,'locked');exc.winerror=32;raise exc
                with patch.object(Path,'replace',replace):
                    with self.assertRaises((OSError,LedgerError)):write()
                self.assertEqual(len(calls),3)
                self.assertEqual(path.read_bytes(),before)
                self.assertEqual(list(self.root.glob('*.tmp')),[])
                path.unlink()


class HealthProgressTests(unittest.TestCase):
    def test_regression_failure_is_preserved_and_identified(self):
        from health_progress import run_suite
        def broken():raise AssertionError('deliberate failure')
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'health.json'
            result=run_suite(unittest.TestSuite([unittest.FunctionTestCase(broken)]),output)
            self.assertFalse(result.wasSuccessful());self.assertEqual(len(result.failures),1)
            progress=json.loads(output.with_suffix('.progress.json').read_text(encoding='utf-8'))
            self.assertIn('broken',progress['test']);self.assertEqual(progress['phase'],'finished')
            self.assertFalse(progress['successful'])
    def test_all_tests_run_and_success_is_not_inferred_from_start(self):
        from health_progress import run_suite
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'health.json';seen=[]
            def first():
                progress=json.loads(output.with_suffix('.progress.json').read_text(encoding='utf-8'))
                self.assertEqual(progress['phase'],'running');seen.append('first')
            def second():seen.append('second')
            result=run_suite(unittest.TestSuite([unittest.FunctionTestCase(first),unittest.FunctionTestCase(second)]),output)
            self.assertTrue(result.wasSuccessful());self.assertEqual(seen,['first','second'])
            lines=output.with_suffix('.tests.log').read_text(encoding='utf-8').splitlines()
            self.assertEqual(len(lines),2)

if __name__=='__main__':unittest.main()
