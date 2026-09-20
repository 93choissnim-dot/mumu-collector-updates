"""Per-player draft settings with explicit save, stable identity and validation."""
import copy
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
from ui_theme import BG,PANEL,INSET,LINE,TEXT,MUTED,GOLD,RED,font,label,button,panel
from ui_state import selected_tasks,validate_profile
from task_catalog import TASK_LABELS
from vision import LABELS

TASK_HELP={
    'farm':'식량 수령','wood':'목재 수령','mine':'광물 수령',
    'ranking':'수령 가능한 랭킹 보상',
    'worldboss':'빨간 표시가 있는 보스만 확인',
    'excavation':'유물 발굴 보상 수령',
    'training':'수련 재료를 사용하는 작업',
}


class PlayerSettings:
    def __init__(self,app,initial=None):
        self.app=app;self.active=None;self.controls=[];self.profile_buttons={}
        self.draft={key:{'enabled':bool(p.get('enabled')),'minutes':str(p.get('minutes',60)),
                    'selected':{task:task in selected_tasks(p) for task in TASK_LABELS},
                    'restore_sleep':bool(p.get('restore_sleep',True))} for key,p in app.players.items()}
        self.original=copy.deepcopy(self.draft)
        win=ctk.CTkToplevel(app.root);self.window=win;app.fleet_window=win
        height=max(620,min(720,int(win.winfo_screenheight()/win._get_window_scaling())-85))
        win.title('세팅 설정');win.geometry(f'880x{height}');win.minsize(800,620);win.configure(fg_color=BG);win.transient(app.root)
        win.grid_columnconfigure(0,weight=1);win.grid_rowconfigure(2,weight=1)
        top=ctk.CTkFrame(win,fg_color='transparent');top.grid(row=0,column=0,sticky='ew',padx=22,pady=(20,8));top.grid_columnconfigure(0,weight=1)
        label(top,'세팅 설정',size=23,bold=True).grid(row=0,column=0,sticky='w')
        app.hotkey_label=label(top,'중지 키: '+app.stop_hotkey.value,size=11,color=GOLD)
        app.hotkey_label.grid(row=0,column=1,padx=(12,9))
        button(top,'키 변경',app.hotkey_dialog,width=80,height=32,font=font(11)).grid(row=0,column=2)
        self.note=label(win,'변경한 설정은 저장을 눌러야 적용됩니다.',size=11,color=MUTED)
        self.note.grid(row=1,column=0,sticky='w',padx=23,pady=(0,14))
        body=ctk.CTkFrame(win,fg_color='transparent');body.grid(row=2,column=0,sticky='nsew',padx=18)
        body.grid_columnconfigure(1,weight=1);body.grid_rowconfigure(0,weight=1)
        nav=ctk.CTkScrollableFrame(body,width=165,fg_color=INSET,corner_radius=10,scrollbar_button_color=LINE)
        nav.grid(row=0,column=0,sticky='ns',padx=(0,12));nav.grid_columnconfigure(0,weight=1)
        label(nav,'뮤뮤 플레이어',size=11,color=MUTED).grid(row=0,column=0,sticky='w',padx=9,pady=(8,12))
        for i,(ident,p) in enumerate(app.players.items(),1):
            name=p.get('name','뮤뮤');name=name if len(name)<=15 else name[:14]+'…'
            b=button(nav,name,lambda key=ident:self.select(key),width=153,height=39,anchor='w',font=font(11),fg_color='transparent')
            b.grid(row=i,column=0,sticky='ew',pady=3);self.profile_buttons[ident]=b
        self.body=ctk.CTkScrollableFrame(body,fg_color=PANEL,corner_radius=10,scrollbar_button_color=LINE)
        self.body.grid(row=0,column=1,sticky='nsew');self.body.grid_columnconfigure(0,weight=1)
        footer=ctk.CTkFrame(win,fg_color='transparent');footer.grid(row=3,column=0,sticky='ew',padx=22,pady=(12,18));footer.grid_columnconfigure(0,weight=1)
        self.error=label(footer,'',size=11,color=RED,wraplength=540,justify='left');self.error.grid(row=0,column=0,sticky='w')
        button(footer,'닫기',self.close,width=85).grid(row=0,column=1,padx=(10,8))
        self.save_button=button(footer,'저장',self.apply,primary=True,width=100);self.save_button.grid(row=0,column=2)
        win.protocol('WM_DELETE_WINDOW',self.close)
        initial=initial if initial in self.draft else app.view_id if app.view_id in self.draft else next(iter(self.draft),None)
        if initial:self.select(initial)
        else:
            label(self.body,'아직 연결한 뮤뮤가 없습니다.',size=17,bold=True).pack(pady=(65,10))
            label(self.body,'게임 실행 후 리스트에서 뮤뮤 연결을 눌러 주세요.\n중지 키는 위에서 변경할 수 있습니다.',size=12,color=MUTED,justify='center').pack(padx=15)
        self.set_running(app.busy())

    def capture(self):
        if self.active is None:return
        self.draft[self.active]={'enabled':self.enabled.get(),'minutes':self.minutes.get(),
                                'selected':{k:v.get() for k,v in self.tasks.items()},'restore_sleep':self.restore.get()}

    def select(self,ident):
        if ident not in self.draft:return
        self.capture();self.active=ident;p=self.draft[ident]
        for child in self.body.winfo_children():child.destroy()
        self.controls=[];self.error.configure(text='')
        for key,b in self.profile_buttons.items():b.configure(fg_color='#2A3546' if key==ident else 'transparent',text_color=GOLD if key==ident else TEXT)
        self.enabled=tk.BooleanVar(value=p['enabled']);self.minutes=tk.StringVar(value=p['minutes']);self.restore=tk.BooleanVar(value=p['restore_sleep'])
        self.tasks={key:tk.BooleanVar(value=p['selected'][key]) for key in TASK_LABELS}
        name=self.app.players[ident].get('name','뮤뮤')
        label(self.body,name,size=20,bold=True,wraplength=475,justify='left').grid(row=0,column=0,sticky='w',padx=16,pady=(15,5))
        enable=ctk.CTkSwitch(self.body,text='이 뮤뮤를 실행 대상에 포함',variable=self.enabled,font=font(12),progress_color=GOLD,button_color=TEXT)
        enable.grid(row=1,column=0,sticky='w',padx=17,pady=(5,19));self.controls.append(enable)
        self.task_checks={}
        for row,title,keys in [(2,'자원 시설',list(LABELS)),(4,'추가 작업',[key for key in TASK_LABELS if key not in LABELS])]:
            label(self.body,title,size=13,bold=True).grid(row=row,column=0,sticky='w',padx=17,pady=(0,7))
            group=ctk.CTkFrame(self.body,fg_color='transparent');group.grid(row=row+1,column=0,sticky='ew',padx=12,pady=(0,16));group.grid_columnconfigure((0,1),weight=1,uniform='tasks')
            for i,key in enumerate(keys):
                tile=ctk.CTkFrame(group,fg_color=INSET,corner_radius=8);tile.grid(row=i//2,column=i%2,sticky='nsew',padx=4,pady=4)
                check=ctk.CTkCheckBox(tile,text=TASK_LABELS[key],variable=self.tasks[key],font=font(12),fg_color=GOLD,border_color=MUTED,checkbox_width=19,checkbox_height=19)
                check.pack(anchor='w',padx=12,pady=(12,5));self.controls.append(check);self.task_checks[key]=check
                label(tile,TASK_HELP[key],size=10,color=GOLD if key=='training' else MUTED,wraplength=205,justify='left').pack(anchor='w',padx=12,pady=(0,11))
        interval=ctk.CTkFrame(self.body,fg_color=INSET,corner_radius=8);interval.grid(row=6,column=0,sticky='ew',padx=16,pady=(0,10));interval.grid_columnconfigure(4,weight=1)
        label(interval,'수령 간격',size=12,bold=True).grid(row=0,column=0,padx=(12,10),pady=13)
        self.interval_entry=ctk.CTkEntry(interval,textvariable=self.minutes,width=64,height=32,justify='center',fg_color=PANEL,border_color=LINE,font=font(12))
        self.interval_entry.grid(row=0,column=1);self.controls.append(self.interval_entry)
        label(interval,'분',size=11,color=MUTED).grid(row=0,column=2,padx=(7,10))
        presets=ctk.CTkOptionMenu(interval,values=['간격 선택','15분','30분','60분','120분'],width=102,height=30,font=font(11),fg_color='#243146',button_color='#243146',command=lambda value:self.minutes.set(value[:-1]) if value!='간격 선택' else None)
        presets.grid(row=0,column=3,padx=(0,12));self.controls.append(presets)
        restore=ctk.CTkSwitch(self.body,text='작업을 마치면 게임 절전 모드로 복귀',variable=self.restore,font=font(11),progress_color=GOLD,button_color=TEXT)
        restore.grid(row=7,column=0,sticky='w',padx=17,pady=(7,16));self.controls.append(restore)
        self.set_running(self.app.busy())

    def set_running(self,running):
        for control in self.controls:control.configure(state='disabled' if running else 'normal')
        self.save_button.configure(state='disabled' if running or not self.draft else 'normal')
        self.note.configure(text='실행 중에는 설정을 확인할 수 있습니다. 중지 후 변경해 주세요.' if running else '변경한 설정은 저장을 눌러야 적용됩니다.')

    def apply(self):
        if self.app.busy():self.set_running(True);return False
        self.capture();changes={}
        for ident,values in self.draft.items():
            try:changes[ident]=validate_profile(values)
            except (ValueError,TypeError):
                self.select(ident);self.error.configure(text=self.app.players[ident].get('name','뮤뮤')+': 간격은 1~1440분, 실행할 작업은 하나 이상 선택해 주세요.');return False
        previous=copy.deepcopy(self.app.players)
        for ident,values in changes.items():self.app.players[ident].update(values)
        try:self.app.save()
        except OSError as exc:
            self.app.players=previous;self.error.configure(text='저장하지 못했습니다: '+str(exc));return False
        self.app.update_fleet_summary()
        if self.active:self.app.select_player(self.active)
        self.app.status.set('뮤뮤별 세팅을 저장했습니다.')
        self.window.destroy();return True

    def close(self):
        self.capture()
        if self.draft!=self.original:
            answer=messagebox.askyesnocancel('변경한 설정','변경한 설정을 저장할까요?',parent=self.window)
            if answer is None:return
            if answer:
                self.apply();return
        self.window.destroy()
