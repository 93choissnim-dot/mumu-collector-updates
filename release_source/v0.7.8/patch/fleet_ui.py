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
        self.fleet_states={};self.fleet_window=None;self.fleet_labels={}
        self.view_id=None;self.tray=None;self.tray_ready=False
        self.active_instance=None

    def capture_profile(self):
        if self.view_id in self.players and not self.busy():
            self.players[self.view_id].update(selected={**self.players[self.view_id].get("selected",{}),**{r:v.get() for r,v in self.selected.items()}},
                minutes=self.minutes.get(),restore_sleep=self.restore.get())

    def select_profile(self,serial):
        ident=self.device_reports.get(serial,{}).get('instance_id')
        if ident==self.view_id:return
        self.capture_profile();self.view_id=ident
        p=self.players.get(ident)
        if p:
            for r,v in self.selected.items():v.set(p.get('selected',{}).get(r,True))
            self.minutes.set(str(p.get('minutes',60)));self.restore.set(p.get('restore_sleep',True))
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

    def history_key(self,serial=None):
        serial=serial or self.chosen_serial()
        return self.device_reports.get(serial,{}).get('instance_id') or serial

    def player_history(self,serial,room):
        return self.history.get(self.history_key(serial),room) or self.history.get(serial,room)

    def fleet_dialog(self):
        if self.fleet_window is not None and self.fleet_window.winfo_exists():
            self.fleet_window.lift();return
        self.capture_profile()
        win=ctk.CTkToplevel(self.root);self.fleet_window=win
        win.title('세팅 설정');win.geometry('760x700');win.minsize(650,500)
        win.configure(fg_color=BG);win.transient(self.root);win.after(100,lambda:win.grab_set() if win.winfo_exists() else None)
        label(win,'세팅 설정',size=23,bold=True).pack(anchor='w',padx=24,pady=(22,5))
        shortcut=ctk.CTkFrame(win,fg_color='transparent');shortcut.pack(fill='x',padx=24,pady=(7,12))
        self.hotkey_label=label(shortcut,'중지 키: '+self.stop_hotkey.value,size=13,color=GOLD)
        self.hotkey_label.pack(side='left')
        button(shortcut,'키 변경',self.hotkey_dialog,width=100).pack(side='right')
        label(win,'체크한 뮤뮤를 순서대로 수령합니다. 창마다 수령 기능과 간격을 지정하세요.',size=12,color=MUTED).pack(anchor='w',padx=24,pady=(0,12))
        body=ctk.CTkScrollableFrame(win,fg_color=BG);body.pack(fill='both',expand=True,padx=18)
        widgets={};self.fleet_labels={}
        if not self.players:label(body,'실행 중인 뮤뮤를 찾지 못했습니다. 게임 실행 후 뮤뮤 연결을 눌러 주세요.',wraplength=600).pack(pady=40)
        for ident,p in self.players.items():
            card=ctk.CTkFrame(body,fg_color=PANEL,border_width=1,border_color=LINE);card.pack(fill='x',pady=6)
            enabled=tk.BooleanVar(value=p.get('enabled',False));minutes=tk.StringVar(value=str(p.get('minutes',60)))
            rooms={r:tk.BooleanVar(value=p.get('selected',{}).get(r,r in LABELS)) for r in TASK_LABELS}
            restore=tk.BooleanVar(value=p.get('restore_sleep',True))
            head=ctk.CTkFrame(card,fg_color='transparent');head.pack(fill='x',padx=16,pady=(14,8))
            controls=[]
            check=ctk.CTkCheckBox(head,text=p.get('name','뮤뮤'),variable=enabled,font=font(15,bold=True),fg_color=GOLD,text_color=TEXT)
            check.pack(side='left');controls.append(check)
            status=label(head,'',size=11,color=MUTED);status.pack(side='right')
            row=ctk.CTkFrame(card,fg_color='transparent');row.pack(fill='x',padx=16,pady=(0,8))
            for r,title in LABELS.items():
                check=ctk.CTkCheckBox(row,text=title,variable=rooms[r],width=90,font=font(12),fg_color=GOLD)
                check.pack(side='left',padx=(0,10));controls.append(check)
            label(row,'간격',size=11,color=MUTED).pack(side='left',padx=(12,5))
            entry=ctk.CTkEntry(row,textvariable=minutes,width=62);entry.pack(side='left');controls.append(entry)
            label(row,'분',size=11,color=MUTED).pack(side='left',padx=5)
            extra=ctk.CTkFrame(card,fg_color='transparent');extra.pack(fill='x',padx=16,pady=(0,10))
            for i,(r,title) in enumerate(EXTRA_LABELS.items()):
                text=title+(' (재료 사용)' if r=='training' else ' (빨간 표시 보스)' if r=='worldboss' else '')
                check=ctk.CTkCheckBox(extra,text=text,variable=rooms[r],font=font(12),fg_color=GOLD)
                check.grid(row=i//2,column=i%2,sticky='w',padx=(0,30),pady=5);controls.append(check)
            check=ctk.CTkCheckBox(card,text='수령 후 절전 모드',variable=restore,font=font(11),fg_color=GOLD)
            check.pack(anchor='w',padx=16,pady=(0,8));controls.append(check)
            result=label(card,'',size=11,color=MUTED,wraplength=640,justify='left');result.pack(anchor='w',padx=16,pady=(0,12))
            self.fleet_labels[ident]=(status,result)
            widgets[ident]=(enabled,minutes,rooms,restore)
            if self.busy():
                for w in controls:w.configure(state='disabled')
        def apply():
            if self.busy():win.destroy();return
            changes={}
            try:
                for ident,(enabled,minutes,rooms,restore) in widgets.items():
                    interval=float(minutes.get())
                    if not 1<=interval<=1440:raise ValueError('간격은 1~1440분으로 입력하세요.')
                    chosen={r:v.get() for r,v in rooms.items()}
                    if enabled.get() and not any(chosen.values()):raise ValueError(self.players[ident]['name']+': 시설을 하나 이상 선택하세요.')
                    changes[ident]={'enabled':enabled.get(),'minutes':interval,'selected':chosen,'restore_sleep':restore.get()}
            except ValueError as exc:messagebox.showerror('설정 확인',str(exc),parent=win);return
            for ident,value in changes.items():self.players[ident].update(value)
            # Reload visible profile before save so old dashboard values cannot overwrite it.
            self.view_id=None;self.select_profile(self.chosen_serial())
            self.save();self.update_fleet_summary();win.destroy()
        button(win,'닫기' if self.busy() else '저장',apply,primary=True,width=120).pack(anchor='e',padx=24,pady=16)
        self.render_fleet_status()

    def render_fleet_status(self):
        if self.fleet_window is None or not self.fleet_window.winfo_exists():return
        live_ids={r.get('instance_id') for r in self.device_reports.values()}
        for ident,(status,result) in self.fleet_labels.items():
            if not status.winfo_exists():continue
            state=self.fleet_states.get(ident,{})
            text=state.get('status','대기' if ident in live_ids else '연결 미확인')
            if self.stop.paused and self.players.get(ident,{}).get('enabled'):
                text='일시중지'
            if state.get('next_at') is not None:
                seconds=max(0,int(state['next_at']-self.stop.clock()))
                text+=f' / 다음 {seconds//60:02d}:{seconds%60:02d}'
            if state.get('checked_at'):text+=' / 확인 '+state['checked_at']
            status.configure(text=text,text_color=GOLD if '중' in text else MUTED)
            p=self.players.get(ident,{})
            result.configure(text=' / '.join(TASK_LABELS[r]+': '+self.task_result(r,(self.history.get(ident,r) or self.history.get(p.get('serial',''),r)).get('result')) for r in TASK_LABELS if p.get('selected',{}).get(r,r in LABELS)))

    @staticmethod
    def task_result(task,result):
        if task=='training':
            if result=='collected':return '수련 완료'
            if result=='skipped':return '수련 조건 미충족'
        return RESULTS.get(result,'기록 없음')

    def setup_tray(self):
        if os.name!='nt':return
        try:
            from tray_support import Tray
            self.tray=Tray(self.events)
            self.root.bind('<Unmap>',self.on_minimize,add='+')
        except Exception as exc:self.log('트레이를 시작하지 못해 일반 최소화를 사용합니다: '+str(exc))

    def on_minimize(self,event):
        if event.widget==self.root and self.tray_ready and not self.closing and self.root.state()=='iconic':
            self.root.withdraw()

    def auto_connect(self):
        if not self.closing and not self.busy():self.connect()
