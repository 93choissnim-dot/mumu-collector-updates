"""Local date-preserved execution summaries; no real user data required."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from diagnostics import export_diagnostics, save_execution_trace
from execution_trace import ExecutionTrace

IDENT = 'a' * 24
NOW = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)


class RunArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)

    def report(self, run_id='run-1', started_at=None):
        return {'run_id': run_id, 'started_at': started_at or NOW.isoformat(),
                'duration_seconds': 14.25, 'version': 'test',
                'task_outcomes': [{'task': 'daily_guild', 'result': 'failed',
                                   'reason': 'unrecognized room', 'duration_seconds': 12.5}],
                'failure_steps': [{'task': 'daily_guild', 'step': 'relic', 'reason': 'unrecognized room'}],
                'events': [{'secret': 'raw-event-must-not-be-archived'}],
                'daily_state': {'secret': 'ledger-must-not-be-archived'}}

    def test_save_preserves_two_runs_and_latest_trace_compatibility(self):
        first = ExecutionTrace(); first.task = 'daily_guild'; first.step = 'relic'
        first.event('task_outcome', result='failed', reason='room unknown')
        save_execution_trace(self.data, IDENT, first, {'ledger': 'latest-only'})
        second = ExecutionTrace(); second.task = 'farm'
        second.event('task_outcome', result='success', reason='collected')
        save_execution_trace(self.data, IDENT, second)
        files = list((self.data / 'run_archive').glob('*.json'))
        self.assertEqual(len(files), 1, 'saving latest trace must also preserve daily summaries')
        day = json.loads(files[0].read_text())
        self.assertEqual([x['run_id'] for x in day['runs']], [first.run_id, second.run_id])
        self.assertEqual(day['runs'][0]['tasks'][0]['reason'], 'room unknown')
        latest = json.loads((self.data / ('last_' + IDENT + '_run.json')).read_text())
        self.assertEqual(latest['run_id'], second.run_id)
        self.assertIn('events', latest)
        self.assertNotIn('events', day['runs'][0])
        self.assertNotIn('daily_state', day['runs'][0])

    def test_outcomes_and_failure_steps_survive_rolling_event_eviction(self):
        trace = ExecutionTrace(); trace.task = 'daily_guild'; trace.step = 'relic'
        trace.event('checkpoint', status='failed', reason='cannot recognize')
        trace.event('task_outcome', result='failed', reason='needs review')
        for _ in range(240): trace.event('screen', actual='menu')
        snapshot = trace.snapshot()
        self.assertEqual(snapshot.get('task_outcomes', [{}])[0].get('result'), 'failed')
        self.assertEqual(snapshot['failure_steps'][0]['step'], 'relic')
        self.assertEqual(snapshot['failure_steps'][0]['reason'], 'cannot recognize')
        self.assertGreaterEqual(snapshot['duration_seconds'], 0)
        self.assertGreaterEqual(snapshot['task_outcomes'][0]['duration_seconds'], 0)
        self.assertEqual(len(snapshot['events']), 200)

    def test_normal_daily_input_reservation_is_not_a_failed_step(self):
        trace = ExecutionTrace(); trace.task = 'daily_guild'; trace.step = 'relic'
        trace.event('checkpoint', status='uncertain', pending='relic_claim')
        trace.event('checkpoint', status='running', pending=None, reason='')
        # daily_mark writes completion to the ledger without a trace event.
        trace.event('task_outcome', result='collected')
        save_execution_trace(self.data, IDENT, trace)
        day = json.loads(next((self.data / 'run_archive').glob('*.json')).read_text())
        self.assertEqual(day['runs'][0]['failure_steps'], [])
        self.assertEqual(day['runs'][0]['tasks'][0]['result'], 'collected')

    def test_actual_uncertainty_survives_later_reservation_and_recovery(self):
        trace = ExecutionTrace(); trace.task = 'daily_guild'; trace.step = 'relic'
        trace.event('checkpoint', status='uncertain', pending='relic_claim',
                    reason='claim result could not be confirmed')
        trace.event('checkpoint', status='uncertain', pending='relic_claim', reason='  ')
        trace.event('checkpoint', status='running', pending=None, reason='')
        trace.event('task_outcome', result='collected')
        save_execution_trace(self.data, IDENT, trace)
        day = json.loads(next((self.data / 'run_archive').glob('*.json')).read_text())
        self.assertEqual(day['runs'][0]['failure_steps'], [{
            'task': 'daily_guild', 'step': 'relic',
            'reason': 'claim result could not be confirmed'}])

    def test_calendar_retention_and_daily_count_keep_newest_runs(self):
        from run_archive import append_run
        old = NOW - timedelta(days=5)
        append_run(self.data, IDENT, self.report('expired', old.isoformat()), now=old)
        edge = NOW - timedelta(days=4)
        append_run(self.data, IDENT, self.report('edge', edge.isoformat()), now=edge)
        for i in range(103): append_run(self.data, IDENT, self.report('run-' + str(i)), now=NOW)
        self.assertFalse((self.data / 'run_archive' / '2026-09-23.json').exists())
        self.assertTrue((self.data / 'run_archive' / '2026-09-24.json').exists())
        runs = json.loads((self.data / 'run_archive' / '2026-09-28.json').read_text())['runs']
        self.assertEqual(len(runs), 100)
        self.assertEqual(runs[0]['run_id'], 'run-3')
        self.assertEqual(runs[-1]['run_id'], 'run-102')

    def test_archive_and_retention_follow_korean_midnight_on_utc_host(self):
        from run_archive import append_run, diagnostic_summaries
        now = datetime(2026, 9, 28, 16, tzinfo=timezone.utc)  # Sep 29, 01:00 KST
        append_run(self.data, IDENT, self.report('today', now.isoformat()), now=now)
        append_run(self.data, IDENT, self.report('edge', '2026-09-24T16:00:00+00:00'), now=now)
        append_run(self.data, IDENT, self.report('expired', '2026-09-24T14:00:00+00:00'), now=now)
        names = sorted(path.name for path in (self.data / 'run_archive').glob('*.json'))
        self.assertEqual(names, ['2026-09-25.json', '2026-09-29.json'])
        self.assertEqual([name for name, _ in diagnostic_summaries(self.data, now=now)],
                         ['run_archive/2026-09-25.json', 'run_archive/2026-09-29.json'])

    def test_repeat_save_upserts_and_threads_do_not_lose_fleet_runs(self):
        from run_archive import append_run
        append_run(self.data, IDENT, self.report(), now=NOW)
        updated = self.report(); updated['task_outcomes'][0]['result'] = 'success'
        append_run(self.data, IDENT, updated, now=NOW)
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda i: append_run(self.data, format(i % 3, '024x'),
                                              self.report('fleet-' + str(i)), now=NOW), range(30)))
        runs = json.loads((self.data / 'run_archive' / '2026-09-28.json').read_text())['runs']
        self.assertEqual(len(runs), 31)
        self.assertEqual(runs[0]['tasks'][0]['result'], 'success')
        self.assertEqual(len({x['run_id'] for x in runs}), 31)

    def test_corrupt_or_wrong_shape_day_is_replaced_by_valid_summary(self):
        from run_archive import append_run
        folder = self.data / 'run_archive'; folder.mkdir()
        path = folder / '2026-09-28.json'
        for broken in ('{broken', '[]', '{"runs": ["bad"]}'):
            path.write_text(broken)
            append_run(self.data, IDENT, self.report(), now=NOW)
            runs = json.loads(path.read_text())['runs']
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]['run_id'], 'run-1')

    def test_atomic_replace_failure_preserves_previous_archive(self):
        from run_archive import append_run
        append_run(self.data, IDENT, self.report(), now=NOW)
        path = self.data / 'run_archive' / '2026-09-28.json'
        previous = path.read_bytes()
        with patch('run_archive.os.replace', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError): append_run(self.data, IDENT, self.report('new'), now=NOW)
        self.assertEqual(path.read_bytes(), previous)
        self.assertEqual(list(path.parent.glob('*.tmp')), [])

    def test_archive_failure_does_not_break_latest_trace(self):
        (self.data / 'run_archive').write_text('blocked archive directory')
        trace = ExecutionTrace()
        save_execution_trace(self.data, IDENT, trace)
        latest = self.data / ('last_' + IDENT + '_run.json')
        self.assertEqual(json.loads(latest.read_text())['run_id'], trace.run_id)

    def test_diagnostic_export_includes_bounded_daily_summaries_only(self):
        trace = ExecutionTrace(); trace.task = 'farm'; trace.event('task_outcome', result='success')
        save_execution_trace(self.data, IDENT, trace)
        folder = self.data / 'run_archive'; folder.mkdir(exist_ok=True)
        (folder / 'secret.png').write_bytes(b'not a summary')
        (folder / '1900-01-01.json').write_text('{"runs":[]}')
        (folder / '2020-01-01.json').write_text('{broken')
        target = self.data / 'diagnostics.zip'; export_diagnostics(self.data, target)
        with zipfile.ZipFile(target) as archive:
            names = [x for x in archive.namelist() if x.startswith('run_archive/')]
            self.assertEqual(len(names), 1)
            summary = json.loads(archive.read(names[0]))
            self.assertEqual(summary['runs'][0]['run_id'], trace.run_id)

    def test_oversized_text_is_compact_and_symlink_directory_is_rejected(self):
        from run_archive import append_run
        report = self.report(); report['task_outcomes'][0]['reason'] = '가' * 1_000_000
        append_run(self.data, IDENT, report, now=NOW)
        path = self.data / 'run_archive' / '2026-09-28.json'
        self.assertLess(path.stat().st_size, 32_000)
        elsewhere = self.data / 'elsewhere'; elsewhere.mkdir()
        other = self.data / 'other'; other.mkdir()
        (other / 'run_archive').symlink_to(elsewhere, target_is_directory=True)
        with self.assertRaises(OSError): append_run(other, IDENT, self.report(), now=NOW)
        self.assertEqual(list(elsewhere.iterdir()), [])


if __name__ == '__main__': unittest.main()
