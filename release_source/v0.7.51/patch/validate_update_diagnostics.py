"""Persistent update failure evidence and first collection evidence across restarts."""
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile
import numpy as np
import exe_updater as exe
from diagnostics import export_diagnostics, save_collection_failure
from execution_trace import ExecutionTrace
from ui_updates import Updates


def blocked():
    error=OSError('application control blocked this file');error.winerror=4551
    return error


class UpdateDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.data=Path(self.temp.name);self.work=self.data/'updates'/'release-test'
        (self.work/'stage').mkdir(parents=True)
        self.target=self.data/'app.exe';self.target.write_bytes(b'MZ old')
        incoming=self.work/'stage'/exe.EXE_NAME;incoming.write_bytes(b'MZ new')
        self.job={'format':'exe','data':str(self.data),'work':str(self.work),'target':str(self.target),
                  'source_version':'0.7.45','version':'0.7.47','sha256':exe.digest(incoming),'status':'prepared'}

    def fail_install(self):
        with patch.object(exe.subprocess,'run',side_effect=blocked()):
            with self.assertRaises(OSError):exe.install(self.job)

    def test_health_policy_failure_keeps_stage_versions_path_before_and_after_rollback(self):
        self.fail_install()
        self.assertEqual(self.target.read_bytes(),b'MZ old')
        path=self.data/'update_failure_latest.json'
        self.assertTrue(path.is_file(),'failure was discarded instead of retained in data')
        failure=json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual((failure['stage'],failure['winerror'],failure['rollback']),('health_check',4551,'succeeded'))
        self.assertEqual((failure['source_version'],failure['target_version']),('0.7.45','0.7.47'))
        self.assertEqual(failure['path'],str(self.target));self.assertTrue(failure['created_at'])
        log=(self.data/'update.log').read_text(encoding='utf-8')
        self.assertIn('pending',log);self.assertIn('succeeded',log)
        initial=json.loads((self.data/'update_failure_first.json').read_text(encoding='utf-8'))
        self.assertEqual(initial['rollback'],'succeeded','first evidence must include its eventual rollback result')

    def test_failed_rollback_preserves_original_error_and_does_not_relaunch(self):
        original=exe.replace_file
        def replace(source,target):
            if Path(source).name=='backup.exe':raise PermissionError('rollback access denied')
            original(source,target)
        exe.atomic_json(self.work/'exe-job.json',self.job)
        with patch.object(exe,'replace_file',side_effect=replace),patch.object(exe.subprocess,'run',side_effect=blocked()),patch.object(exe.subprocess,'Popen') as launch:
            exe.worker(self.work/'exe-job.json')
            self.assertFalse(launch.called,'failed rollback must not launch the unverified target')
        path=self.data/'update_failure_latest.json'
        self.assertTrue(path.is_file(),'rollback failure erased original policy failure')
        failure=json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(failure['winerror'],4551);self.assertEqual(failure['rollback'],'failed')
        self.assertIn('rollback access denied',failure['rollback_error'])
        result=json.loads((self.data/'update_result.json').read_text(encoding='utf-8'))
        self.assertIn('4551',result['message'])

    def test_later_recovery_updates_rollback_outcome_without_replacing_original_cause(self):
        self.fail_install()
        self.target.write_bytes(b'MZ new')
        self.job['status']='applying';self.job['failure']['rollback']='failed'
        exe.atomic_json(self.work/'exe-job.json',self.job)
        with patch.object(exe.subprocess,'Popen'):
            exe.worker(self.work/'exe-job.json',recover=True)
        self.assertEqual(self.target.read_bytes(),b'MZ old')
        job=json.loads((self.work/'exe-job.json').read_text(encoding='utf-8'))
        self.assertEqual(job['failure']['rollback'],'succeeded')
        self.assertEqual(job['failure']['winerror'],4551)
        self.assertEqual(job['failure']['stage'],'health_check')

    def test_export_contains_retained_failures_and_bounded_transaction_text_not_exes(self):
        self.fail_install()
        (self.work/'health.progress.json').write_text('{"step":"boot"}')
        (self.work/'health.threads.log').write_text('thread context')
        (self.work/'helper.exe').write_bytes(b'MZ helper')
        (self.work/'download.zip').write_bytes(b'package')
        export_diagnostics(self.data,self.data/'export.zip')
        with zipfile.ZipFile(self.data/'export.zip') as archive:
            names=archive.namelist()
            self.assertIn('update_failure_first.json',names)
            self.assertIn('update_failure_latest.json',names)
            self.assertIn('updates/release-test/exe-job.json',names)
            self.assertIn('updates/release-test/health.progress.json',names)
            self.assertFalse(any(n.endswith('.exe') or n.endswith('download.zip') for n in names))

    def test_startup_result_is_retained_after_ui_reads_it(self):
        result={'ok':False,'message':'EXE update blocked [WinError 4551]'}
        exe.atomic_json(self.data/'update_result.json',result)
        app=SimpleNamespace(root=Mock(),feed_url=lambda:'https://example.test',log=lambda value:None,auto_check_updates=lambda:None)
        with patch('ui_updates.tk.StringVar',return_value=Mock()):Updates.setup_updates(app,self.data,self.data)
        self.assertTrue((self.data/'update_result.json').is_file(),'startup consumed the only result evidence')

    def test_blocked_release_does_not_schedule_unrequested_retry_but_manual_and_new_release_can(self):
        self.fail_install()
        for version,manual,scheduled in [('0.7.47',False,False),('0.7.47',True,True),('0.7.48',True,True)]:
            calls=[]
            app=SimpleNamespace(update_data=self.data,update_requested=manual,update_manual_retry=manual,
                update_pending=Mock(),update_message=Mock(),update_button=Mock(),schedule_update_continue=lambda:calls.append('continue'))
            with patch.object(exe.sys,'frozen',True,create=True):
                Updates.handle_update_event(app,'update_checked',{'version':version,'sha256':'a'*64})
            self.assertEqual(bool(calls),scheduled)
            if version=='0.7.47' and not manual:
                self.assertIn('4551',app.update_message.set.call_args.args[0])
                self.assertIsNone(app.update_info)

    def test_helper_policy_failure_keeps_prepared_job_and_clears_queued_install(self):
        from version import VERSION
        app=SimpleNamespace(update_busy=lambda:False,update_applying=False,busy=lambda:False,
            save=lambda:None,update_base=self.data,update_data=self.data,update_work=self.work,
            update_meta={'version':'0.7.47','files':{exe.EXE_NAME:self.job['sha256']}},
            update_pending=Mock(),update_message=Mock(),log=lambda value:None)
        with patch.object(exe.sys,'frozen',True,create=True),patch.object(exe.sys,'executable',str(self.target)),patch('ui_updates.prepare_job',side_effect=exe.prepare_job),patch('ui_updates.start_helper',side_effect=blocked()):
            Updates.apply_update(app)
        job=json.loads((self.work/'exe-job.json').read_text(encoding='utf-8'))
        self.assertEqual(job.get('format'),'exe','diagnostic write corrupted the prepared transaction')
        self.assertEqual(job['sha256'],self.job['sha256']);self.assertEqual(job['source_version'],VERSION)
        self.assertIsNone(app.update_meta);self.assertFalse(app.update_requested)
        failure=json.loads((self.data/'update_failure_latest.json').read_text(encoding='utf-8'))
        self.assertEqual(failure['stage'],'start_helper');self.assertTrue(exe.policy_blocked(self.data,'0.7.47'))

    def test_later_block_does_not_erase_earlier_release_suppression(self):
        self.fail_install();self.job['version']='0.7.48';self.fail_install()
        self.assertTrue(exe.policy_blocked(self.data,'0.7.47'))
        self.assertTrue(exe.policy_blocked(self.data,'0.7.48'))
        self.assertFalse(exe.policy_blocked(self.data,'0.7.49'))

    def test_original_update_failure_survives_later_attempt(self):
        self.fail_install();first=self.data/'update_failure_first.json'
        self.assertTrue(first.exists(),'first failure snapshot missing')
        original=first.read_bytes()
        self.job['version']='0.7.48'
        self.fail_install()
        self.assertEqual(first.read_bytes(),original)
        self.assertEqual(json.loads((self.data/'update_failure_latest.json').read_text(encoding='utf-8'))['target_version'],'0.7.48')

    def test_first_collection_failure_survives_a_new_run_and_is_exported_with_metadata(self):
        ident='a'*24;image=np.zeros((540,960,3),np.uint8)
        trace=ExecutionTrace();trace.task='daily_guild';trace.step='relic';first_run=trace.run_id
        screen=SimpleNamespace(state='daily_relic',diagnostics={})
        save_collection_failure(self.data,ident,image,screen,'first failure','daily_guild',trace=trace)
        trace=ExecutionTrace();trace.task='daily_guild';trace.step='relic'
        save_collection_failure(self.data,ident,image+100,screen,'later failure','daily_guild',trace=trace)
        export_diagnostics(self.data,self.data/'export.zip')
        with zipfile.ZipFile(self.data/'export.zip') as archive:
            name=f'first_{ident}_daily_guild_error.json'
            self.assertIn(name,archive.namelist(),'later run replaced all initial failure evidence')
            meta=json.loads(archive.read(name));self.assertEqual(meta['run_id'],first_run)
            self.assertEqual(meta['reason'],'first failure');self.assertTrue(meta['created_at']);self.assertTrue(meta['version'])
            with zipfile.ZipFile(io.BytesIO(archive.read(f'first_{ident}_daily_guild_relic_initial.zip'))) as initial:
                self.assertEqual(json.loads(initial.read('failure.json'))['run_id'],first_run)
            self.assertEqual(json.loads(archive.read(f'last_{ident}_daily_guild_error.json'))['reason'],'later failure')


if __name__=='__main__':unittest.main()
