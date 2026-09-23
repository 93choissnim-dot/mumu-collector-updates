"""Bounded, attributable local request/result evidence."""
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch
import numpy as np
import diagnostics
from vision import Screen


class InputEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.ident='a'*24;self.scope='b'*24
        self.image=np.zeros((540,960,3),np.uint8)
        self.screen=Screen('daily_result',{})
    def save(self,phase='resolved',request='request-1'):
        detail={'last_input':{'id':request,'action':'raid_fight','requested_at':'2026-09-22T12:00:00+09:00','version':'0.7.49'},
                'input_resolution':{'kind':'confirmed','confirmed':True,'source':'game_state'}}
        return diagnostics.save_input_evidence(self.root,self.ident,self.scope,'daily_guild','raid',phase,
            detail,self.image,self.screen,run_id='run-1')
    def test_request_and_result_are_bounded_and_attributed(self):
        self.save('requested');self.save();self.save(request='request-2')
        paths=list(self.root.glob('*.zip'));self.assertEqual(len(paths),2)
        path=next(p for p in paths if '_resolved_' in p.name)
        with zipfile.ZipFile(path) as archive:
            meta=json.loads(archive.read('evidence.json'))
            self.assertEqual(meta['account_scope'],self.scope)
            self.assertEqual(meta['detail']['last_input']['id'],'request-2')
            self.assertTrue(meta['detail']['input_resolution']['confirmed'])
            self.assertEqual(meta['state'],'daily_result')
            self.assertIn('screen.jpg',archive.namelist())
    def test_export_contains_only_valid_bounded_evidence(self):
        path=self.save();(self.root/'last_secret_input_evidence.zip').write_bytes(b'private')
        target=self.root/'diagnostics.zip';diagnostics.export_diagnostics(self.root,target)
        with zipfile.ZipFile(target) as archive:
            self.assertIn(path.name,archive.namelist())
            self.assertNotIn('last_secret_input_evidence.zip',archive.namelist())
    def test_invalid_task_step_phase_and_identity_never_write(self):
        for ident,task,step,phase in [('bad','daily_guild','raid','resolved'),
            (self.ident,'../other','raid','resolved'),(self.ident,'daily_guild','other','resolved'),
            (self.ident,'daily_guild','raid','../x')]:
            with self.subTest(ident=ident,task=task,step=step,phase=phase),self.assertRaises(ValueError):
                diagnostics.save_input_evidence(self.root,ident,self.scope,task,step,phase,{},self.image,self.screen)
        self.assertEqual(list(self.root.iterdir()),[])
    def test_training_request_and_resolution_export_with_same_input_id(self):
        from action_state import ActionState
        from types import SimpleNamespace
        state=ActionState(self.root/'actions.json',self.scope)
        collector=SimpleNamespace(action_state=state,daily_ledger=None,last_image=self.image,
            last_screen=Screen('training',{}),trace=SimpleNamespace(run_id='training-run'))
        binder=getattr(diagnostics,'bind_input_evidence',None)
        self.assertTrue(callable(binder),'training evidence is not wired')
        binder(collector,self.root,self.ident,self.scope,lambda message:None)
        state.reserve('training');request=state.pending('training')['id']
        state.confirm('training')
        output=self.root/'export.zip';diagnostics.export_diagnostics(self.root,output)
        with zipfile.ZipFile(output) as exported:
            for phase in ('requested','resolved'):
                name=f'last_{self.scope}_training_claim_{phase}_input.zip'
                self.assertIn(name,exported.namelist())
                import io
                with zipfile.ZipFile(io.BytesIO(exported.read(name))) as evidence:
                    meta=json.loads(evidence.read('evidence.json'))
                    detail=meta['detail']
                    origin=detail['pending']['claim'] if phase=='requested' else detail['last_input']
                    self.assertEqual(origin['id'],request)
                    self.assertEqual(meta['run_id'],'training-run')
                    self.assertIn('screen.jpg',evidence.namelist())
        self.assertIsNone(state.pending('training'))

    def test_training_rejects_unknown_evidence_step(self):
        with self.assertRaises(ValueError):
            diagnostics.save_input_evidence(self.root,self.ident,self.scope,'training','other',
                'requested',{},self.image,self.screen)

    def test_failed_replace_preserves_previous_evidence(self):
        path=self.save();original=path.read_bytes()
        with patch.object(Path,'replace',side_effect=OSError('disk full')),self.assertRaises(OSError):
            self.save(request='new')
        self.assertEqual(path.read_bytes(),original)
        self.assertFalse(list(self.root.glob('*.tmp')))


if __name__=='__main__':unittest.main()
