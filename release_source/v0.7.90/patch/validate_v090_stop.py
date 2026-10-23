"""Complete stop cancels real worker/watch controls before saving UI settings."""
import importlib.util
import json
from pathlib import Path
import queue
import tempfile
import threading
from types import SimpleNamespace
import unittest

from fleet_runner import run_fleet
from game_watch import GameWatch
from run_control import RunControl


class Value:
    def __init__(self, value=None):self.value=value
    def get(self):return self.value
    def set(self, value):self.value=value


class Widget:
    def __init__(self):self.options={}
    def configure(self, **options):self.options.update(options)


class CompleteStopTests(unittest.TestCase):
    def setUp(self):
        # Missing feature is an assertion failure before importing the new mixin.
        self.assertIsNotNone(importlib.util.find_spec('ui_safety'), 'complete stop mixin is missing')
        from ui_safety import SafetyUI
        self.stop_all=SafetyUI.stop_all
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path=Path(self.directory.name)/'settings.json'
        self.events=[];self.logs=[]
        self.app=SimpleNamespace(
            stop=RunControl(),game_watch=GameWatch(self.events.append),
            watch_value=Value(True),config={'game_watch':True},
            pause_button=Widget(),watch_status=Widget(),status=Value(),
            countdown=Value('예약 대기'),next_at=100,
            fleet_states={'a':{'next_at':100}},busy=lambda:False,
            log=self.logs.append,update_pending=threading.Event(),update_applying=False,
        )
        def save():
            from record_storage import save_json
            save_json(self.path,self.app.config)
        self.app.save=save
        self.app.game_watch.enable(True)

    def assert_stopped(self):
        self.assertTrue(self.app.stop.is_set())
        self.assertFalse(self.app.game_watch.enabled)
        self.assertFalse(self.app.watch_value.get())
        self.assertFalse(self.app.config['game_watch'])
        self.assertIsNone(self.app.next_at)
        self.assertIsNone(self.app.fleet_states['a']['next_at'])
        self.assertEqual(self.app.countdown.get(),'예약 없음')

    def test_idle_complete_stop_persists_disabled_watch(self):
        self.stop_all(self.app)
        self.assert_stopped()
        self.assertFalse(json.loads(self.path.read_text())['game_watch'])
        self.assertIn('완전 중지',self.app.status.get())

    def test_paused_worker_is_released_and_remains_stopped(self):
        self.app.stop.pause();done=threading.Event();answers=[]
        thread=threading.Thread(target=lambda:(answers.append(self.app.stop.wait(60)),done.set()),daemon=True)
        thread.start()
        try:
            self.stop_all(self.app)
            self.assertTrue(done.wait(1));self.assertEqual(answers,[True])
            self.assertFalse(self.app.stop.paused)
            self.assert_stopped()
            self.assertEqual(self.app.pause_button.options['state'],'disabled')
        finally:self.app.stop.set();thread.join(1)

    def test_active_watch_cannot_dispatch_after_complete_stop(self):
        prepared=threading.Event();release=threading.Event();inputs=[]
        def prepare(job,control):
            prepared.set();release.wait(2)
            return SimpleNamespace(attempts=0,device=SimpleNamespace(),recover=lambda:inputs.append('launch'))
        thread=threading.Thread(target=lambda:self.app.game_watch.scan([{'id':'a','enabled':True}],prepare),daemon=True)
        thread.start()
        try:
            self.assertTrue(prepared.wait(1));control=self.app.game_watch.control
            self.stop_all(self.app)
            self.assertTrue(control.is_set());release.set();thread.join(1)
            self.assertFalse(thread.is_alive());self.assertEqual(inputs,[])
            self.assert_stopped()
        finally:release.set();self.app.game_watch.enable(False);thread.join(1)

    def test_repeat_schedule_stops_before_second_collection(self):
        waiting=threading.Event();collections=[]
        def event(kind,value):
            if kind=='fleet_wait':waiting.set()
        thread=threading.Thread(target=lambda:run_fleet(
            [{'id':'a','name':'A','rooms':['farm'],'minutes':1}],True,
            self.app.stop,self.app.update_pending,
            lambda job,rooms:(collections.append(job['id']) or {'farm':'collected'}),event),daemon=True)
        thread.start()
        try:
            self.assertTrue(waiting.wait(1));self.stop_all(self.app);thread.join(1)
            self.assertFalse(thread.is_alive());self.assertEqual(collections,['a'])
            self.assert_stopped()
        finally:self.app.stop.set();thread.join(1)

    def test_clearing_worker_stop_does_not_reenable_passive_watch(self):
        from ui_game_watch import GameWatchUI
        self.stop_all(self.app);self.app.stop.clear();prepared=[]
        self.app.game_watch.scan([{'id':'a','enabled':True}],lambda *args:prepared.append(args))
        self.assertEqual(prepared,[]);self.assertFalse(self.app.game_watch.enabled)
        self.app.watch_value.set(True);GameWatchUI.toggle_game_watch(self.app)
        self.assertTrue(self.app.game_watch.enabled)
        self.assertTrue(json.loads(self.path.read_text())['game_watch'])

    def test_save_failure_does_not_restore_worker_or_watch(self):
        def fail_save():
            self.assert_stopped()
            raise OSError('disk full')
        self.app.save=fail_save
        self.stop_all(self.app)
        self.assert_stopped();self.assertIn('저장',self.app.status.get())
        self.assertTrue(any('disk full' in message for message in self.logs))

    def test_complete_stop_does_not_cancel_update_replacement(self):
        self.app.update_pending.set();self.app.update_applying=True
        self.stop_all(self.app)
        self.assertTrue(self.app.update_pending.is_set());self.assertTrue(self.app.update_applying)
        self.assert_stopped()

    def prepare_worker(self):
        from app import App
        self.app.worker=None;self.app.worker_pending=None;self.app.worker_generation=0
        self.app.busy=lambda:App.busy(self.app)
        self.app.device_lane=threading.RLock();self.app.events=queue.Queue()
        self.app.stop_hotkey=SimpleNamespace(reset=lambda:None)
        self.app.set_busy=lambda value:None
        self.app.sync_stop_key=lambda:None
        return App.run_worker

    def test_worker_queued_for_device_lane_never_enters_operation_after_stop(self):
        run_worker=self.prepare_worker();dispatched=[]
        with self.app.device_lane:
            run_worker(self.app,lambda:dispatched.append('connect'),'연결 중')
            self.stop_all(self.app)
        self.app.worker.join(1)
        self.assertFalse(self.app.worker.is_alive())
        self.assertEqual(dispatched,[])
        self.assertTrue(self.app.stop.is_set())

    def test_explicit_new_run_after_complete_stop_can_collect_with_watch_off(self):
        run_worker=self.prepare_worker();dispatched=[]
        self.stop_all(self.app)
        run_worker(self.app,lambda:dispatched.append('collect'),'수령 중')
        self.app.worker.join(1)
        self.assertFalse(self.app.worker.is_alive())
        self.assertEqual(dispatched,['collect'])
        self.assertFalse(self.app.stop.is_set())
        self.assertFalse(self.app.game_watch.enabled)

    def test_queued_startup_connection_does_not_restart_after_complete_stop(self):
        from fleet_ui import FleetUI
        connected=[];self.app.closing=False;self.app.connect=lambda:connected.append(True)
        self.stop_all(self.app)
        FleetUI.auto_connect(self.app)
        self.assertEqual(connected,[])
        self.assert_stopped()

    def test_startup_connection_still_runs_before_any_stop(self):
        from fleet_ui import FleetUI
        connected=[];self.app.closing=False;self.app.connect=lambda:connected.append(True)
        FleetUI.auto_connect(self.app)
        self.assertEqual(connected,[True])


if __name__=='__main__':unittest.main()
