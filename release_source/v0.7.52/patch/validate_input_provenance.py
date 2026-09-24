"""Stable input origins, honest resolution attribution and atomic persistence."""
import copy
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock,patch

from action_state import ActionState
from daily_state import DailyLedger,ManualQuestLedger,LedgerError,KST


class InputProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'daily.json'

    def test_first_request_survives_rechecks_restart_and_new_manual_run(self):
        ledger=ManualQuestLedger(self.path)
        with patch('daily_state.VERSION','first'),patch('daily_state.korea_now',return_value=datetime(2026,1,1,1,tzinfo=KST)):
            ledger.checkpoint('vm','daily_guild','donation','uncertain',pending='donation_paid')
        request=ledger.detail('vm','daily_guild','donation')['input_request']
        self.assertEqual(request['version'],'first');self.assertIn('+09:00',request['requested_at'])
        self.assertTrue(request['id'])
        ledger=ManualQuestLedger(self.path);ledger.begin_run('vm')
        with patch('daily_state.VERSION','later'):
            ledger.checkpoint('vm','daily_guild','donation','running',pending='donation_paid')
        detail=ledger.detail('vm','daily_guild','donation')
        self.assertEqual(detail['input_request'],request)
        self.assertNotEqual(detail['updated_at'],request['requested_at'])

    def test_actual_legacy_migration_never_invents_origin(self):
        legacy=Path(self.tmp.name)/'legacy.json'
        legacy.write_text(json.dumps({'vm':{'2025-01-01':{'daily_guild':{'_steps':{
            'donation':{'pending':'donation_paid','updated_at':'old-observation','status':'uncertain'}}}}}}))
        ledger=ManualQuestLedger(self.path);ledger.begin_run('vm',legacy)
        ledger.checkpoint('vm','daily_guild','donation','uncertain',pending='donation_paid')
        self.assertNotIn('input_request',ledger.detail('vm','daily_guild','donation'))
        ledger.checkpoint('vm','daily_guild','donation','done',pending=None)
        detail=ledger.detail('vm','daily_guild','donation')
        self.assertEqual(detail['last_input'],{'action':'donation_paid','origin':'legacy_unknown'})
        self.assertTrue(detail['input_resolution']['confirmed'])

    def test_resolution_preserves_origin_and_only_new_dispatch_gets_new_id(self):
        ledger=ManualQuestLedger(self.path)
        ledger.checkpoint('vm','daily_guild','donation','uncertain',pending='donation_paid')
        request=ledger.detail('vm','daily_guild','donation')['input_request']
        ledger.checkpoint('vm','daily_guild','donation','running',pending=None)
        detail=ledger.detail('vm','daily_guild','donation')
        self.assertEqual(detail['last_input'],request);self.assertNotIn('input_request',detail)
        self.assertEqual(detail['input_resolution']['kind'],'confirmed')
        ledger.begin_run('vm')
        self.assertEqual(ledger.detail('vm','daily_guild','donation')['last_input'],request)
        ledger.checkpoint('vm','daily_guild','donation','uncertain',pending='donation_paid')
        self.assertNotEqual(ledger.detail('vm','daily_guild','donation')['input_request']['id'],request['id'])

    def test_manual_and_authorized_repeat_are_distinct_from_screen_confirmation(self):
        ledger=DailyLedger(self.path)
        cases=[({'manual_resolution':{'outcome':'not_executed','source':'user_confirmed'}},'manual_resolution',False),
               ({'manual_resolution':{'outcome':'completed','source':'user_confirmed'}},'manual_resolution',True),
               ({'retry_authorized':True,'resolution_source':'repeat_allowed_raid'},'retry_authorized',False)]
        for fields,kind,confirmed in cases:
            ledger.checkpoint('vm','daily_guild','raid','uncertain',pending='raid_fight')
            ledger.checkpoint('vm','daily_guild','raid','done',pending=None,**fields)
            result=ledger.detail('vm','daily_guild','raid')['input_resolution']
            self.assertEqual(result['kind'],kind);self.assertEqual(result['confirmed'],confirmed)
        ledger.checkpoint('vm','daily_guild','raid','uncertain',pending='raid_fight')
        ledger.checkpoint('vm','daily_guild','raid','done',pending=None)
        self.assertEqual(ledger.detail('vm','daily_guild','raid')['input_resolution']['kind'],'confirmed')

    def test_daily_failed_write_retains_pending_and_emits_no_evidence(self):
        ledger=DailyLedger(self.path);callback=Mock();ledger.on_input_evidence=callback
        ledger.checkpoint('vm','daily_guild','raid','uncertain',pending='raid_fight')
        before=copy.deepcopy(ledger.data);disk=self.path.read_bytes();callback.reset_mock()
        with patch.object(Path,'replace',side_effect=OSError('full')):
            with self.assertRaises(LedgerError):ledger.checkpoint('vm','daily_guild','raid','done',pending=None)
        self.assertEqual(ledger.data,before);self.assertEqual(self.path.read_bytes(),disk)
        callback.assert_not_called()

    def test_failed_first_reservation_has_no_origin_or_callback(self):
        ledger=DailyLedger(self.path);ledger.on_input_evidence=Mock()
        state=ActionState(Path(self.tmp.name)/'actions.json','vm');state.on_input_evidence=Mock()
        with patch.object(Path,'replace',side_effect=OSError('full')):
            with self.assertRaises(LedgerError):ledger.checkpoint('vm','daily_guild','raid','uncertain',pending='raid_fight')
            with self.assertRaises(LedgerError):state.reserve('training')
        self.assertEqual(ledger.data,{});self.assertEqual(state.data,{})
        ledger.on_input_evidence.assert_not_called();state.on_input_evidence.assert_not_called()

    def test_new_manual_run_keeps_archive_without_reusing_verified_donation_counts(self):
        ledger=ManualQuestLedger(self.path)
        ledger.checkpoint('vm','daily_guild','donation','uncertain',pending='donation_paid',
                          values={'donation_paid':2,'donation_verified':1})
        ledger.checkpoint('vm','daily_guild','donation','done',pending=None,
                          values={'donation_verified':2,'donation':'done'})
        ledger.begin_run('vm')
        self.assertNotIn('donation_paid',ledger.snapshot('vm')['daily_guild'])
        self.assertNotIn('donation_verified',ledger.snapshot('vm')['daily_guild'])
        self.assertFalse(ledger.done('vm','daily_guild','donation'))
        self.assertTrue(ledger.detail('vm','daily_guild','donation')['input_resolution']['confirmed'])

    def test_callbacks_fire_only_for_persisted_input_transitions_and_are_isolated(self):
        ledger=DailyLedger(self.path);events=[]
        def callback(phase,task,step,detail):
            self.assertEqual(DailyLedger(self.path).detail('vm',task,step),detail)
            events.append((phase,detail));detail['callback_only']=True
        ledger.on_input_evidence=callback
        ledger.checkpoint('vm','daily_guild','raid','uncertain',pending='raid_fight')
        ledger.checkpoint('vm','daily_guild','raid','uncertain',reason='recheck')
        ledger.checkpoint('vm','daily_guild','raid','done',pending=None)
        self.assertEqual([e[0] for e in events],['requested','resolved'])
        self.assertNotIn('callback_only',ledger.detail('vm','daily_guild','raid'))

    def test_daily_history_is_bounded(self):
        ledger=DailyLedger(self.path)
        for _ in range(14):
            ledger.checkpoint('vm','daily_guild','donation','uncertain',pending='donation_paid')
            ledger.checkpoint('vm','daily_guild','donation','running',pending=None)
        detail=ledger.detail('vm','daily_guild','donation')
        self.assertEqual(len(detail['input_history']),8)
        self.assertEqual(detail['input_history'][-1]['request'],detail['last_input'])

    def test_action_reserve_preserves_first_and_confirm_attributes_each_slot(self):
        state=ActionState(self.path,'vm');state.reserve('worldboss','kraken')
        request=state.pending('worldboss','kraken');self.assertIn('requested_at',request)
        state=ActionState(self.path,'vm')
        with patch('action_state.VERSION','later'):state.reserve('worldboss','kraken')
        self.assertEqual(state.pending('worldboss','kraken'),request)
        state.reserve('worldboss','void');state.confirm('worldboss','kraken')
        self.assertEqual(state.get('worldboss')['last_input'],request)
        self.assertTrue(state.pending('worldboss','void'))
        self.assertTrue(state.get('worldboss')['input_resolution']['confirmed'])

    def test_action_legacy_and_manual_resolution_are_honest_and_bounded(self):
        self.path.write_text(json.dumps({'vm':{'training':{'pending':{'claim':{'action':'claim','version':'old'}}}}}))
        state=ActionState(self.path,'vm');state.reserve('training')
        self.assertEqual(state.pending('training'),{'action':'claim','version':'old'})
        state.confirm('training',status='not_executed',source='user_confirmed',
                      manual_resolution={'outcome':'not_executed'})
        self.assertFalse(state.get('training')['input_resolution']['confirmed'])
        self.assertNotIn('requested_at',state.get('training')['last_input'])
        for _ in range(14):state.reserve('training');state.confirm('training')
        self.assertEqual(len(state.get('training')['input_history']),8)

    def test_action_failed_confirm_is_atomic(self):
        state=ActionState(self.path,'vm');state.reserve('training');before=copy.deepcopy(state.data)
        with patch.object(Path,'replace',side_effect=OSError('full')):
            with self.assertRaises(LedgerError):state.confirm('training')
        self.assertEqual(state.data,before)
        self.assertEqual(ActionState(self.path,'vm').data,before)

    def assert_retry_attribution(self,state,task,old,slot='claim'):
        records=state.get(task)['input_history']
        self.assertEqual(len(records),2)
        self.assertEqual(records[0]['request'],old)
        self.assertEqual(records[0]['resolution']['kind'],'retry_authorized')
        self.assertEqual(records[0]['resolution']['source'],'manual_free_claim_retry')
        self.assertFalse(records[0]['resolution']['confirmed'])
        self.assertNotEqual(records[1]['request']['id'],old['id'])
        self.assertEqual(records[1]['request']['action'],slot)
        self.assertNotEqual(records[1]['request']['version'],old['version'])
        self.assertTrue(records[1]['resolution']['confirmed'])

    def test_actual_free_extra_retry_confirms_new_dispatch_not_old_pending(self):
        from validate_reward_recovery import RewardRecoveryTests
        for task,slot in (('ranking','claim'),('excavation','claim'),('worldboss','kraken')):
            with self.subTest(task=task):
                d,c=RewardRecoveryTests().extra(task);c.manual_retry_tasks={task}
                if task=='worldboss':c.boss_slot=slot
                with patch('action_state.VERSION','prior-version'):c.action_state.reserve(task,slot)
                old=c.action_state.pending(task,slot)
                self.assertEqual(c.claim_extra(task,d.screen()),'collected');self.assertEqual(d.claims,1)
                self.assert_retry_attribution(c.action_state,task,old,slot)

    def test_actual_autumn_and_facility_retries_keep_distinct_origins(self):
        import validate_autumn,validate_audit
        d,c=validate_autumn.RouteTests().collector();c.manual_retry_tasks={'autumn'}
        with patch('action_state.VERSION','prior-version'):c.action_state.reserve('autumn')
        old=c.action_state.pending('autumn')
        self.assertEqual(c.cycle(['autumn']),{'autumn':'collected'});self.assertEqual(d.claims,1)
        self.assert_retry_attribution(c.action_state,'autumn',old)
        for task in ('farm','wood','mine'):
            with self.subTest(task=task):
                c,d,_=validate_audit.FacilityRecoveryTests().collector();c.manual_retry_rooms={task}
                with patch('action_state.VERSION','prior-version'):c.action_state.reserve(task)
                old=c.action_state.pending(task)
                self.assertEqual(c.cycle([task]),{task:'collected'});self.assertEqual(d.claims[task],1)
                self.assert_retry_attribution(c.action_state,task,old)

    def test_authorized_retry_write_failure_retains_original_and_no_callback(self):
        state=ActionState(self.path,'vm');state.reserve('ranking');state.on_input_evidence=Mock()
        before=copy.deepcopy(state.data)
        with patch.object(Path,'replace',side_effect=OSError('full')):
            with self.assertRaises(LedgerError):state.reserve('ranking',repeat_authorized=True)
        self.assertEqual(state.data,before);self.assertEqual(ActionState(self.path,'vm').data,before)
        state.on_input_evidence.assert_not_called()


if __name__=='__main__':unittest.main()
