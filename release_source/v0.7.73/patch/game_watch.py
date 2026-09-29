"""Independent, bounded recovery checks; never collect or alter schedules."""
from contextlib import contextmanager
import threading
import time
from collector import Halt
from run_control import RunControl

class WatchControl(RunControl):
    def __init__(self,parent=None):
        super().__init__();self.parent=parent
        self.parent_generation=getattr(parent,'generation',None)
    def clock(self):
        return self.parent.clock() if self.parent is not None else super().clock()
    def checkpoint(self):
        if self.parent is not None:
            while self.parent.paused and not self.parent.is_set():
                if self.wait(.1):raise Halt('복구 점검을 취소했습니다.')
            if self.parent.is_set():raise Halt('작업이 중지되어 복구 점검을 취소했습니다.')
            if self.parent.generation!=self.parent_generation:
                with self._condition:
                    self.parent_generation=self.parent.generation;self.generation+=1
        super().checkpoint()
    @contextmanager
    def input_guard(self,generation=None):
        if self.parent is None:
            with super().input_guard(generation):yield
        else:
            with self.parent.input_guard(self.parent_generation):
                with super().input_guard(generation):yield

class GameWatch:
    def __init__(self,report,clock=time.monotonic,package_report=None):
        self.report=report;self.clock=clock;self.enabled=False;self.control=None
        self.lock=threading.RLock();self.scan_lock=threading.Lock()
        self.next_check={};self.launches={};self.last_status=None
        self.failures={};self.last_checked={};self.startups={};self.packages={};self.package_report=package_report or (lambda ident,package:None)
    def status(self,text):
        if text!=self.last_status:self.last_status=text;self.report(text)
    def enable(self,value):
        with self.lock:
            self.enabled=bool(value)
            if self.control:self.control.set()
            if value:self.next_check.clear()
            self.status('감시 중 / 선택한 뮤뮤' if value else '꺼짐')
    def interrupt(self):
        with self.lock:
            if self.control:self.control.set()
    def scan(self,jobs,prepare,parent=None):
        if not self.scan_lock.acquire(False):return
        try:
            selected={job['id'] for job in jobs if job.get('enabled')}
            self.failures={k:v for k,v in self.failures.items() if k in selected}
            for job in jobs:
                with self.lock:
                    if not self.enabled:return
                    if parent is not None and (parent.is_set() or parent.paused):return
                    ident=job['id'];now=self.clock()
                    if not job.get('enabled') or now<self.next_check.get(ident,0):continue
                    control=WatchControl(parent);self.control=control
                    self.next_check[ident]=now+15
                try:
                    recovered=self.perform(ident,lambda active:prepare(job,active),parent,control)
                    with self.lock:
                        if not self.enabled or control.is_set():return
                        self.failures.pop(ident,None);self.last_checked[ident]=self.clock()
                        if not self.failures:
                            self.status(job.get('name',ident)+(' / 재접속 완료, 수령 예약 유지' if recovered else ' / 감시 점검 완료 '+time.strftime('%H:%M:%S')))
                except Exception as exc:
                    if not control.is_set() and not (parent is not None and (parent.is_set() or parent.paused)):
                        self.failures[ident]=job.get('name',ident)+' / 복구 보류: '+str(exc)
                        self.next_check[ident]=self.clock()+60
            with self.lock:
                if self.enabled:
                    if self.failures:self.status(next(iter(self.failures.values())))
                    elif not selected:self.status('감시 대기 / 선택한 뮤뮤 없음')
        finally:self.scan_lock.release()

    def perform(self,ident,prepare,parent=None,control=None):
        with self.lock:
            if not self.enabled:return False
            control=control or WatchControl(parent);self.control=control
        recovery=None;before=0
        try:
            control.checkpoint();recovery=prepare(control)
            recovery.startup=self.startups.setdefault(ident,{})
            if self.packages.get(ident):recovery.device.package=self.packages[ident]
            now=self.clock();history=[t for t in self.launches.get(ident,[]) if now-t<600]
            self.launches[ident]=history;before=len(history);recovery.attempts=before
            control.checkpoint();return recovery.recover()
        finally:
            if recovery is not None:
                self.launches.setdefault(ident,[]).extend([self.clock()]*max(0,recovery.attempts-before))
                package=getattr(recovery,'observed_package',None)
                if package and package!=self.packages.get(ident):
                    self.packages[ident]=package;self.package_report(ident,package)
            with self.lock:
                if self.control is control:self.control=None

class WatchedRecovery:
    def __init__(self,watch,ident,prepare,parent):
        self.watch=watch;self.ident=ident;self.prepare=prepare;self.parent=parent
    def recover(self):return self.watch.perform(self.ident,self.prepare,self.parent)
