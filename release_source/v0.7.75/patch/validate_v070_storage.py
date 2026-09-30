"""Disk-backed journal durability and interrupted source-update regressions."""
import copy
import errno
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from daily_state import LedgerError
from run_journal import RunJournal
import updater


class JournalStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'run_progress.json'

    def test_stale_instances_merge_accounts_and_task_results(self):
        first, second = RunJournal(self.path), RunJournal(self.path)
        first.begin('a', ['farm', 'wood'])
        stale = RunJournal(self.path)
        first.result('a', 'farm', 'collected')
        stale.result('a', 'wood', 'skipped')
        second.begin('b', ['mine'])
        saved = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(saved['a']['results'], {'farm': 'collected', 'wood': 'skipped'})
        self.assertEqual(saved['b']['tasks'], ['mine'])
        self.assertEqual(first.remaining('a'), [])
        with self.assertRaises(LedgerError):
            first.continue_run('a', ['wood'])

    def test_concurrent_instances_preserve_every_account(self):
        journals = [RunJournal(self.path) for _ in range(10)]
        ready = threading.Barrier(len(journals))
        def begin(pair):
            i, journal = pair
            ready.wait(timeout=5)
            journal.begin(str(i), ['farm'])
        with ThreadPoolExecutor(max_workers=len(journals)) as pool:
            list(pool.map(begin, enumerate(journals)))
        self.assertEqual(set(json.loads(self.path.read_text(encoding='utf-8'))), {str(i) for i in range(10)})

    def test_private_temp_file_leaves_other_writer_file_untouched(self):
        old_tmp = self.path.with_suffix('.tmp')
        old_tmp.write_text('owned by another writer')
        RunJournal(self.path).begin('a', ['farm'])
        self.assertEqual(old_tmp.read_text(encoding='utf-8'), 'owned by another writer')
        self.assertEqual(set(self.path.parent.iterdir()), {old_tmp, self.path})

    def test_windows_sharing_and_lock_violations_retry_before_result_returns(self):
        journal = RunJournal(self.path)
        journal.begin('a', ['farm'])
        original = Path.replace
        for code in (32, 33):
            attempts = []
            def replace(source, target):
                attempts.append(source)
                if len(attempts) < 3:
                    error = PermissionError(errno.EACCES, 'sharing violation')
                    error.winerror = code
                    raise error
                return original(source, target)
            with patch.object(Path, 'replace', replace):
                journal.result('a', 'farm', 'collected')
                self.assertEqual(json.loads(self.path.read_text(encoding='utf-8'))['a']['results']['farm'], 'collected')
            self.assertEqual(len(attempts), 3)
        self.assertEqual(set(self.path.parent.iterdir()), {self.path})

    def test_permanent_replace_failure_keeps_previous_result_and_reports_path_reason(self):
        journal = RunJournal(self.path)
        journal.begin('a', ['farm'])
        before = self.path.read_bytes()
        error = OSError(errno.ENOSPC, 'No space left on device')
        with patch.object(Path, 'replace', side_effect=error) as replace:
            with self.assertRaises(LedgerError) as caught:
                journal.result('a', 'farm', 'collected')
        self.assertEqual(replace.call_count, 1)
        self.assertIn('No space left', str(caught.exception))
        self.assertIn(str(self.path.resolve()), str(caught.exception))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(journal.data, json.loads(before))
        self.assertEqual(set(self.path.parent.iterdir()), {self.path})

    def test_persistent_sharing_violation_has_bounded_retries_and_preserves_file(self):
        journal = RunJournal(self.path)
        journal.begin('a', ['farm'])
        before = self.path.read_bytes()
        error = PermissionError(errno.EACCES, 'sharing violation')
        error.winerror = 32
        with patch.object(Path, 'replace', side_effect=error) as replace:
            with self.assertRaises(LedgerError) as caught:
                journal.result('a', 'farm', 'collected')
        self.assertGreater(replace.call_count, 1)
        self.assertLessEqual(replace.call_count, 5)
        self.assertIn('32', str(caught.exception))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(journal.data, json.loads(before))

    def test_fsync_failure_never_publishes_a_success(self):
        journal = RunJournal(self.path)
        journal.begin('a', ['farm'])
        before = self.path.read_bytes()
        with patch('os.fsync', side_effect=OSError(errno.ENOSPC, 'disk full')):
            with self.assertRaises(LedgerError):
                journal.result('a', 'farm', 'collected')
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(journal.data, json.loads(before))
        self.assertEqual(set(self.path.parent.iterdir()), {self.path})

    def test_deleted_known_journal_is_not_recreated(self):
        journal = RunJournal(self.path)
        journal.begin('a', ['farm'])
        before = copy.deepcopy(journal.data)
        self.path.unlink()
        with self.assertRaises(LedgerError):
            journal.begin('b', ['wood'])
        self.assertEqual(journal.data, before)
        self.assertFalse(self.path.exists())

    def test_fresh_corruption_is_not_overwritten_or_hidden_by_cache(self):
        for broken in ('{', '[]', '{"a": {"day":"x", "tasks":[], "results":[]}}'):
            self.path.unlink(missing_ok=True)
            journal = RunJournal(self.path)
            journal.begin('a', ['farm'])
            self.path.write_text(broken)
            with self.subTest(broken=broken):
                with self.assertRaises(LedgerError):
                    journal.result('a', 'farm', 'collected')
                with self.assertRaises(LedgerError):
                    journal.remaining('a')
                self.assertEqual(self.path.read_text(encoding='utf-8'), broken)

    def test_parent_directory_error_is_ledger_error_with_os_reason(self):
        blocked = self.path.parent / 'blocked'
        journal = RunJournal(blocked / 'run_progress.json')
        blocked.write_text('file')
        with self.assertRaises(LedgerError) as caught:
            journal.begin('a', ['farm'])
        self.assertIsInstance(caught.exception.__cause__, OSError)
        self.assertIn(str(journal.path), str(caught.exception))


class SourceRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.install = self.root / 'install'
        self.install.mkdir()

    def record(self, name, raw):
        work = self.root / 'updates' / name
        work.mkdir(parents=True)
        (work / 'job.json').write_text(raw)
        return work

    def interrupted(self):
        work = self.record('active', '{}')
        (self.install / 'app.py').write_text('new app')
        (work / 'backup').mkdir()
        (work / 'backup' / 'app.py').write_text('old app')
        job = {'install': str(self.install), 'work': str(work), 'status': 'applying',
               'files': {'app.py': 'unused'}, 'existed': ['app.py']}
        (work / 'job.json').write_text(json.dumps(job))
        return work

    def test_invalid_and_historical_records_cannot_block_valid_applying_recovery(self):
        records = [self.record(str(i), raw) for i, raw in enumerate((
            '{', '[]', '{"status":"complete"}',
            json.dumps({'status': 'applying', 'install': str(self.root / 'other')})))]
        active = self.interrupted()
        paths = [work / 'job.json' for work in [*records, active]]
        with patch.object(Path, 'glob', return_value=iter(paths)):
            updater.recover_interrupted(self.root, self.install)
        self.assertEqual((self.install / 'app.py').read_text(encoding='utf-8'), 'old app')
        self.assertEqual(json.loads((active / 'job.json').read_text(encoding='utf-8'))['status'], 'rolled_back')
        self.assertEqual((records[0] / 'job.json').read_text(encoding='utf-8'), '{')
        self.assertFalse(json.loads((self.root / 'update_result.json').read_text(encoding='utf-8'))['ok'])

    def test_only_invalid_history_allows_launch_without_rewriting_records(self):
        for i, raw in enumerate(('{', '[]', '{"status":"complete"}')):
            self.record(str(i), raw)
        updater.recover_interrupted(self.root, self.install)
        self.assertEqual((self.root / 'updates' / '0' / 'job.json').read_text(encoding='utf-8'), '{')

    def test_launcher_cleanup_preserves_malformed_historical_records(self):
        records = []
        for i, raw in enumerate(('{', '[]', '{"status":[]}')):
            records.append((self.record('release-' + str(i), raw), raw))
        updater.recover_interrupted(self.root, self.install)
        updater.cleanup_updates(self.root)
        for work, raw in records:
            self.assertEqual((work / 'job.json').read_text(encoding='utf-8'), raw)

    def test_valid_applying_rollback_failure_still_blocks_launch(self):
        active = self.interrupted()
        (active / 'backup' / 'app.py').unlink()
        with self.assertRaises(OSError):
            updater.recover_interrupted(self.root, self.install)
        self.assertEqual(json.loads((active / 'job.json').read_text(encoding='utf-8'))['status'], 'applying')
        self.assertEqual((self.install / 'app.py').read_text(encoding='utf-8'), 'new app')


if __name__ == '__main__':
    unittest.main()
