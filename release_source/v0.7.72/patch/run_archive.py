"""Compact local run summaries: five Korean calendar days, at most 100 runs per day.

No frames, event streams or ledger copies are retained here. A process-wide
lock serializes the fleet's read/modify/write operations; replacement is atomic.
"""
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading

KST = timezone(timedelta(hours=9))
RETENTION_DAYS = 5
MAX_RUNS_PER_DAY = 100
MAX_DAY_BYTES = 1_000_000
_LOCK = threading.RLock()
_DAY_NAME = re.compile(r'\d{4}-\d{2}-\d{2}\.json')


def _text(value, limit=300):
    return str(value or '')[:limit]


def _seconds(value):
    try:
        number = float(value)
        return round(max(0., number), 3) if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _summary(ident, report):
    tasks = []
    for item in report.get('task_outcomes', [])[:32]:
        if not isinstance(item, dict): continue
        tasks.append({'task': _text(item.get('task'), 64),
                      'result': _text(item.get('result'), 64),
                      'reason': _text(item.get('reason')),
                      'duration_seconds': _seconds(item.get('duration_seconds'))})
    failures = []
    for item in report.get('failure_steps', [])[:32]:
        if not isinstance(item, dict): continue
        failures.append({'task': _text(item.get('task'), 64),
                         'step': _text(item.get('step'), 64),
                         'reason': _text(item.get('reason'))})
    return {'run_id': _text(report.get('run_id'), 64), 'instance_id': ident,
            'started_at': _text(report.get('started_at'), 64),
            'finished_at': _text(report.get('finished_at'), 64),
            'version': _text(report.get('version'), 32),
            'duration_seconds': _seconds(report.get('duration_seconds')),
            'tasks': tasks, 'failure_steps': failures}


def _read(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_DAY_BYTES:
        return []
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict) or not isinstance(value.get('runs'), list): return []
        # Sanitize all loaded records as well; never propagate arbitrary payloads.
        runs = []
        for item in value['runs'][-MAX_RUNS_PER_DAY:]:
            if not isinstance(item, dict) or not re.fullmatch('[0-9a-f]{24}', str(item.get('instance_id', ''))): continue
            if not item.get('run_id') or not isinstance(item.get('tasks'), list) or not isinstance(item.get('failure_steps'), list): continue
            runs.append(_summary(item['instance_id'], dict(item, task_outcomes=item['tasks'])))
        return runs
    except (OSError, ValueError, TypeError):
        return []


def _korean_time(value):
    # Trace timestamps include their offset. Legacy naive values use KST too.
    return value.replace(tzinfo=KST) if value.tzinfo is None else value.astimezone(KST)


def _days(folder, now):
    earliest = now.date() - timedelta(days=RETENTION_DAYS - 1)
    for path in folder.glob('*.json'):
        if not _DAY_NAME.fullmatch(path.name) or path.is_symlink(): continue
        try: day = datetime.strptime(path.stem, '%Y-%m-%d').date()
        except ValueError: continue
        yield path, earliest <= day <= now.date()


def _encode(day, runs):
    return json.dumps({'schema': 1, 'date': day, 'runs': runs}, ensure_ascii=False,
                      separators=(',', ':')).encode('utf-8')


def append_run(data, ident, report, *, now=None):
    """Persist or update a run; callers may treat storage failure as optional."""
    if not re.fullmatch('[0-9a-f]{24}', str(ident)): raise ValueError('Invalid instance identity')
    now = _korean_time(now or datetime.now(KST))
    day = _korean_time(datetime.fromisoformat(report['started_at'])).date()
    folder = Path(data) / 'run_archive'
    with _LOCK:
        if folder.is_symlink(): raise OSError('Run archive must be a local directory')
        folder.mkdir(parents=True, exist_ok=True)
        for old, retained in _days(folder, now):
            if not retained: old.unlink(missing_ok=True)
        if not now.date() - timedelta(days=RETENTION_DAYS - 1) <= day <= now.date(): return
        path = folder / (day.isoformat() + '.json')
        if path.is_symlink(): raise OSError('Run archive must be a local file')
        summary = _summary(ident, report)
        runs = [item for item in _read(path) if
                (item['instance_id'], item['run_id']) != (ident, summary['run_id'])]
        runs = (runs + [summary])[-MAX_RUNS_PER_DAY:]
        raw = _encode(day.isoformat(), runs)
        while len(raw) > MAX_DAY_BYTES and len(runs) > 1:
            runs.pop(0)
            raw = _encode(day.isoformat(), runs)
        temp = None
        try:
            with tempfile.NamedTemporaryFile(dir=folder, suffix='.tmp', delete=False) as stream:
                temp = Path(stream.name)
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            os.replace(temp, path)
        finally:
            if temp is not None: temp.unlink(missing_ok=True)


def diagnostic_summaries(data, *, now=None):
    """Return validated bounded text payloads, never screenshot or unknown files."""
    now = _korean_time(now or datetime.now(KST))
    folder = Path(data) / 'run_archive'
    with _LOCK:
        if folder.is_symlink() or not folder.is_dir(): return []
        payloads = []
        for path, retained in sorted(_days(folder, now)):
            if not retained: continue
            runs = _read(path)
            if runs: payloads.append(('run_archive/' + path.name, _encode(path.stem, runs)))
        return payloads
