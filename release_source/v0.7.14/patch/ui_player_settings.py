"""Per-player draft settings with explicit save, stable identity and validation."""
import copy
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
from ui_theme import BG,PANEL,INSET,LINE,RULE,TEXT,MUTED,GOLD,RED,ACCENT,ACCENT_HOVER,CREAM,HEADER,HOVER,font,label,heading,button,panel,icon
from ui_state import selected_tasks,validate_profile
from task_catalog import TASK_LABELS
from profile_edits import merge_profiles,copy_settings
from ui_layout import fit_window

TASK_HELP={
    'farm':'식량 수령','wood':'목재 수령','mine':'광물 수령',
    'ranking':'수령 가능한 보상 확인',
    'worldboss':'빨간 표시가 있는 보스만 확인',
    'excavation':'유물 발굴 보상 수령',
    'training':'수련 재료 사용',
}


INTERVAL_PRESETS = {'1시간': '60', '2시간': '120', '3시간': '180'}


class PlayerSettings:
    def __init__(self,app,initial=None):
        self.app=app;self.active=None;self.controls=[];self.profile_buttons={}
        self.draft={key:{'enabled':bool(p.get('enabled')),'minutes':format(p.get('minutes',60),'g') if isinstance(p.get('minutes',60),(int,float)) else str(p.get('minutes',60)),
                    'selected':{task:task in selected_tasks(p) for task in TASK_LABELS},
                    'restore_sleep':True} for key,p in app.players.items()}
        self.original=copy.deepcopy(self.draft)
        win=ctk.CTkToplevel(app.root);self.window=win;app.fleet_window=win
        win.title('세팅 설정');win.configure(fg_color=BG);win.transient(app.root)
        width,height=fit_window(win,(880,720),(640,430))
        win.grid_columnconfigure(0,weight=1);win.grid_rowconfigure(2,weight=1)
        top=ctk.CTkFrame(win,fg_color='transparent');top.grid(row=0,column=0,sticky='ew',padx=22,pady=(20,8));top.grid_columnconfigure(0,weight=1)
        heading(top,'세팅 설정',size=23).grid(row=0,column=0,sticky='w')
        app.hotkey_label=label(top,'중지 키: '+app.stop_hotkey.value,size=11,color=GOLD)
        app.hotkey_label.grid(row=0,column=1,padx=(12,9))
        button(top,'키 변경',app.hotkey_dialog,width=80,height=32,font=font(11)).grid(row=0,column=2)
        self.note=label(win,'변경한 설정은 저장을 눌러야 적용됩니다.',size=11,color=MUTED)
        note_row=ctk.CTkFrame(win,fg_color='transparent');note_row.grid(row=1,column=0,sticky='ew',padx=22,pady=(0,10));note_row.grid_columnconfigure(0,weight=1)
        self.note.destroy();self.note=label(note_row,'변경한 설정은 저장을 눌러야 적용됩니다.',size=11,color=MUTED,wraplength=max(220,width-245),justify='left')
        self.note.grid(row=0,column=0,sticky='w')
        self.copy_button=button(note_row,'다른 뮤뮤에 적용',self.bulk_dialog,width=126,height=30,font=font(11))
        self.copy_button.grid(row=0,column=1,padx=(8,0))
        body=ctk.CTkFrame(win,fg_color='transparent');body.grid(row=2,column=0,sticky='nsew',padx=18)
        body.grid_columnconfigure(1,weight=1);body.grid_rowconfigure(0,weight=1)
        nav_width=130 if width<800 else 165
        nav=ctk.CTkScrollableFrame(body,width=nav_width,fg_color=INSET,corner_radius=0,border_width=1,border_color=LINE,scrollbar_button_color=LINE)
        nav.grid(row=0,column=0,sticky='ns',padx=(0,12));nav.grid_columnconfigure(0,weight=1)
        label(nav,'뮤뮤 플레이어',size=11,color=MUTED).grid(row=0,column=0,sticky='w',padx=9,pady=(8,12))
        for i,(ident,p) in enumerate(app.players.items(),1):
            name=p.get('name','뮤뮤');name=name if len(name)<=15 else name[:14]+'…'
            b=button(nav,name,lambda key=ident:self.select(key),width=nav_width-12,height=39,anchor='w',font=font(11),fg_color='transparent')
            b.grid(row=i,column=0,sticky='ew',pady=3);self.profile_buttons[ident]=b
        self.body=ctk.CTkScrollableFrame(body,fg_color=PANEL,corner_radius=0,border_width=1,border_color=LINE,scrollbar_button_color=LINE)
        self.body.grid(row=0,column=1,sticky='nsew');self.body.grid_columnconfigure(0,weight=1)
        footer=ctk.CTkFrame(win,fg_color='transparent');footer.grid(row=3,column=0,sticky='ew',padx=22,pady=(12,18));footer.grid_columnconfigure(0,weight=1)
        self.error=label(footer,'',size=11,color=RED,wraplength=max(180,width-265),justify='left');self.error.grid(row=0,column=0,sticky='w')
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
                                'selected':{k:v.get() for k,v in self.tasks.items()},'restore_sleep':True}

    def select(self,ident):
        if ident not in self.draft:return
        self.capture();self.active=ident;p=self.draft[ident]
        for child in self.body.winfo_children():child.destroy()
        self.controls=[];self.error.configure(text='')
        for key,b in self.profile_buttons.items():b.configure(fg_color=HEADER if key==ident else 'transparent',text_color=CREAM if key==ident else TEXT,hover_color='#534D3C' if key==ident else HOVER)
        self.enabled=tk.BooleanVar(value=p['enabled']);self.minutes=tk.StringVar(value=p['minutes'])
        self.tasks={key:tk.BooleanVar(value=p['selected'][key]) for key in TASK_LABELS}
        name=self.app.players[ident].get('name','뮤뮤')
        label(self.body,name,size=20,bold=True,wraplength=340,justify='left').grid(row=0,column=0,sticky='w',padx=16,pady=(15,5))
        enable=ctk.CTkSwitch(self.body,text='이 뮤뮤를 실행 대상에 포함',variable=self.enabled,font=font(12),progress_color=ACCENT,button_color=CREAM)
        enable.grid(row=1,column=0,sticky='w',padx=17,pady=(5,19));self.controls.append(enable)
        interval=panel(self.body,fg_color=INSET);interval.grid(row=2,column=0,sticky='ew',padx=16,pady=(0,18));interval.grid_columnconfigure(4,weight=1)
        label(interval,'수령 간격',size=12,bold=True).grid(row=0,column=0,padx=(12,10),pady=13)
        self.interval_entry=ctk.CTkEntry(interval,textvariable=self.minutes,width=64,height=32,justify='center',fg_color=PANEL,border_color=LINE,font=font(12))
        self.interval_entry.grid(row=0,column=1);self.controls.append(self.interval_entry)
        label(interval,'분',size=11,color=MUTED).grid(row=0,column=2,padx=(7,10))
        self.interval_presets=ctk.CTkOptionMenu(interval,values=list(INTERVAL_PRESETS),width=112,height=32,font=font(11),fg_color=ACCENT,button_color=ACCENT,button_hover_color=ACCENT_HOVER,text_color=CREAM,command=self.choose_interval)
        self.interval_presets.grid(row=0,column=3,padx=(0,12));self.controls.append(self.interval_presets)
        self.minutes.trace_add('write',self.sync_interval)
        self.sync_interval()
        title_row=ctk.CTkFrame(self.body,fg_color='transparent');title_row.grid(row=3,column=0,sticky='ew',padx=17,pady=(0,8));title_row.grid_columnconfigure(0,weight=1)
        label(title_row,'수령할 작업',size=13,bold=True).grid(row=0,column=0,sticky='w')
        self.select_all_button=button(title_row,'전체 선택',lambda:self.set_all_tasks(True),width=77,height=27,font=font(10))
        self.select_all_button.grid(row=0,column=1,padx=(5,4));self.controls.append(self.select_all_button)
        self.clear_all_button=button(title_row,'전체 해제',lambda:self.set_all_tasks(False),width=77,height=27,font=font(10))
        self.clear_all_button.grid(row=0,column=2);self.controls.append(self.clear_all_button)
        self.task_checks={}
        self.task_group=panel(self.body,fg_color=PANEL)
        self.task_group.grid(row=4,column=0,sticky='ew',padx=16,pady=(0,12));self.task_group.grid_columnconfigure(1,weight=1)
        for i,key in enumerate(TASK_LABELS):
            check=ctk.CTkCheckBox(self.task_group,text=TASK_LABELS[key],variable=self.tasks[key],width=142,height=24,font=font(12),fg_color=ACCENT,border_color=MUTED,checkbox_width=19,checkbox_height=19)
            check.grid(row=i*2,column=0,sticky='w',padx=(14,8),pady=9);self.controls.append(check);self.task_checks[key]=check
            label(self.task_group,TASK_HELP[key],size=10,color=GOLD if key=='training' else MUTED,wraplength=170,justify='left',anchor='w').grid(row=i*2,column=1,sticky='w',padx=(0,14),pady=9)
            if i<len(TASK_LABELS)-1:
                ctk.CTkFrame(self.task_group,height=1,fg_color=RULE,corner_radius=0).grid(row=i*2+1,column=0,columnspan=2,sticky='ew',padx=13)
        self.set_running(self.app.busy())

    def choose_interval(self,value):
        if not self.app.busy() and value in INTERVAL_PRESETS:
            self.minutes.set(INTERVAL_PRESETS[value])

    def sync_interval(self,*_):
        try:minutes=float(self.minutes.get())
        except ValueError:minutes=None
        value=next((title for title,number in INTERVAL_PRESETS.items() if minutes==float(number)),'직접 입력')
        self.interval_presets.set(value)

    def set_all_tasks(self,selected):
        if self.app.busy():return
        for value in self.tasks.values():value.set(bool(selected))
        self.error.configure(text='전체 해제했습니다. 저장하려면 작업을 선택하거나 실행 대상에서 제외해 주세요.' if not selected and self.enabled.get() else '')

    def set_running(self,running):
        for control in self.controls:control.configure(state='disabled' if running else 'normal')
        self.save_button.configure(state='disabled' if running or not self.draft else 'normal')
        self.copy_button.configure(state='disabled' if running or len(self.draft)<2 else 'normal')
        self.note.configure(text='실행 중에는 설정을 확인할 수 있습니다. 중지 후 변경해 주세요.' if running else '변경한 설정은 저장을 눌러야 적용됩니다.')

    def apply(self):
        if self.app.busy():self.set_running(True);return False
        self.capture()
        try:merged=merge_profiles(self.app.players,self.original,self.draft)
        except (ValueError,TypeError,KeyError) as exc:
            self.error.configure(text=str(exc) or '수령 간격과 선택한 작업을 확인해 주세요.');return False
        previous=copy.deepcopy(self.app.players)
        self.app.players=merged
        try:self.app.save()
        except OSError as exc:
            self.app.players=previous;self.error.configure(text='저장하지 못했습니다: '+str(exc));return False
        self.app.update_fleet_summary()
        if self.active:self.app.select_player(self.active)
        self.app.status.set('뮤뮤별 세팅을 저장했습니다.')
        self.window.destroy();return True

    def bulk_dialog(self):
        if self.app.busy() or self.active is None:return
        self.capture();source=self.active
        win=ctk.CTkToplevel(self.window);win.title('설정 일괄 적용');win.configure(fg_color=BG);win.transient(self.window)
        width,_=fit_window(win,(590,580),(500,420))
        win.grid_columnconfigure(0,weight=1);win.grid_rowconfigure(3,weight=1)
        heading(win,'설정 일괄 적용',size=21).grid(row=0,column=0,sticky='w',padx=20,pady=(18,6))
        label(win,'기준: '+self.app.players[source].get('name','뮤뮤'),size=12,bold=True,wraplength=width-50,justify='left').grid(row=1,column=0,sticky='w',padx=20,pady=(0,9))
        fields=ctk.CTkFrame(win,fg_color='transparent');fields.grid(row=2,column=0,sticky='ew',padx=20,pady=(0,10))
        choices={}
        for col,(field,title) in enumerate([('selected','수령할 작업'),('minutes','수령 간격')]):
            value=tk.BooleanVar(value=True);choices[field]=value
            ctk.CTkCheckBox(fields,text=title,variable=value,font=font(11),width=125).grid(row=0,column=col,padx=(0,7))
        if self.draft[source]['selected'].get('training'):
            label(fields,'작업을 복사하면 재료를 사용하는 수련도 포함됩니다.',size=10,color=GOLD,wraplength=width-55,justify='left').grid(row=1,column=0,columnspan=3,sticky='w',pady=(8,0))
        targets=ctk.CTkScrollableFrame(win,fg_color=PANEL,corner_radius=0);targets.grid(row=3,column=0,sticky='nsew',padx=20)
        values={}
        for ident,p in self.app.players.items():
            if ident==source or ident not in self.draft:continue
            value=tk.BooleanVar(value=False);values[ident]=value
            ctk.CTkCheckBox(targets,text=p.get('name','뮤뮤'),variable=value,font=font(12)).pack(anchor='w',padx=10,pady=9)
        footer=ctk.CTkFrame(win,fg_color='transparent');footer.grid(row=4,column=0,sticky='ew',padx=20,pady=14);footer.grid_columnconfigure(0,weight=1)
        error=label(footer,'복사 후 세팅 설정에서 저장을 눌러 주세요.',size=10,color=MUTED,wraplength=width-45,justify='left');error.grid(row=0,column=0,columnspan=3,sticky='w',pady=(0,10))
        def apply():
            if self.app.busy():error.configure(text='수령을 중지한 뒤 적용해 주세요.',text_color=RED);return
            try:count=copy_settings(self.draft,source,[key for key,v in values.items() if v.get()],[key for key,v in choices.items() if v.get()])
            except ValueError as exc:error.configure(text=str(exc),text_color=RED);return
            self.note.configure(text=f'{count}개 뮤뮤에 설정을 복사했습니다. 저장을 누르면 적용됩니다.')
            win.destroy()
        select_row=ctk.CTkFrame(footer,fg_color='transparent');select_row.grid(row=1,column=0,sticky='w')
        button(select_row,'전체 선택',lambda:[v.set(True) for v in values.values()],width=70,height=30,font=font(10)).pack(side='left',padx=(0,3))
        button(select_row,'전체 해제',lambda:[v.set(False) for v in values.values()],width=70,height=30,font=font(10)).pack(side='left')
        button(footer,'닫기',win.destroy,width=75).grid(row=1,column=1,padx=8)
        button(footer,'선택 대상에 복사',apply,primary=True,width=137).grid(row=1,column=2)
        win.after(100,lambda:win.grab_set() if win.winfo_exists() else None)
        self.bulk_window=win;self.bulk_targets=values;self.bulk_fields=choices;self.bulk_apply=apply

    def close(self):
        self.capture()
        if self.draft!=self.original:
            answer=messagebox.askyesnocancel('변경한 설정','변경한 설정을 저장할까요?',parent=self.window)
            if answer is None:return
            if answer:
                self.apply();return
        self.window.destroy()
