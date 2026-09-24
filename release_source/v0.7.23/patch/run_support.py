"""Scheduling and connection recovery, separate from the verified game flow."""
import time
from collector import Halt
from history import TERMINAL_RESULTS,NO_AUTO_RETRY
from run_control import ResumeRecognition, checkpoint


class Schedule:
    RETRY_SECONDS = 120
    MAX_RETRIES = 2

    def __init__(self, selected, interval):
        self.selected = list(selected)
        self.interval = interval
        self.regular_at = 0
        self.pending = {}
        self.attempts = {}

    def next(self):
        due = min([self.regular_at, *self.pending.values()])
        if due == self.regular_at:
            return due, list(self.selected), False
        return due, [r for r, when in self.pending.items() if when == due], True

    def complete(self, rooms, results, retry, now):
        if not retry:
            self.pending.clear()
            self.attempts.clear()
            self.regular_at = now + self.interval
        for room in rooms:
            self.pending.pop(room, None)
            if retry:
                self.attempts[room] = self.attempts.get(room, 0) + 1
            if results.get(room) not in NO_AUTO_RETRY:
                if self.attempts.get(room, 0) < self.MAX_RETRIES:
                    self.pending[room] = now + self.RETRY_SECONDS


def cycle_with_recovery(collector, selected, restore, adb, device, vision, stop, log,
                        on_link=lambda available: None, on_error=lambda exc: None, verify_identity=lambda: None):
    """Recover proven transport loss only, never an online recognition failure."""
    expected = device.package
    results, counts = {}, {}
    collector.resume_counts = {}
    remaining = list(selected)
    recoveries = 0
    while True:
        try:
            result = collector.cycle(remaining, restore)
            results.update(result)
            counts.update(collector.claim_counts)
            collector.results, collector.claim_counts = dict(results), dict(counts)
            collector.resume_counts = {}
            return results
        except ResumeRecognition:
            results.update(collector.results)
            counts.update(collector.claim_counts)
            checkpoint(stop)
            verify_identity()
            if device.current_package() != expected:
                raise Halt('일시중지 중 실행 앱이 바뀌었습니다. 게임 화면을 확인한 뒤 다시 시작하세요.')
            collector.last_image = collector.last_screen = None
            remaining = [r for r in selected if results.get(r) not in TERMINAL_RESULTS]
            collector.resume_counts = {r:counts[r] for r in remaining if r in counts}
            log('재시작: 현재 화면을 다시 확인하고 남은 수령을 이어갑니다.')
        except Halt as exc:
            results.update(collector.results)
            counts.update(collector.claim_counts)
            collector.results, collector.claim_counts = dict(results), dict(counts)
            if stop.is_set():
                raise
            on_error(exc)
            if adb.is_connected(device.serial):
                raise
            on_link(False)
            while True:
                if recoveries >= 2:
                    raise Halt("같은 뮤뮤 주소의 연결 복구에 실패했습니다. 주소와 수령 기록은 유지됩니다.") from exc
                recoveries += 1
                log(f"연결 끊김 확인 → 같은 주소 복구 ({recoveries}/2): {device.serial}")
                if stop.wait(2):
                    raise Halt("사용자가 중지했습니다.")
                try:
                    verify_identity()
                    adb.ensure_connected(device.serial, log)
                    break
                except Halt:
                    if stop.is_set():
                        raise
            # The current app must match the original binding before any input.
            if device.current_package() != expected:
                raise Halt("연결은 복구됐지만 실행 앱이 바뀌어 수령을 멈췄습니다.")
            device.bind_game(vision)
            if device.package != expected:
                raise Halt("연결 복구 후 게임 확인 결과가 달라 수령을 멈췄습니다.")
            collector.last_image = collector.last_screen = None
            remaining = [r for r in selected if results.get(r) not in TERMINAL_RESULTS]
            on_link(True)
            log("연결 복구 확인 / 이미 확인한 시설은 건너뛰고 이어갑니다.")
