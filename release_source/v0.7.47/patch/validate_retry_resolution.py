"""Explicit recovery of uncertain outcomes; never infer a paid action succeeded."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from daily_state import ManualQuestLedger,DAILY_STEPS
from daily_execution import OutcomeUnknown
import validate_audit

class RetryResolutionTests(unittest.TestCase):
    def test_real_launch_routes_daily_only_retry_with_preserved_ledger(self):
        import validate_fleet
        from history import History
        from contextlib import ExitStack
        fixture=validate_fleet.ManualLaunchTests();app=fixture.app();app.log=Mock()
        with tempfile.TemporaryDirectory() as tmp,ExitStack() as stack:
            root=Path(tmp);app.history=History(root/'history.json');app.history.record('b','daily_guild','deferred')
            old=ManualQuestLedger(root/'daily_manual.json');old.mark('b','daily_guild','attendance')
            stack.enter_context(patch('app.DATA',root))
            lookup=stack.enter_context(patch('fleet_collection.CatalogLookup'));lookup.return_value.read.return_value={'s':{'instance_id':'b','name':'VM'}}
            stack.enter_context(patch('fleet_collection.Adb'));stack.enter_context(patch('fleet_collection.AdbDevice'))
            stack.enter_context(patch('fleet_collection.Vision'))
            stack.enter_context(patch('fleet_collection.save_execution_trace'))
            def cycle(c,rooms,*args,**kw):
                self.assertEqual(rooms,['daily_guild'])
                self.assertEqual(c.manual_retry_tasks,{'daily_guild'})
                self.assertTrue(c.daily_ledger.done('b','daily_guild','attendance'))
                return {'daily_guild':'already_complete'}
            run=stack.enter_context(patch('fleet_collection.cycle_with_recovery',side_effect=cycle))
            app.launch('retry',{'b':['daily_guild']})
            run.assert_called_once()

    def test_started_raid_inspects_detail_but_never_restarts_battle(self):
        fixture=validate_audit.SweepAndWorkshopTests();fixture.setUp();self.addCleanup(fixture.tmp.cleanup)
        c=fixture.c;c.daily_task='daily_guild';c.daily_step='raid';c.daily_mark('raid','started')
        c.daily_guild_page=Mock();c.daily_tap=Mock();c.daily_wait=Mock(side_effect=[Mock(state='daily_raid_map'),Mock(state='daily_raid_detail')])
        with self.assertRaises(OutcomeUnknown):c.daily_guild_raid()
        self.assertEqual(c.daily_wait.call_count,2)
        self.assertNotIn('raid_fight',[a.args[1] for a in c.daily_tap.call_args_list if len(a.args)>1])
        self.assertEqual(c.daily_ledger.get('vm','daily_guild','raid'),'started')

    def test_retry_preserves_completed_steps_and_pending_inputs(self):
        from retry_resolution import retry_ledger
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'daily_manual.json';old=ManualQuestLedger(p)
            old.mark('vm','daily_guild','donation')
            old.checkpoint('vm','daily_guild','raid','uncertain',pending='raid_fight',values={'raid':'started'})
            current=retry_ledger(Path(tmp),'vm',['daily_guild'])
            self.assertTrue(current.done('vm','daily_guild','donation'))
            self.assertEqual(current.get('vm','daily_guild','raid'),'started')
            self.assertEqual(current.detail('vm','daily_guild','raid')['pending'],'raid_fight')
    def test_resolving_one_step_preserves_other_pending_actions_and_accounts(self):
        from retry_resolution import pending_choices,resolve_choice
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ledger=ManualQuestLedger(root/'daily_manual.json')
            ledger.checkpoint('vm','daily_guild','raid','uncertain',pending='raid_fight',values={'raid':'started'})
            ledger.checkpoint('vm','daily_guild','donation','uncertain',pending='donation_paid')
            ledger.mark('other','daily_guild','raid','started')
            choice=next(c for c in pending_choices(root,'vm','daily_guild') if c['step']=='raid')
            resolve_choice(root,'vm','daily_guild',choice,'completed',confirmed=True)
            saved=ManualQuestLedger(root/'daily_manual.json')
            self.assertTrue(saved.done('vm','daily_guild','raid'))
            self.assertEqual(saved.detail('vm','daily_guild','raid').get('pending'),None)
            self.assertTrue(saved.detail('vm','daily_guild','donation')['pending'])
            self.assertEqual(saved.get('other','daily_guild','raid'),'started')
    def test_resolution_requires_explicit_attestation_and_current_record(self):
        from retry_resolution import pending_choices,resolve_choice
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ledger=ManualQuestLedger(root/'daily_manual.json')
            ledger.mark('vm','daily_guild','raid','started')
            choice=pending_choices(root,'vm','daily_guild')[0]
            with self.assertRaises(ValueError):resolve_choice(root,'vm','daily_guild',choice,'completed',confirmed=False)
            ledger.mark('vm','daily_guild','raid','done')
            with self.assertRaises(ValueError):resolve_choice(root,'vm','daily_guild',choice,'not_executed',confirmed=True)
            self.assertTrue(ManualQuestLedger(root/'daily_manual.json').done('vm','daily_guild','raid'))
    def test_manual_not_executed_rearms_only_chosen_raid(self):
        from retry_resolution import pending_choices,resolve_choice
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ledger=ManualQuestLedger(root/'daily_manual.json');ledger.mark('vm','daily_guild','attendance')
            ledger.checkpoint('vm','daily_guild','raid','uncertain',pending='raid_fight',values={'raid':'started'})
            resolve_choice(root,'vm','daily_guild',pending_choices(root,'vm','daily_guild')[0],'not_executed',confirmed=True)
            saved=ManualQuestLedger(root/'daily_manual.json')
            self.assertIsNone(saved.get('vm','daily_guild','raid'));self.assertIsNone(saved.detail('vm','daily_guild','raid')['pending'])
            self.assertTrue(saved.done('vm','daily_guild','attendance'))
            self.assertEqual(saved.detail('vm','daily_guild','raid')['manual_resolution']['outcome'],'not_executed')
    def test_training_resolution_keeps_audit_and_does_not_claim_resources(self):
        from retry_resolution import pending_choices,resolve_choice
        from action_state import ActionState
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);state=ActionState(root/'action_state.json','vm');state.reserve('training');state.reserve('wood')
            resolve_choice(root,'vm','training',pending_choices(root,'vm','training')[0],'completed',confirmed=True)
            saved=ActionState(root/'action_state.json','vm')
            self.assertFalse(saved.pending('training'));self.assertTrue(saved.pending('wood'))
            self.assertEqual(saved.get('training')['manual_resolution']['outcome'],'completed')

if __name__=='__main__':unittest.main()
