"""Atomic per-device collection history. Never infer success from a tap alone."""
import json
import threading
from datetime import datetime
from pathlib import Path

RESULTS = {"collected": "수령 완료", "skipped": "수령할 자원 없음", "unavailable": "이벤트 없음",
           "attempted": "수령 시도 · 완료 미확인", "unrecognized": "버튼 미인식 · 확인 필요",
           "failed": "진행 중단 · 확인 필요", "deferred": "자동 재시도 보류 · 확인 필요",
           "already_complete": "이미 완료", "already_claimed": "이미 수령", "no_entries": "입장 횟수 없음"}
TERMINAL_RESULTS=frozenset(("collected","skipped","already_complete","already_claimed","no_entries","unavailable"))
ISSUES={'failed','attempted','unrecognized','deferred'}
NO_AUTO_RETRY=TERMINAL_RESULTS|{'deferred'}


class History:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(self.data, dict):
                self.data = {}
        except (OSError, ValueError):
            self.data = {}

    def record(self, serial, room, result, now=None, reason=None, run_id=None):
        if result not in RESULTS:raise ValueError('Unknown collection result')
        stamp = now or datetime.now().astimezone().isoformat(timespec="milliseconds")
        day=datetime.fromisoformat(stamp).astimezone().date().isoformat()
        with self.lock:
            if not isinstance(self.data.get(serial, {}), dict):self.data[serial] = {}
            rooms = self.data.setdefault(serial, {})
            previous = rooms.get(room, {})
            if not isinstance(previous, dict):previous = {}
            daily=previous.get('daily',{})
            daily={key:value for key,value in daily.items() if isinstance(key,str) and type(value) is int and value>=0} if isinstance(daily,dict) else {}
            if result=='collected':daily[day]=daily.get(day,0)+1
            daily={key:daily[key] for key in sorted(daily)[-30:]}
            failures=previous.get('consecutive_failures',0)
            failures=failures if type(failures) is int and failures>=0 else 0
            rooms[room] = {"checked_at": stamp, "result": result, "run_id":run_id,
                           "collected_at": stamp if result == "collected" else previous.get("collected_at"),
                           'daily':daily,'consecutive_failures':failures+1 if result in ISSUES else 0,
                           'reason':str(reason or RESULTS[result])[:2000] if result in ISSUES else ''}
            self._save()

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def issue(self,serial,room,reason):
        with self.lock:
            entry=self.data.get(serial,{}).get(room,{})
            if isinstance(entry,dict) and entry.get('result') in ISSUES:
                entry['reason']=str(reason)[:2000];self._save()

    def get(self, serial, room):
        with self.lock:
            value = self.data.get(serial, {})
            entry = value.get(room, {}) if isinstance(value, dict) else {}
            return dict(entry) if isinstance(entry, dict) else {}

    def stats(self,serial,day=None,alternate=None):
        from task_catalog import TASK_LABELS
        day=day or datetime.now().astimezone().date().isoformat()
        entries=[self.get(serial,task) or self.get(alternate,task) for task in TASK_LABELS]
        total=0;stamps=[]
        for entry in entries:
            daily=entry.get('daily',{})
            value=daily.get(day,0) if isinstance(daily,dict) else 0
            if type(value) is int and value>0:total+=value
            try:stamps.append(datetime.fromisoformat(entry['collected_at']).astimezone())
            except (KeyError,ValueError,TypeError):pass
        return {'today':total,'last_success':max(stamps).isoformat() if stamps else None,
                'failed_tasks':sum(entry.get('result') in ISSUES for entry in entries)}


def last_success(entry):
    try:
        when = datetime.fromisoformat(entry["collected_at"])
        return "최근 수령  " + when.strftime("%m/%d %H:%M")
    except (KeyError, ValueError, TypeError):
        return "최근 수령  기록 없음"
