"""Windows denied replacement and one-time v086 farm uncertainty recovery."""
import errno,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from action_state import ActionState
from daily_state import LedgerError
import validate_audit as fixtures

def denied():
    exc=PermissionError(errno.EACCES,'Access is denied');exc.winerror=5
    return exc

class StorageTests(unittest.TestCase):
    def test_transient_denial_retries_same_durable_payload_before_confirmation(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'actions.json';s=ActionState(path,'vm');s.reserve('farm')
            request=s.pending('farm')['id'];original=Path.replace;calls=[];events=[]
            s.on_input_evidence=lambda *args:events.append(args)
            def replace(source,target):
                calls.append((source,source.read_bytes()))
                if len(calls)<3:
                    self.assertTrue(ActionState(path,'vm').pending('farm'));self.assertEqual(events,[])
                    raise denied()
                return original(source,target)
            with patch.object(Path,'replace',replace):
                try:s.confirm('farm',source='free_reward_confirmed')
                except LedgerError as exc:self.fail('Transient Windows denial aborted confirmation: '+str(exc))
            self.assertEqual(len(calls),3);self.assertEqual(len(set(calls)),1)
            saved=ActionState(path,'vm');self.assertFalse(saved.pending('farm'))
            self.assertEqual(saved.get('farm')['last_input']['id'],request)
            self.assertTrue(saved.get('farm')['input_resolution']['confirmed'])
            self.assertEqual(len(events),1)
    def test_persistent_denial_keeps_old_file_and_blocks_new_input(self):
        for operation in ('reserve','confirm'):
            with self.subTest(operation=operation),tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'actions.json';s=ActionState(path,'vm');s.reserve('farm')
                before=path.read_bytes();events=[];s.on_input_evidence=lambda *a:events.append(a)
                with patch.object(Path,'replace',side_effect=denied()) as replace:
                    with self.assertRaises(LedgerError):
                        if operation=='confirm':s.confirm('farm')
                        else:s.reserve('farm',repeat_authorized=True)
                        events.append('input')
                self.assertEqual(replace.call_count,3);self.assertEqual(events,[])
                self.assertEqual(path.read_bytes(),before);self.assertEqual(s.data,json.loads(before))
                self.assertEqual(list(Path(folder).iterdir()),[path])

class FarmRecoveryTests(unittest.TestCase):
    def flow(self,**kwargs):
        c,d,_=fixtures.FacilityRecoveryTests().collector(**kwargs)
        old={'id':'old-farm','action':'claim','requested_at':'2026-10-09T09:50:21.879+09:00','version':'0.7.86'}
        c.action_state.update('farm',pending={'claim':old})
        return c,d
    def test_active_farm_recovers_once_and_archives_old_result_as_unknown(self):
        c,d=self.flow();self.assertEqual(c.cycle(['farm']),{'farm':'collected'})
        self.assertEqual(d.claims['farm'],1);self.assertFalse(c.action_state.pending('farm'))
        old=next(h for h in c.action_state.get('farm')['input_history'] if h['request']['id']=='old-farm')
        self.assertFalse(old['resolution']['confirmed'])
        self.assertEqual(old['resolution']['source'],'legacy_free_claim_recovery')
    def test_failed_recovery_never_repeats_new_uncertain_request(self):
        c,d=self.flow(post={'farm':'ready'})
        for _ in range(3):self.assertEqual(c.cycle(['farm']),{'farm':'deferred'})
        self.assertEqual(d.claims['farm'],1)
        self.assertNotEqual(c.action_state.pending('farm')['id'],'old-farm')
    def test_empty_farm_reconciles_without_click(self):
        c,d=self.flow(initially_empty=True);c.cycle(['farm'])
        self.assertEqual(d.claims['farm'],0);self.assertFalse(c.action_state.pending('farm'))
    def test_ambiguous_farm_preserves_old_request_without_click(self):
        c,d=self.flow(initial_modes={'farm':'both'});c.cycle(['farm'])
        self.assertEqual(d.claims['farm'],0);self.assertEqual(c.action_state.pending('farm')['id'],'old-farm')
    def test_only_v086_farm_claim_with_valid_provenance_is_eligible(self):
        from legacy_free_recovery import eligible
        from datetime import datetime,timezone
        now=datetime(2026,10,10,tzinfo=timezone.utc)
        request=dict(id='old',action='claim',version='0.7.86',requested_at='2026-10-09T09:50:21+09:00')
        self.assertTrue(eligible('farm','claim',request,now=now))
        for task in ('wood','mine','excavation','training','daily_guild','daily_store'):
            self.assertFalse(eligible(task,'claim',request,now=now))
        for fields in ({'version':'0.7.87'},{'action':'paid'},{'id':''},{'requested_at':'bad'},
                       {'requested_at':'2030-01-01T00:00:00+09:00'}):
            self.assertFalse(eligible('farm','claim',request|fields,now=now))

if __name__=='__main__':unittest.main()
