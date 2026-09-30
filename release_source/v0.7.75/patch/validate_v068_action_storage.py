"""Disk-backed regressions for concurrent ActionState readers/writers and failed saves."""
import errno
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from action_state import ActionState
from daily_state import LedgerError


class ActionStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'action_state.json'

    def test_stale_instances_preserve_other_accounts_and_pending_slots(self):
        first = ActionState(self.path, 'first')
        second = ActionState(self.path, 'second')
        stale_first = ActionState(self.path, 'first')
        first.reserve('worldboss', 'kraken')
        original = first.pending('worldboss', 'kraken')
        second.reserve('excavation')
        stale_first.reserve('worldboss', 'void')
        disk = json.loads(self.path.read_text())
        self.assertEqual(disk['first']['worldboss']['pending']['kraken'], original)
        self.assertIn('void', disk['first']['worldboss']['pending'])
        self.assertIn('claim', disk['second']['excavation']['pending'])
        stale_first.reserve('worldboss', 'kraken')
        self.assertEqual(stale_first.pending('worldboss', 'kraken'), original)

    def test_concurrent_instances_keep_every_reservation(self):
        states = [ActionState(self.path, str(i)) for i in range(12)]
        ready = threading.Barrier(len(states))
        def reserve(state):
            ready.wait(timeout=5)
            state.reserve('excavation')
        with ThreadPoolExecutor(max_workers=len(states)) as pool:
            list(pool.map(reserve, states))
        disk = json.loads(self.path.read_text())
        self.assertEqual(set(disk), {str(i) for i in range(12)})
        self.assertTrue(all('claim' in entry['excavation']['pending'] for entry in disk.values()))

    def test_stale_confirmation_keeps_other_unresolved_slot(self):
        first = ActionState(self.path, 'first')
        first.reserve('worldboss', 'kraken')
        stale = ActionState(self.path, 'first')
        first.reserve('worldboss', 'void')
        stale.confirm('worldboss', 'kraken')
        saved = ActionState(self.path, 'first')
        self.assertIsNone(saved.pending('worldboss', 'kraken'))
        self.assertIsNotNone(saved.pending('worldboss', 'void'))
        self.assertEqual(saved.get('worldboss')['last_input']['action'], 'kraken')

    def test_save_does_not_reuse_or_delete_another_temporary_file(self):
        old_tmp = self.path.with_suffix('.tmp')
        old_tmp.write_text('another writer owns this')
        ActionState(self.path, 'first').reserve('excavation')
        self.assertEqual(old_tmp.read_text(), 'another writer owns this')
        self.assertEqual(set(Path(self.temp.name).iterdir()), {self.path, old_tmp})

    def test_transient_windows_sharing_failure_recovers_before_dispatch(self):
        state = ActionState(self.path, 'first')
        real_replace = Path.replace
        for winerror in (32, 33):
            with self.subTest(winerror=winerror):
                attempts = []
                def replace(source, target):
                    attempts.append(source)
                    if len(attempts) <= 2:
                        exc = PermissionError(errno.EACCES, 'sharing/lock violation')
                        exc.winerror = winerror
                        raise exc
                    return real_replace(source, target)
                with patch.object(Path, 'replace', replace):
                    state.reserve('task_' + str(winerror))
                    # The real action can proceed only after reserve returns durably.
                    saved = json.loads(self.path.read_text())
                    self.assertIn('claim', saved['first']['task_' + str(winerror)]['pending'])
                self.assertEqual(len(attempts), 3)
        self.assertEqual(set(Path(self.temp.name).iterdir()), {self.path})

    def test_permanent_failure_preserves_file_memory_and_blocks_dispatch_with_os_reason(self):
        state = ActionState(self.path, 'first')
        state.reserve('worldboss', 'kraken')
        before = self.path.read_bytes()
        events = []
        state.on_input_evidence = lambda *args: events.append(args)
        error = OSError(errno.ENOSPC, 'No space left on device')
        with patch.object(Path, 'replace', side_effect=error) as replace:
            with self.assertRaises(LedgerError) as caught:
                state.reserve('excavation')
                events.append('dispatched')
        self.assertIn('No space left', str(caught.exception))
        self.assertEqual(replace.call_count, 1)
        self.assertEqual(events, [])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(state.data, json.loads(before))
        self.assertEqual(set(Path(self.temp.name).iterdir()), {self.path})

    def test_persistent_sharing_failure_is_bounded_and_keeps_pending_claim(self):
        state = ActionState(self.path, 'first')
        state.reserve('excavation')
        before = self.path.read_bytes()
        error = PermissionError(errno.EACCES, 'sharing violation')
        error.winerror = 32
        with patch.object(Path, 'replace', side_effect=error) as replace:
            with self.assertRaises(LedgerError) as caught:
                state.confirm('excavation')
        self.assertGreater(replace.call_count, 1)
        self.assertLessEqual(replace.call_count, 5)
        self.assertIn('32', str(caught.exception))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(state.data, json.loads(before))
        self.assertEqual(set(Path(self.temp.name).iterdir()), {self.path})

    def test_deleted_ledger_does_not_forget_known_pending_claims(self):
        state = ActionState(self.path, 'first')
        state.reserve('excavation')
        before = state.data.copy()
        self.path.unlink()
        with self.assertRaises(LedgerError):
            state.reserve('ranking')
        self.assertEqual(state.data, before)
        self.assertFalse(self.path.exists())

    def test_flush_failure_never_authorizes_input_or_changes_old_file(self):
        state = ActionState(self.path, 'first')
        state.reserve('excavation')
        before = self.path.read_bytes()
        events = []
        state.on_input_evidence = lambda *args: events.append(args)
        with patch('action_state.os.fsync', side_effect=OSError(errno.ENOSPC, 'disk full')):
            with self.assertRaises(LedgerError):
                state.reserve('ranking')
                events.append('dispatched')
        self.assertEqual(events, [])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(state.data, json.loads(before))
        self.assertEqual(set(Path(self.temp.name).iterdir()), {self.path})

    def test_fresh_invalid_disk_state_is_never_overwritten_by_stale_instance(self):
        state = ActionState(self.path, 'first')
        self.path.write_text('{broken')
        with self.assertRaises(LedgerError):
            state.reserve('excavation')
        self.assertEqual(self.path.read_text(), '{broken')


if __name__ == '__main__':
    unittest.main()
