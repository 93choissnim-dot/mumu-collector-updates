"""Synthetic-only regressions for evidence retention and export budgets."""
import json
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import zipfile
import diagnostics
IDENT='a'*24
SCOPE='b'*24
NOW=datetime(2026,9,28,12,tzinfo=timezone(timedelta(hours=9)))

class DiagnosticRetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.data=Path(self.temp.name)
    def failure(self,scope=SCOPE):
        meta=dict(instance_id=IDENT,account_scope=scope,task='farm',run_id='failed-run',image_sha256=hashlib.sha256(b'failure-image').hexdigest(),created_at=(NOW-timedelta(days=1)).isoformat())
        path=self.data/('first_'+IDENT+'_farm_error.json');path.write_text(json.dumps(meta))
        path.with_suffix('.png').write_bytes(b'failure-image');return path
    def success(self,scope=SCOPE,task='farm',start=None,result='collected'):
        return IDENT,dict(account_scope=scope,run_id='success-run',started_at=(start or NOW-timedelta(hours=1)).isoformat(),finished_at=NOW.isoformat(),task_outcomes=[dict(task=task,result=result)],failure_steps=[])
    def maintain(self,**kwargs):
        callback=getattr(diagnostics,'maintain_evidence',None)
        self.assertTrue(callable(callback),'evidence lifecycle is not installed')
        return callback(self.data,now=NOW,**kwargs)
    def test_later_scoped_success_excludes_failure_and_retains_briefly(self):
        path=self.failure();result=self.maintain(success=self.success())
        self.assertEqual(result['files'][path.name]['status'],'resolved');self.assertTrue(path.exists())
        target=self.data/'out.zip'
        # Export runs maintenance again. Keep it on the same synthetic date;
        # the real calendar must not age this receipt past its five-day TTL.
        maintain=diagnostics.maintain_evidence
        with patch.object(diagnostics,'maintain_evidence',side_effect=lambda data:maintain(data,now=NOW)):
            diagnostics.export_diagnostics(self.data,target)
        with zipfile.ZipFile(target) as archive:
            self.assertNotIn(path.name,archive.namelist());manifest=json.loads(archive.read('diagnostics.json'))
            self.assertTrue(any(e['file']==path.name and e['status']=='resolved' for e in manifest['entries']))
    def test_wrong_account_old_run_wrong_task_and_legacy_never_resolve(self):
        path=self.failure()
        for success in (self.success(scope='c'*24),self.success(task='wood'),self.success(start=NOW-timedelta(days=2)),self.success(result='already_complete')):
            with self.subTest(success=success):self.assertEqual(self.maintain(success=success)['files'][path.name]['status'],'retained')
        path=self.failure(scope=None)
        self.assertEqual(self.maintain(success=self.success())['files'][path.name]['status'],'retained')
    def test_pending_guards_and_malformed_ledgers_block_resolution_without_mutation(self):
        path=self.failure()
        for filename,value in [('action_state.json',{SCOPE:{'farm':{'pending':{'claim':{'id':'pending'}}}}}),('daily_tasks.json',{SCOPE:{'2026-09-28':{'farm':{'_steps':{'claim':{'pending':'claim'}}}}}}),('daily_manual.json',[])]:
            with self.subTest(filename=filename):
                guard=self.data/filename;raw=json.dumps(value);guard.write_text(raw)
                self.assertEqual(self.maintain(success=self.success())['files'][path.name]['status'],'retained')
                self.assertEqual(guard.read_text(),raw);guard.unlink()
    def test_cleanup_after_five_korean_dates_and_new_bytes_survive(self):
        path=self.failure();self.maintain(success=self.success());callback=diagnostics.maintain_evidence
        callback(self.data,now=NOW+timedelta(days=4));self.assertTrue(path.exists())
        callback(self.data,now=NOW+timedelta(days=5));self.assertFalse(path.exists());self.assertFalse(path.with_suffix('.png').exists())
        path=self.failure();self.maintain(success=self.success());path.with_suffix('.png').write_bytes(b'new-unmatched-image')
        callback(self.data,now=NOW+timedelta(days=6));self.assertTrue(path.with_suffix('.png').exists())
    def test_changed_image_cannot_be_reproved_by_persisted_old_success(self):
        path=self.failure();self.maintain(success=self.success())
        (self.data/('last_'+IDENT+'_run.json')).write_text(json.dumps(self.success()[1]))
        path.with_suffix('.png').write_bytes(b'replacement-evidence')
        for days in (5,6):
            diagnostics.maintain_evidence(self.data,now=NOW+timedelta(days=days))
            self.assertTrue(path.exists());self.assertTrue(path.with_suffix('.png').exists())
    def test_guard_pause_does_not_forget_replacement_invalidation(self):
        path=self.failure();self.maintain(success=self.success())
        (self.data/('last_'+IDENT+'_run.json')).write_text(json.dumps(self.success()[1]))
        path.with_suffix('.png').write_bytes(b'replacement-evidence')
        diagnostics.maintain_evidence(self.data,now=NOW+timedelta(days=1))
        guard=self.data/'action_state.json'
        guard.write_text(json.dumps({SCOPE:{'farm':{'pending':{'claim':{}}}}}))
        diagnostics.maintain_evidence(self.data,now=NOW+timedelta(days=2));guard.unlink()
        diagnostics.maintain_evidence(self.data,now=NOW+timedelta(days=6))
        self.assertTrue(path.exists());self.assertTrue(path.with_suffix('.png').exists())
    def test_malformed_success_proofs_cannot_resolve_evidence(self):
        path=self.failure()
        for change in ({'run_id':['not-a-run-id']},
                {'task_outcomes':[{'task':'farm','result':'collected'},{'task':'farm','result':'failed'}]}):
            ident,report=self.success();report.update(change)
            with self.subTest(change=change):
                self.assertEqual(self.maintain(success=(ident,report))['files'][path.name]['status'],'retained')
    def test_corrupt_receipts_do_not_reprove_replaced_evidence(self):
        path=self.failure();self.maintain(success=self.success())
        (self.data/('last_'+IDENT+'_run.json')).write_text(json.dumps(self.success()[1]))
        path.with_suffix('.png').write_bytes(b'replacement-evidence')
        (self.data/'diagnostic_retention.json').write_text('{broken')
        result=diagnostics.maintain_evidence(self.data,now=NOW+timedelta(days=5))
        self.assertTrue(path.exists());self.assertTrue(path.with_suffix('.png').exists())
        self.assertTrue(result['errors'])
    def test_malformed_receipt_record_does_not_reprove_replacement(self):
        path=self.failure();self.maintain(success=self.success())
        (self.data/('last_'+IDENT+'_run.json')).write_text(json.dumps(self.success()[1]))
        path.with_suffix('.png').write_bytes(b'replacement-evidence')
        (self.data/'diagnostic_retention.json').write_text(json.dumps({'schema':1,'receipts':{path.name:[]}}))
        diagnostics.maintain_evidence(self.data,now=NOW+timedelta(days=5))
        self.assertTrue(path.exists());self.assertTrue(path.with_suffix('.png').exists())
    def test_missing_receipt_cannot_reprove_replaced_image(self):
        path=self.failure();self.maintain(success=self.success())
        (self.data/('last_'+IDENT+'_run.json')).write_text(json.dumps(self.success()[1]))
        path.with_suffix('.png').write_bytes(b'replacement-evidence')
        (self.data/'diagnostic_retention.json').unlink()
        diagnostics.maintain_evidence(self.data,now=NOW+timedelta(days=5))
        self.assertTrue(path.exists());self.assertTrue(path.with_suffix('.png').exists())
    def test_unbound_legacy_image_stays_retained(self):
        path=self.failure();meta=json.loads(path.read_text());meta.pop('image_sha256');path.write_text(json.dumps(meta))
        self.assertEqual(self.maintain(success=self.success())['files'][path.name]['status'],'retained')
    def test_new_capture_and_nested_zip_bind_exact_failure_image(self):
        from execution_trace import ExecutionTrace
        from types import SimpleNamespace
        import numpy as np
        trace=ExecutionTrace();trace.account_scope=SCOPE;trace.task='farm';trace.step='claim'
        diagnostics.save_collection_failure(self.data,IDENT,np.zeros((8,8,3),dtype=np.uint8),
            SimpleNamespace(state='unknown',diagnostics={}), 'test',task='farm',trace=trace)
        path=self.data/('last_'+IDENT+'_farm_error.json');meta=json.loads(path.read_text())
        self.assertEqual(meta.get('image_sha256'),hashlib.sha256(path.with_suffix('.png').read_bytes()).hexdigest())
        finished=datetime.now(timezone.utc)+timedelta(seconds=2)
        ident,report=self.success(start=finished-timedelta(seconds=1));report['finished_at']=finished.isoformat()
        result=diagnostics.maintain_evidence(self.data,now=finished,success=(ident,report))
        self.assertEqual(result['files'][path.name]['status'],'resolved')
        self.assertEqual(result['files']['last_'+IDENT+'_farm_claim_evidence.zip']['status'],'resolved')
    def test_invalid_pending_container_is_not_a_clear_guard(self):
        path=self.failure()
        (self.data/'action_state.json').write_text(json.dumps({SCOPE:{'farm':{'pending':[]}}}))
        self.assertEqual(self.maintain(success=self.success())['files'][path.name]['status'],'retained')
    def test_bad_metadata_and_symlinks_are_never_deleted(self):
        path=self.failure();path.write_text('[]');external=self.data/'outside.json';external.write_text('{}')
        link=self.data/('last_'+IDENT+'_farm_error.json')
        try:link.symlink_to(external)
        except OSError:self.skipTest('symlinks unavailable')
        self.maintain(success=self.success());self.assertTrue(path.exists());self.assertTrue(link.is_symlink());self.assertEqual(external.read_text(),'{}')
    def test_export_budget_keeps_current_ledgers_and_reports_omissions_and_duplicates(self):
        for name in ('action_state.json','daily_tasks.json','run_progress.json'):(self.data/name).write_text('{"current":true}')
        raw=os.urandom(7_000_000)
        for task in ('farm','wood','mine','training','ranking','worldboss'):(self.data/('last_'+IDENT+'_'+task+'_error.png')).write_bytes(raw if task=='wood' else os.urandom(7_000_000))
        (self.data/('first_'+IDENT+'_wood_error.png')).write_bytes(raw)
        # Make the duplicate source a current priority item that fits the budget.
        source=self.data/('last_'+IDENT+'_wood_error.png')
        stamp=source.stat().st_mtime+60;os.utime(source,(stamp,stamp))
        target=self.data/'out.zip';diagnostics.export_diagnostics(self.data,target)
        self.assertLessEqual(target.stat().st_size,32*1024*1024)
        with zipfile.ZipFile(target) as archive:
            for name in ('action_state.json','daily_tasks.json','run_progress.json'):self.assertEqual(json.loads(archive.read(name)),{'current':True})
            entries=json.loads(archive.read('diagnostics.json'))['entries']
            self.assertTrue(any(e.get('reason')=='total_budget' for e in entries));self.assertTrue(any(e.get('reason')=='duplicate' for e in entries))
            for entry in entries:
                if entry.get('reason')=='duplicate':self.assertIn(entry['duplicate_of'],archive.namelist())
    def test_maintenance_failure_does_not_break_saved_execution(self):
        from execution_trace import ExecutionTrace
        trace=ExecutionTrace();trace.account_scope=SCOPE;trace.task='farm';trace.event('task_outcome',result='collected')
        self.assertTrue(callable(getattr(diagnostics,'maintain_evidence',None)))
        with patch.object(diagnostics,'maintain_evidence',side_effect=OSError('locked')):diagnostics.save_execution_trace(self.data,IDENT,trace)
        self.assertEqual(json.loads((self.data/('last_'+IDENT+'_run.json')).read_text())['run_id'],trace.run_id)
if __name__=='__main__':unittest.main()
