"""Per-MuMu profiles and status UI, all widget access on the Tk thread."""
import copy
import os
import time
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
from ui_theme import BG,PANEL,LINE,TEXT,MUTED,GOLD,MINT,RED,font,label,button
from vision import LABELS
from task_catalog import EXTRA_LABELS,TASK_LABELS
from history import RESULTS
from collector import Halt


class FleetUI:
    def init_fleet(self):
        raw=self.config.get('players',{})
        self.players=copy.deepcopy(raw) if isinstance(raw,dict) else {}
        self.players={k:v for k,v in self.players.items() if isinstance(v,dict)}
        for player in self.players.values():player['restore_sleep']=True
        self.config['restore_sleep']=True
        self.fleet_states={};self.fleet_window=None;self.fleet_labels={}
        self.view_id=None;self.tray=None;self.tray_ready=False
        self.active_instance=None

    def capture_profile(self):
        # Settings are edited explicitly; changing the viewed player never saves hidden UI values.
        return

    def select_profile(self,serial):
        ident=self.device_reports.get(serial,{}).get('instance_id')
        if ident==self.view_id:return
        self.capture_profile();self.view_id=ident
        p=self.players.get(ident)
        if p:
            for r,v in self.selected.items():v.set(p.get('selected',{}).get(r,True))
            self.minutes.set(str(p.get('minutes',60)));self.restore.set(True)
            self.update_cards()

    def sync_players(self,reports,chosen):
        self.capture_profile()
        initial=not self.players
        for serial,report in reports.items():
            ident=report.get('instance_id')
            if not ident:continue
            if ident not in self.players:
                self.players[ident]={'enabled':bool(initial and serial==chosen),
                    'selected':dict(self.config.get('selected',{r:True for r in LABELS})),
                    'minutes':self.config.get('minutes',60),'restore_sleep':self.config.get('restore_sleep',True)}
            self.players[ident].update(name=report['window_name'],serial=serial)
        self.update_fleet_summary()

    def update_fleet_summary(self):
        count=sum(bool(p.get('enabled')) for p in self.players.values())
        self.fleet_button.configure(text='세팅 설정')
        self.fleet_summary.set(f'{count}개 뮤뮤 순차 수령 / 시설 선택은 세팅 설정에서 변경')
        self.render_roster(force=True)

    def history_key(self,serial=None):
        serial=serial or self.chosen_serial()
        return self.device_reports.get(serial,{}).get('instance_id') or serial

    def player_history(self,serial,room):
        return self.history.get(self.history_key(serial),room) or self.history.get(serial,room)

    def fleet_dialog(self,ident=None):
        if self.fleet_window is not None and self.fleet_window.winfo_exists():
            if ident is not None:self.settings_editor.select(ident)
            self.fleet_window.lift();return
        from ui_player_settings import PlayerSettings
        self.settings_editor=PlayerSettings(self,ident)

    def render_fleet_status(self):
        self.render_roster()
        if self.fleet_window is not None and self.fleet_window.winfo_exists():
            running=self.busy()
            if getattr(self.settings_editor,'last_running',None)!=running:
                self.settings_editor.set_running(running);self.settings_editor.last_running=running

    @staticmethod
    def task_result(task,result):
        from daily_state import DAILY_TASKS,DAILY_ALREADY
        if task=='autumn' and result=='skipped':return '가을맞이 보상 수령 대기'
        if task in DAILY_TASKS and result in {'collected','skipped'}:
            return '일일 작업 완료' if result=='collected' else RESULTS[DAILY_ALREADY[task]]
        if task=='training':
            if result=='collected':return '수련 완료'
            if result=='skipped':return '수련 조건 미충족'
        return RESULTS.get(result,'기록 없음')

    def setup_tray(self):
        if os.name!='nt':return
        try:
            from tray_support import Tray
            self.tray=Tray(self.events)
        except Exception as exc:self.log('트레이를 시작하지 못해 일반 최소화를 사용합니다: '+str(exc))

    def auto_connect(self):
        if not self.closing and not self.busy():self.connect()
