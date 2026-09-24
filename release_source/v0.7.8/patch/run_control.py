"""Cooperative pause, cancellation and a clock that freezes while paused."""
from contextlib import contextmanager
import threading
import time


class ResumeRecognition(Exception):
    """A pause invalidated a planned touch; recognize again before continuing."""


class RunControl:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._condition = threading.Condition(threading.RLock())
        self._stopped = False
        self._paused_at = None
        self._paused_seconds = 0.0
        self.generation = 0

    @property
    def paused(self):
        with self._condition:
            return self._paused_at is not None

    def clock(self):
        with self._condition:
            now = self._clock() if self._paused_at is None else self._paused_at
            return now - self._paused_seconds

    def is_set(self):
        with self._condition:
            return self._stopped

    def set(self):
        with self._condition:
            self._stopped = True
            self.resume()
            self._condition.notify_all()

    def clear(self):
        with self._condition:
            self._stopped = False
            self._paused_at = None
            self._paused_seconds = 0.0
            self.generation += 1
            self._condition.notify_all()

    def pause(self):
        with self._condition:
            if self._stopped or self._paused_at is not None:
                return False
            self._paused_at = self._clock()
            self.generation += 1
            self._condition.notify_all()
            return True

    def resume(self):
        with self._condition:
            if self._paused_at is None:
                return False
            self._paused_seconds += self._clock() - self._paused_at
            self._paused_at = None
            self._condition.notify_all()
            return True

    def wait(self, timeout=None):
        with self._condition:
            deadline = None if timeout is None else self.clock() + max(0, timeout)
            while not self._stopped:
                if self._paused_at is not None:
                    self._condition.wait()
                    continue
                remaining = None if deadline is None else deadline - self.clock()
                if remaining is not None and remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True

    def checkpoint(self):
        if self.wait(0):
            from collector import Halt
            raise Halt('사용자가 중지했습니다.')

    @contextmanager
    def input_guard(self, generation=None):
        # Hold only across process creation, never across ADB communication.
        # A command already dispatched can finish; no new input starts paused.
        with self._condition:
            if self._stopped:
                from collector import Halt
                raise Halt('사용자가 중지했습니다.')
            if self._paused_at is not None or (generation is not None and generation != self.generation):
                raise ResumeRecognition()
            yield


def checkpoint(stop):
    if isinstance(stop, RunControl):
        stop.checkpoint()


def active_clock(stop):
    return stop.clock() if isinstance(stop, RunControl) else time.monotonic()
