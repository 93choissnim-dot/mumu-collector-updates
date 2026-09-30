"""Synthetic regressions for diagnostic publication races and budget priorities."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from datetime import timedelta
import zipfile
import numpy as np
import diagnostics
import validate_v069_diagnostics as baseline
from validate_v069_diagnostics import IDENT, SCOPE, NOW


class DiagnosticPublicationTests(unittest.TestCase):
    def test_new_failure_published_during_expiry_survives_as_complete_pair(self):
        fixture=baseline.DiagnosticRetentionTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        old=fixture.failure();path=old.with_name(old.name.replace('first_', 'last_', 1))
        old.rename(path);old.with_suffix('.png').rename(path.with_suffix('.png'))
        fixture.maintain(success=fixture.success())
        real_unlink=Path.unlink;threads=[];done=threading.Event();errors=[]
        def publish():
            try:
                diagnostics.save_collection_failure(fixture.data,IDENT,np.ones((8,8,3),np.uint8),
                    SimpleNamespace(state='unknown',diagnostics={}), 'new failure',task='farm')
            except Exception as exc:errors.append(exc)
            finally:done.set()
        def unlink(member,*args,**kwargs):
            if member==path and not threads:
                thread=threading.Thread(target=publish);threads.append(thread);thread.start()
                # Schedule a writer in the final-check/unlink window. A shared
                # lock must defer the whole publication until expiry completes.
                done.wait(0.3)
            return real_unlink(member,*args,**kwargs)
        with patch.object(Path,'unlink',unlink):
            diagnostics.maintain_evidence(fixture.data,now=NOW+timedelta(days=5))
        for thread in threads:thread.join(3)
        self.assertTrue(done.is_set());self.assertFalse(errors)
        self.assertTrue(path.exists(),'expiry erased a concurrently published failure')
        meta=json.loads(path.read_text())
        self.assertEqual(meta['reason'],'new failure')
        self.assertEqual(meta['image_sha256'],hashlib.sha256(path.with_suffix('.png').read_bytes()).hexdigest())

    def test_export_reads_one_complete_failure_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp);screen=SimpleNamespace(state='unknown',diagnostics={})
            diagnostics.save_collection_failure(data,IDENT,np.zeros((8,8,3),np.uint8),screen,'old',task='farm')
            picture=data/f'last_{IDENT}_farm_error.png'
            # Make this task metadata precede its image, then schedule a real
            # writer precisely when the exporter starts reading the image.
            os.utime(picture,(1_600_000_000,1_600_000_000))
            real_open=Path.open;threads=[];done=threading.Event()
            def publish():
                try:diagnostics.save_collection_failure(data,IDENT,np.ones((8,8,3),np.uint8),screen,'new',task='farm')
                finally:done.set()
            def opening(path,*args,**kwargs):
                if path==picture and args and args[0]=='rb' and not threads:
                    # Only intercept export reads, not lifecycle hashing.
                    import inspect
                    if any(frame.function=='export_diagnostics' for frame in inspect.stack()) and not any(frame.function=='maintain_evidence' for frame in inspect.stack()):
                        thread=threading.Thread(target=publish);threads.append(thread);thread.start();done.wait(0.3)
                return real_open(path,*args,**kwargs)
            target=data/'out.zip'
            with patch.object(Path,'open',opening):diagnostics.export_diagnostics(data,target)
            for thread in threads:thread.join(3)
            self.assertTrue(done.is_set())
            with zipfile.ZipFile(target) as archive:
                meta=json.loads(archive.read(picture.with_suffix('.json').name))
                entries=json.loads(archive.read('diagnostics.json'))['entries']
                entry=next(e for e in entries if e['file']==picture.name)
                raw=archive.read(entry.get('duplicate_of',picture.name))
                self.assertEqual(meta['image_sha256'],hashlib.sha256(raw).hexdigest())


class DiagnosticPriorityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.data=Path(self.tmp.name)
    def proof(self,step,phase,request=None,size=10_500_000,stamp=1_600_000_000):
        path=self.data/f'last_{SCOPE}_daily_guild_{step}_{phase}_input.zip'
        detail={'pending':'donate','input_request':{'id':request}} if phase=='requested' else {'last_input':{'id':request}}
        metadata={'account_scope':SCOPE,'instance_id':IDENT,'task':'daily_guild','step':step,'phase':phase,'detail':detail}
        with zipfile.ZipFile(path,'w',zipfile.ZIP_STORED) as archive:
            archive.writestr('evidence.json',json.dumps(metadata))
            archive.writestr('screen.jpg',bytes([len(step)+len(phase)])*size)
        os.utime(path,(stamp,stamp));return path
    def export(self):
        target=self.data/'out.zip';diagnostics.export_diagnostics(self.data,target)
        self.assertLessEqual(target.stat().st_size,32*1024*1024)
        with zipfile.ZipFile(target) as archive:
            return set(archive.namelist()),json.loads(archive.read('diagnostics.json')), {name:archive.read(name) for name in ('action_state.json','daily_tasks.json') if name in archive.namelist()}
    def test_latest_failure_precedes_old_input_proofs(self):
        for phase in ('requested','resolved','completed'):self.proof('donation',phase)
        latest=self.data/f'last_{IDENT}_worldboss_error.png';latest.write_bytes(b'newest-error'*100_000)
        latest.with_suffix('.json').write_text(json.dumps({'task':'worldboss'}))
        raw=b'{"untouched": true}\n';(self.data/'action_state.json').write_bytes(raw)
        names,manifest,ledgers=self.export()
        self.assertIn(latest.name,names);self.assertIn(latest.with_suffix('.json').name,names)
        self.assertEqual(ledgers['action_state.json'],raw)
        self.assertTrue(any(e.get('reason')=='total_budget' for e in manifest['entries']))
    def test_exact_current_request_precedes_newer_unrelated_and_same_step_old_proofs(self):
        current=self.proof('raid','requested','current',stamp=1_500_000_000)
        old=self.proof('raid','resolved','old',stamp=1_900_000_000)
        self.proof('donation','requested','unrelated',stamp=1_900_000_001)
        self.proof('donation','completed','unrelated',stamp=1_900_000_002)
        ledger={SCOPE:{'2026-09-28':{'daily_guild':{'_steps':{'raid':{'pending':'fight','input_request':{'id':'current'}}}}}}}
        raw=json.dumps(ledger).encode();(self.data/'daily_tasks.json').write_bytes(raw)
        names,manifest,ledgers=self.export()
        self.assertIn(current.name,names,'current pending request proof lost to old proofs')
        self.assertNotIn(old.name,names,'same step does not establish exact request linkage')
        self.assertEqual(ledgers['daily_tasks.json'],raw)
    def test_unsupported_legacy_input_zip_does_not_abort_export(self):
        path=self.proof('raid','requested','current',size=100)
        # An unsupported compression method is valid ZIP structure but its
        # metadata cannot be inspected. Still preserve the opaque old evidence.
        import struct
        raw=bytearray(path.read_bytes())
        struct.pack_into('<H',raw,8,99)
        central=raw.index(b'PK\x01\x02');struct.pack_into('<H',raw,central+10,99)
        path.write_bytes(raw)
        (self.data/'daily_tasks.json').write_text(json.dumps({SCOPE:{'2026-09-28':{
            'daily_guild':{'_steps':{'raid':{'pending':'fight','input_request':{'id':'current'}}}}}}}))
        try:names,_,_=self.export()
        except Exception as exc:self.fail('opaque legacy evidence aborted export: '+type(exc).__name__)
        self.assertIn(path.name,names)
    def test_training_pending_request_precedes_old_daily_proofs(self):
        for phase in ('requested','resolved','completed'):self.proof('donation',phase)
        current=self.data/f'last_{SCOPE}_training_claim_requested_input.zip'
        with zipfile.ZipFile(current,'w',zipfile.ZIP_STORED) as archive:
            archive.writestr('evidence.json',json.dumps({'account_scope':SCOPE,'task':'training','step':'claim','phase':'requested','detail':{'pending':{'claim':{'id':'training-current'}}}}))
            archive.writestr('screen.jpg',b'training'*150_000)
        os.utime(current,(1_500_000_000,1_500_000_000))
        (self.data/'action_state.json').write_text(json.dumps({SCOPE:{'training':{'pending':{'claim':{'id':'training-current'}}}}}))
        names,_,_=self.export();self.assertIn(current.name,names)

if __name__=='__main__':unittest.main()
