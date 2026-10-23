"""Update preference regression tests: persistence and asynchronous authorization."""
import json
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ui_updates import Updates


class Value:
    def __init__(self, value='', **kwargs):self.value=value
    def set(self, value):self.value=value
    def get(self):return self.value


class Scheduler:
    def __init__(self):self.callbacks={};self.sequence=0
    def after(self, delay, callback):
        self.sequence+=1;self.callbacks[self.sequence]=callback;return self.sequence
    def after_cancel(self, ident):self.callbacks.pop(ident,None)


class App(Updates):
    def __init__(self, folder, config):
        self.config=dict(config);self.root=Scheduler();self.events=queue.Queue()
        self.closing=False;self.working=False;self.save_failure=False;self.closed=False
        self.stop=SimpleNamespace(paused=False);self.stop_count=0
        self.update_button=Mock();self.logs=[];self.settings=folder/'settings.json'
        with patch('ui_updates.tk.StringVar',Value):self.setup_updates(folder,folder)
    def feed_url(self):return 'https://example.test/latest.json'
    def save(self):
        if self.save_failure:raise OSError('disk full')
        self.settings.write_text(json.dumps(self.config),encoding='utf-8')
    def log(self, message):self.logs.append(message)
    def busy(self):return self.working
    def stop_run(self):self.stop_count+=1;self.working=False
    def set_busy(self, value):self.working=value
    def close(self):self.closed=True
    def finish_task(self):
        if self.update_thread:self.update_thread.join(2)
        while not self.events.empty():self.handle_update_event(*self.events.get_nowait())


class UpdatePreferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        self.release={'version':'9.0.0','size':10,'notes':'수령 완료 확인 개선\n설정 저장 오류 안내'}
    def app(self, mode='notify'):
        return App(self.folder,{} if mode is None else {'update_mode':mode})
    def check(self, app, manual=True):
        with patch('ui_updates.check_feed',return_value=self.release):
            app.check_updates(manual=manual);app.finish_task()
    def prepared(self, app):
        app.update_info=dict(self.release);app.update_meta={'version':'9.0.0'};app.update_work=self.folder
    def test_missing_and_invalid_preferences_default_to_notify(self):
        for mode in (None,'broken'):
            app=self.app(mode);self.check(app)
            self.assertFalse(app.update_requested,'checking must not authorize install for existing settings')
            self.assertFalse(app.update_pending.is_set())
            self.assertFalse(app.update_continue_scheduled)
    def test_notify_checks_display_release_notes_without_download(self):
        app=self.app();self.check(app)
        self.assertEqual(app.update_info,self.release)
        self.assertIn(self.release['notes'],app.update_notes.get())
        self.assertFalse(app.update_requested)
        app.continue_update()
        self.assertFalse((self.folder/'updates').exists())
    def test_auto_background_check_requests_deferred_update(self):
        app=self.app('auto');self.check(app,manual=False)
        self.assertTrue(app.update_requested)
        self.assertTrue(app.update_continue_scheduled)
    def test_mode_persists_and_survives_reload(self):
        app=self.app();self.assertTrue(app.set_update_mode('auto'))
        saved=json.loads(app.settings.read_text(encoding='utf-8'))
        self.assertEqual(saved['update_mode'],'auto')
        reloaded=App(self.folder,saved);self.check(reloaded,manual=False)
        self.assertTrue(reloaded.update_requested)
    def test_save_failure_rolls_back_preference_and_pending_authorization(self):
        app=self.app('auto');app.save_failure=True;app.update_requested=True;app.update_pending.set()
        self.assertFalse(app.set_update_mode('notify'))
        self.assertEqual(app.config['update_mode'],'auto')
        self.assertEqual(app.update_mode_value.get(),'auto')
        self.assertTrue(app.update_requested);self.assertTrue(app.update_pending.is_set())
        self.assertIn('저장',app.update_message.get())
    def test_save_failure_does_not_leave_new_preference_in_legacy_config(self):
        app=self.app(None);app.save_failure=True
        self.assertFalse(app.set_update_mode('auto'))
        self.assertNotIn('update_mode',app.config)
        self.assertEqual(app.update_mode_value.get(),'notify')
    def test_switch_during_check_prevents_late_auto_download(self):
        app=self.app('auto');entered=threading.Event();finish=threading.Event()
        def feed(*args):entered.set();finish.wait(2);return self.release
        with patch('ui_updates.check_feed',side_effect=feed):
            app.check_updates();self.assertTrue(entered.wait(1))
            try:self.assertTrue(app.set_update_mode('notify'))
            finally:finish.set();app.finish_task()
        self.assertEqual(app.update_info,self.release)
        self.assertFalse(app.update_requested);self.assertFalse(app.update_continue_scheduled)
    def test_switch_after_check_invalidates_queued_continuation(self):
        app=self.app('auto');self.check(app)
        stale=list(app.root.callbacks.values())[-1]
        self.assertTrue(app.set_update_mode('notify'));stale()
        self.assertFalse(app.update_requested);self.assertFalse(app.update_pending.is_set())
        self.assertFalse((self.folder/'updates').exists())
    def test_switch_during_download_retains_prepared_release_without_apply(self):
        app=self.app('auto');self.check(app);entered=threading.Event();finish=threading.Event()
        def download(*args,**kwargs):entered.set();finish.wait(2);return {'version':'9.0.0'}
        with patch('ui_updates.download_update',side_effect=download):
            app.download_update();self.assertTrue(entered.wait(1))
            try:self.assertTrue(app.set_update_mode('notify'))
            finally:finish.set();app.finish_task()
        self.assertIsNotNone(app.update_meta)
        self.assertFalse(app.update_requested);self.assertFalse(app.update_pending.is_set())
        self.assertNotIn('자동 적용 중',app.update_message.get())
        with patch('ui_updates.start_helper') as helper:app.continue_update();helper.assert_not_called()
    def test_notify_switch_clears_prepared_wait_without_stopping_work(self):
        app=self.app('auto');self.prepared(app);app.working=True;app.update_requested=True
        app.continue_update();self.assertTrue(app.update_pending.is_set())
        self.assertTrue(app.set_update_mode('notify'));app.continue_update()
        self.assertFalse(app.update_pending.is_set());self.assertTrue(app.working)
        self.assertEqual(app.stop_count,0)
    def test_direct_apply_cannot_bypass_notify_preference(self):
        app=self.app();self.prepared(app);app.update_requested=True
        with patch('ui_updates.prepare_job',return_value=self.folder/'job.json'),patch('ui_updates.start_helper',return_value=SimpleNamespace(poll=lambda:None)) as helper:
            app.apply_update();helper.assert_not_called()
        self.assertFalse(app.closed)
    def test_explicit_apply_in_notify_launches_helper_after_work_finishes(self):
        app=self.app();self.prepared(app);app.working=True
        app.request_update_apply();app.continue_update()
        self.assertTrue(app.update_pending.is_set());self.assertFalse(app.closed)
        app.working=False
        with patch('ui_updates.prepare_job',return_value=self.folder/'job.json'),patch('ui_updates.start_helper',return_value=SimpleNamespace(poll=lambda:None)):
            app.continue_update()
        self.assertTrue(app.closed);self.assertTrue(app.update_applying)
    def test_explicit_apply_survives_notify_switch(self):
        app=self.app('auto');self.prepared(app);app.request_update_apply()
        self.assertTrue(app.set_update_mode('notify'))
        self.assertTrue(app.update_requested)
        with patch('ui_updates.prepare_job',return_value=self.folder/'job.json'),patch('ui_updates.start_helper',return_value=SimpleNamespace(poll=lambda:None)):
            app.continue_update()
        self.assertTrue(app.closed)
    def test_check_in_notify_does_not_convert_existing_auto_request_to_explicit(self):
        app=self.app('auto');self.prepared(app);app.update_requested=True
        app.set_update_mode('notify');app.check_updates();app.continue_update()
        self.assertFalse(app.update_requested);self.assertFalse(app.closed)
    def test_failed_explicit_attempt_clears_authorization_for_next_check(self):
        app=self.app();self.prepared(app);app.request_update_apply()
        app.handle_update_event('update_error','download failed')
        app.update_meta=None;self.check(app)
        self.assertFalse(app.update_requested);self.assertFalse(app.update_explicit_apply)


if __name__=='__main__':unittest.main()
