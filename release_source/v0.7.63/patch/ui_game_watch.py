"""One device lane shared by collection, inspection and independent recovery."""
import copy
import threading
import tkinter as tk
import customtkinter as ctk
from game_watch import GameWatch
from ui_theme import MUTED,font,label

class GameWatchUI:
    def init_game_watch(self,live=True):
        self.device_lane=threading.RLock();self.watch_thread=None;self.live_watch=live
        self.game_watch=GameWatch(lambda text:self.events.put(('game_watch',text)),package_report=lambda ident,package:self.events.put(('watch_package',(ident,package))))
        self.game_watch.enable(bool(self.config.get('game_watch',True)))
        self._watch_poll=0;self.watch_vision=None
    def build_game_watch(self):
        row=ctk.CTkFrame(self.footer,fg_color='transparent');row.grid(row=4,column=0,columnspan=3,sticky='ew',pady=(8,0));row.grid_columnconfigure(1,weight=1)
        self.watch_value=tk.BooleanVar(value=self.game_watch.enabled)
        self.watch_switch=ctk.CTkSwitch(row,text='게임 자동 복구',variable=self.watch_value,command=self.toggle_game_watch,font=font(12),width=155)
        self.watch_switch.grid(row=0,column=0,sticky='w')
        self.watch_status=label(row,'감시 중' if self.game_watch.enabled else '꺼짐',size=12,color=MUTED,anchor='w',wraplength=390)
        self.watch_status.grid(row=0,column=1,sticky='w',padx=(12,0))
    def toggle_game_watch(self):
        enabled=self.watch_value.get();self.game_watch.enable(enabled);self.config['game_watch']=enabled
        self.save()
        self.log('게임 자동 복구 '+('켜짐 / 작업 중지 후에도 선택한 뮤뮤를 감시합니다.' if enabled else '꺼짐'))
    def remember_game_packages(self,reports):
        from game_recovery import GAME_PACKAGES
        for report in reports.values():
            ident=report.get('instance_id');package=report.get('package')
            if ident in self.players and package in GAME_PACKAGES:self.players[ident]['game_package']=package
    def watch_jobs(self):
        jobs=[]
        for ident,p in self.players.items():
            if not p.get('enabled'):continue
            job=copy.deepcopy(p);job['id']=ident
            reports=[r for r in self.device_reports.values() if r.get('instance_id')==ident]
            for report in reports:
                if report.get('package') in {'com.nns.genesis','com.nns.genesis.onestore'}:job['game_package']=report['package']
            jobs.append(job)
        return jobs
    def watch_prepare(self,executable):
        from adb_device import Adb,AdbDevice
        from game_recovery import GameRecovery,GAME_PACKAGES
        from mumu_names import CatalogLookup
        from collector import Halt
        from vision import Vision
        lookup=CatalogLookup()
        def prepare(job,control):
            ident=job['id'];name=job.get('name',ident)
            def log(text):self.log(name+' / '+text)
            catalog=lookup.read(executable,control,lambda _:None,ident)
            matches=[s for s,p in catalog.items() if p.get('instance_id')==ident]
            if len(matches)!=1:raise Halt('대상 뮤뮤 연결 확인 필요')
            serial=matches[0]
            def verify():
                control.checkpoint()
                current=self.players.get(ident,{})
                if not current.get('enabled') or current.get('daily_profile','')!=job.get('daily_profile',''):raise Halt('감시 대상 설정 변경')
                if self.update_pending.is_set() or self.closing:raise Halt('업데이트 또는 종료 중')
                latest=lookup.read(executable,control,lambda _:None,ident)
                if latest.get(serial,{}).get('instance_id')!=ident:raise Halt('뮤뮤 식별 정보 변경')
            adb=Adb(executable,control);adb.ensure_connected(serial,log)
            device=AdbDevice(adb,serial,log=log)
            if job.get('game_package') in GAME_PACKAGES:device.package=job['game_package']
            if self.watch_vision is None:self.watch_vision=Vision()
            return GameRecovery(device,self.watch_vision,control,verify,log,self.game_watch.status)
        return prepare
    def poll_game_watch(self):
        if not self.live_watch or self.closing or not self.game_watch.enabled:return
        if self.update_pending.is_set() or self.update_applying:
            self.game_watch.interrupt();return
        if self.stop.paused:
            self.game_watch.status('감시 일시중지 / 재시작 후 점검');return
        if self.busy():return
        import time
        now=time.monotonic()
        if now<self._watch_poll or (self.watch_thread and self.watch_thread.is_alive()):return
        self._watch_poll=now+15
        jobs=self.watch_jobs();prepare=self.watch_prepare(self.adb_path.get())
        if not jobs:
            self.game_watch.status('감시 대기 / 선택한 뮤뮤 없음');return
        def work():
            with self.device_lane:
                if self.busy() or self.closing:return
                self.game_watch.scan(jobs,prepare)
        self.watch_thread=threading.Thread(target=work,name='game-watch',daemon=True);self.watch_thread.start()
