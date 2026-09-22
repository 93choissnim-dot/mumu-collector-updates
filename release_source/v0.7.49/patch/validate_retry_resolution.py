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

    def test_legacy_started_raid_requires_no_manual_resolution(self):
        from retry_resolution import pending_choices
        with tempfile.TemporaryDirectory() as tmp:
            ledger=ManualQuestLedger(Path(tmp)/'daily_manual.json')
            ledger.mark('vm','daily_guild','raid','started')
            self.assertEqual(pending_choices(tmp,'vm','daily_guild'),[])
            self.assertFalse(ledger.done('vm','daily_guild','raid'))

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
            ledger.checkpoint('vm','daily_guild','dungeon','uncertain',pending='guild_fight')
            ledger.checkpoint('vm','daily_guild','donation','uncertain',pending='donation_paid')
            ledger.mark('other','daily_guild','dungeon','started')
            choice=next(c for c in pending_choices(root,'vm','daily_guild') if c['step']=='dungeon')
            resolve_choice(root,'vm','daily_guild',choice,'completed',confirmed=True)
            saved=ManualQuestLedger(root/'daily_manual.json')
            self.assertTrue(saved.done('vm','daily_guild','dungeon'))
            self.assertEqual(saved.detail('vm','daily_guild','dungeon').get('pending'),None)
            self.assertTrue(saved.detail('vm','daily_guild','donation')['pending'])
            self.assertEqual(saved.detail('vm','daily_guild','raid')['pending'],'raid_fight')
            self.assertEqual(saved.get('other','daily_guild','dungeon'),'started')
    def test_resolution_requires_explicit_attestation_and_current_record(self):
        from retry_resolution import pending_choices,resolve_choice
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ledger=ManualQuestLedger(root/'daily_manual.json')
            ledger.checkpoint('vm','daily_guild','dungeon','uncertain',pending='guild_fight')
            choice=pending_choices(root,'vm','daily_guild')[0]
            with self.assertRaises(ValueError):resolve_choice(root,'vm','daily_guild',choice,'completed',confirmed=False)
            ledger.checkpoint('vm','daily_guild','dungeon','done',pending=None,values={'dungeon':'done'})
            with self.assertRaises(ValueError):resolve_choice(root,'vm','daily_guild',choice,'not_executed',confirmed=True)
            self.assertTrue(ManualQuestLedger(root/'daily_manual.json').done('vm','daily_guild','dungeon'))
    def test_manual_not_executed_rearms_only_chosen_dungeon(self):
        from retry_resolution import pending_choices,resolve_choice
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ledger=ManualQuestLedger(root/'daily_manual.json');ledger.mark('vm','daily_guild','attendance')
            ledger.checkpoint('vm','daily_guild','dungeon','uncertain',pending='guild_fight')
            resolve_choice(root,'vm','daily_guild',pending_choices(root,'vm','daily_guild')[0],'not_executed',confirmed=True)
            saved=ManualQuestLedger(root/'daily_manual.json')
            self.assertIsNone(saved.get('vm','daily_guild','dungeon'));self.assertIsNone(saved.detail('vm','daily_guild','dungeon')['pending'])
            self.assertTrue(saved.done('vm','daily_guild','attendance'))
            self.assertEqual(saved.detail('vm','daily_guild','dungeon')['manual_resolution']['outcome'],'not_executed')
    def test_training_resolution_keeps_audit_and_does_not_claim_resources(self):
        from retry_resolution import pending_choices,resolve_choice
        from action_state import ActionState
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);state=ActionState(root/'action_state.json','vm');state.reserve('training');state.reserve('wood')
            resolve_choice(root,'vm','training',pending_choices(root,'vm','training')[0],'completed',confirmed=True)
            saved=ActionState(root/'action_state.json','vm')
            self.assertFalse(saved.pending('training'));self.assertTrue(saved.pending('wood'))
            self.assertEqual(saved.get('training')['manual_resolution']['outcome'],'completed')
            self.assertEqual(saved.get('training')['input_resolution']['source'],'user_confirmed')
            self.assertEqual(saved.get('training')['last_input']['action'],'claim')

if __name__=='__main__':unittest.main()
