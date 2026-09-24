"""A multi-player workspace with a stable run bar and selected-player details."""
import os
from pathlib import Path
import tkinter as tk
import customtkinter as ctk
import cv2
from PIL import Image
from ui_theme import (BG,SIDE,PANEL,INSET,LINE,RULE,TEXT,MUTED,GOLD,MINT,RED,ACCENT,ACCENT_HOVER,CREAM,HEADER,HOVER,SELECTED,font,label,heading,button,panel,icon,install_theme,PaperFrame,GameTabs)
from vision import LABELS
from task_catalog import TASK_LABELS
from version import VERSION


class Dashboard:
    def build(self):
        install_theme()
        self.root.title('창키 도우미 '+VERSION)
        if os.name=='nt':self.root.iconbitmap(str(Path(__file__).parent/'assets/chanki.ico'))
        scale=self.root._get_window_scaling()
        width=max(980,min(1220,int(self.root.winfo_screenwidth()/scale)-40))
        height=max(640,min(820,int(self.root.winfo_screenheight()/scale)-100))
        self.root.geometry(f'{width}x{height}+12+12');self.root.minsize(980,640)
        self.root.configure(fg_color=BG)
        self.root.grid_columnconfigure(1,weight=1);self.root.grid_rowconfigure(1,weight=1)
        self.controls=[];self.next_at=None;self.session_count=0;self.log_empty=True
        self.adb_path=tk.StringVar(value=self.config.get('adb_path',''))
        self.address=tk.StringVar(value=self.config.get('address',''))
        self.minutes=tk.StringVar(value=str(self.config.get('minutes',60)))
        self.restore=tk.BooleanVar(value=self.config.get('restore_sleep',True))
        self.selected={k:tk.BooleanVar(value=self.config.get('selected',{}).get(k,True)) for k in LABELS}
        self.status=tk.StringVar(value='게임을 실행한 뒤 뮤뮤 연결을 눌러 주세요.')
        self.countdown=tk.StringVar(value='예약 없음')
        self.connection_text=tk.StringVar(value='선택한 뮤뮤 없음')
        self.device_info=tk.StringVar(value='목록에서 뮤뮤를 선택해 주세요.')
        self.fleet_summary=tk.StringVar(value='연결된 뮤뮤를 기다리고 있습니다.')
        self.serial_value=tk.StringVar(value='')
        # Compatibility with endpoint routing; the visible selector is the roster.
        self.serial=ctk.CTkComboBox(self.root,values=[],variable=self.serial_value,state='readonly')
        self.cards={};self.card_notes={};self.card_history={};self.switches={}
        self.roster_rows={};self.roster_signature=None;self.roster_filter=tk.StringVar(value='전체')
        self.roster_query=tk.StringVar(value='');self.logs_open=False
        self.ui_last_refresh=0;self.run_mode=None;self.cycle_results={}

        banner=ctk.CTkFrame(self.root,fg_color=HEADER,height=48,corner_radius=0)
        banner.grid(row=0,column=0,columnspan=2,sticky='ew');banner.grid_propagate(False)
        label(banner,'',image=icon('brand',color=CREAM,size=32)).pack(side='left',padx=(17,9),pady=6)
        heading(banner,'창키 도우미',size=21,color=CREAM).pack(side='left')
        label(banner,'│   창세기전 키우기 수령 도우미',size=11,color='#DAD1BE').pack(side='left',padx=15)
        label(banner,'v'+VERSION,size=10,color='#DAD1BE').pack(side='right',padx=18)
        ctk.CTkFrame(banner,height=1,fg_color='#BCA270',corner_radius=0).place(relx=0,rely=1,anchor='sw',relwidth=1)

        side=PaperFrame(self.root,width=162,corner_radius=0,fg_color=SIDE)
        side.grid(row=1,column=0,sticky='nsew');side.grid_propagate(False)
        side.grid_columnconfigure(0,weight=1);side.grid_rowconfigure(3,weight=1)
        self.list_button=button(side,'리스트',self.show_roster,width=138,height=45,anchor='w',
            image=icon('list',color=CREAM,size=21),fg_color=HEADER,hover_color='#534D3C',text_color=CREAM)
        self.list_button.grid(row=0,column=0,padx=12,pady=(26,9))
        self.fleet_button=button(side,'세팅 설정',self.fleet_dialog,width=138,height=43,anchor='w',
            image=icon('settings',color=MUTED,size=22),fg_color='transparent')
        self.fleet_button.grid(row=1,column=0,padx=12,pady=3)
        label(side,'작업 설정은 뮤뮤별로\n저장됩니다.',size=10,color=MUTED,justify='left').grid(row=2,column=0,sticky='w',padx=20,pady=(13,0))
        for row,(text,command,kind) in enumerate([('사용 가이드',self.guide_dialog,'guide'),('진단 파일 저장',self.export_diagnostics,'screen')],4):
            button(side,text,command,width=140,height=32,anchor='w',image=icon(kind,color=MUTED,size=19),
                   fg_color='transparent',text_color=MUTED,font=font(11)).grid(row=row,column=0,padx=11,pady=2)
        self.update_button=button(side,'업데이트',self.updates_dialog,width=140,height=32,anchor='w',
            image=icon('update',color=MUTED,size=19),fg_color='transparent',text_color=MUTED,font=font(11))
        self.update_button.grid(row=6,column=0,padx=11,pady=2)
        label(side,'◇  창키 도우미  ◇',size=10,color=GOLD).grid(row=7,column=0,pady=(14,18))

        main=ctk.CTkFrame(self.root,fg_color='transparent');self.main_panel=main
        main.grid(row=1,column=1,sticky='nsew',padx=16,pady=(12,10))
        main.grid_columnconfigure(0,weight=1);main.grid_rowconfigure(3,weight=1)
        header=ctk.CTkFrame(main,fg_color='transparent');header.grid(row=0,column=0,sticky='ew',pady=(0,9))
        header.grid_columnconfigure(0,weight=1)
        heading(header,'리스트',size=27).grid(row=0,column=0,sticky='w')
        label(header,'뮤뮤별 진행 상황과 다음 수령을 확인하세요.',size=11,color=MUTED).grid(row=1,column=0,sticky='w')
        self.connect_button=button(header,'뮤뮤 연결',self.connect,primary=True,width=112,height=38)
        self.connect_button.grid(row=0,column=1,rowspan=2,sticky='e');self.controls.append(self.connect_button)
        metrics=panel(main,height=48);metrics.grid(row=1,column=0,sticky='ew',pady=(0,10));metrics.grid_propagate(False)
        metrics.grid_columnconfigure((0,1,2),weight=1,uniform='metrics');metrics.grid_rowconfigure(0,weight=1)
        self.metric_values=[]
        for i,title in enumerate(['연결된 뮤뮤','실행 대상','확인 필요']):
            box=ctk.CTkFrame(metrics,fg_color='transparent');box.grid(row=0,column=i,padx=12,pady=8)
            label(box,title,size=12,bold=True).pack(side='left',padx=(0,10))
            value=label(box,'0개',size=20,bold=True,color=ACCENT if i<2 else GOLD)
            value.pack(side='left');self.metric_values.append(value)
        self.issue_metric=self.metric_values[2]
        for x in (1/3,2/3):ctk.CTkFrame(metrics,width=1,height=21,fg_color=RULE,corner_radius=0).place(relx=x,rely=.5,anchor='center')

        tools=ctk.CTkFrame(main,fg_color='transparent');tools.grid(row=2,column=0,sticky='ew',pady=(0,9));tools.grid_columnconfigure(1,weight=1)
        label(tools,'이름 검색',size=11,color=MUTED).grid(row=0,column=0,padx=(0,8))
        self.search_entry=ctk.CTkEntry(tools,textvariable=self.roster_query,width=150,height=32,font=font(12),fg_color=PANEL,border_color=LINE)
        self.search_entry.grid(row=0,column=1,sticky='ew',padx=(0,10))
        self.filter_menu=GameTabs(tools,['전체','실행 대상','확인 필요'],variable=self.roster_filter,width=254,height=32,command=lambda _:self.render_roster(force=True))
        self.filter_menu.grid(row=0,column=2)
        self.roster_query.trace_add('write',lambda *_:self.render_roster(force=True))

        body=ctk.CTkFrame(main,fg_color='transparent');body.grid(row=3,column=0,sticky='nsew')
        body.grid_columnconfigure(0,weight=1,minsize=470);body.grid_columnconfigure(1,weight=0,minsize=300);body.grid_rowconfigure(0,weight=1)
        roster=panel(body);roster.grid(row=0,column=0,sticky='nsew',padx=(0,10));roster.grid_columnconfigure(0,weight=1);roster.grid_rowconfigure(1,weight=1)
        columns=ctk.CTkFrame(roster,fg_color=INSET);columns.grid(row=0,column=0,sticky='ew',padx=8,pady=(8,0));columns.grid_columnconfigure(1,weight=1)
        label(columns,'',width=33).grid(row=0,column=0)
        label(columns,'뮤뮤 플레이어',size=11,bold=True,anchor='w').grid(row=0,column=1,sticky='ew',pady=7)
        label(columns,'진행 상태',size=10,color=MUTED,width=76).grid(row=0,column=2,padx=3)
        label(columns,'다음 수령',size=10,color=MUTED,width=67).grid(row=0,column=3)
        label(columns,'설정',size=10,color=MUTED,width=49).grid(row=0,column=4,padx=(3,13))
        self.roster_body=ctk.CTkScrollableFrame(roster,fg_color='transparent',corner_radius=0,scrollbar_button_color=LINE)
        self.roster_body.grid(row=1,column=0,sticky='nsew',padx=7,pady=(0,0));self.roster_body.grid_columnconfigure(0,weight=1)
        notes=ctk.CTkFrame(roster,fg_color='transparent');notes.grid(row=2,column=0,sticky='ew',padx=13,pady=(3,8));notes.grid_columnconfigure(0,weight=1)
        label(notes,'체크한 뮤뮤만 순서대로 실행합니다.',size=10,color=MUTED).grid(row=0,column=0,sticky='w')
        self.roster_total=label(notes,'0개',size=10,color=MUTED);self.roster_total.grid(row=0,column=1,sticky='e')

        detail=panel(body,width=300);self.detail_panel=detail
        detail.grid(row=0,column=1,sticky='nsew');detail.grid_columnconfigure(0,weight=1);detail.grid_rowconfigure(3,weight=1)
        self.detail_name=heading(detail,'뮤뮤를 선택하세요',size=17,anchor='w',width=267)
        self.detail_name.grid(row=0,column=0,sticky='w',padx=15,pady=(12,0))
        self.connection_badge=label(detail,textvariable=self.connection_text,size=10,color=MUTED,anchor='w',height=16)
        self.connection_badge.grid(row=1,column=0,sticky='w',padx=16,pady=(1,7))
        self.detail_tabs=GameTabs(detail,['수령 결과','최근 화면'],width=268,height=29,command=self.show_detail_tab)
        self.detail_tabs.grid(row=2,column=0,sticky='ew',padx=13,pady=(0,8));self.detail_tabs.set('수령 결과')
        self.detail_content=ctk.CTkFrame(detail,fg_color='transparent')
        self.detail_content.grid(row=3,column=0,sticky='nsew',padx=8)
        self.detail_content.grid_columnconfigure(0,weight=1);self.detail_content.grid_rowconfigure(0,weight=1)
        self.preview_frame=ctk.CTkFrame(self.detail_content,fg_color=INSET,corner_radius=0,height=150)
        self.preview_frame.grid(row=0,column=0,sticky='nsew',padx=6);self.preview_frame.grid_propagate(False)
        self.preview_placeholder=icon('screen',color=MUTED,size=30)
        self.preview_label=label(self.preview_frame,'화면 확인을 누르면\n최근 화면을 볼 수 있습니다.',size=11,color=MUTED,image=self.preview_placeholder,compound='top',padx=7,pady=5)
        self.preview_label.place(relx=.5,rely=.5,anchor='center');self.preview_label.bind('<Button-1>',lambda _:self.preview())
        self.preview_frame.bind('<Configure>',lambda _:self.render_thumbnail())
        self.preview_stamp=label(detail,'최근 캡처 / 클릭하면 확대',size=9,color=MUTED,height=16)
        self.preview_stamp.grid(row=4,column=0,sticky='w',padx=16,pady=(3,0))
        self.detail_tasks=ctk.CTkScrollableFrame(self.detail_content,fg_color='transparent',corner_radius=0,scrollbar_button_color=LINE)
        tasks=self.detail_tasks;tasks.grid(row=0,column=0,sticky='nsew');tasks.grid_columnconfigure(0,weight=1)
        self.detail_results={}
        for i,(key,title) in enumerate(TASK_LABELS.items()):
            row=ctk.CTkFrame(tasks,fg_color='transparent',corner_radius=0);row.grid(row=i,column=0,sticky='ew',padx=5,pady=0);row.grid_columnconfigure(1,weight=1)
            label(row,'',image=icon(key,color='#776346',size=18),width=22,height=25).grid(row=0,column=0,padx=(0,6))
            label(row,title,size=11,color=TEXT,height=25).grid(row=0,column=1,sticky='w')
            result=label(row,'기록 없음',size=10,color=MUTED,height=25);result.grid(row=0,column=2,sticky='e');self.detail_results[key]=result
            ctk.CTkFrame(row,height=1,fg_color=RULE,corner_radius=0).grid(row=1,column=0,columnspan=3,sticky='ew')
        self.detail_checked=label(detail,'설정과 기록은 뮤뮤별로 유지됩니다.',size=9,color=MUTED,height=16)
        self.detail_checked.grid(row=4,column=0,sticky='w',padx=16,pady=(3,0))
        self.inspect_button=button(detail,'화면 확인',self.inspect_selected,primary=True,width=92,height=29,font=font(10))
        self.inspect_button.grid(row=5,column=0,sticky='e',padx=13,pady=(5,10));self.controls.append(self.inspect_button)
        self.show_detail_tab('수령 결과')

        logs=panel(main);self.log_panel=logs
        logs.grid(row=4,column=0,sticky='ew',pady=(9,0));logs.grid_columnconfigure(0,weight=1)
        row=ctk.CTkFrame(logs,fg_color='transparent');row.grid(row=0,column=0,sticky='ew',padx=10,pady=6);row.grid_columnconfigure(1,weight=1)
        self.log_toggle=button(row,'실행 기록 펼치기',self.toggle_logs,width=119,height=27,font=font(11),fg_color='transparent')
        self.log_toggle.grid(row=0,column=0,padx=(0,9))
        self.log_summary=label(row,'실행 기록이 여기에 표시됩니다.',size=10,color=MUTED,anchor='w')
        self.log_summary.grid(row=0,column=1,sticky='w')
        self.copy_log_button=button(row,'복사',self.copy_logs,width=49,height=27,font=font(10),fg_color='transparent');self.copy_log_button.grid(row=0,column=2)
        self.logbox=ctk.CTkTextbox(logs,height=90,fg_color=INSET,text_color=TEXT,font=font(11),wrap='word',scrollbar_button_color=LINE)
        self.logbox.insert('end','첫 수령을 시작하면 진행 상황이 표시됩니다.');self.logbox.configure(state='disabled')

        footer_outer=panel(self.root,fg_color=INSET);footer_outer.grid(row=2,column=0,columnspan=2,sticky='ew')
        footer=ctk.CTkFrame(footer_outer,fg_color='transparent');self.footer=footer
        footer.pack(fill='x',padx=18,pady=(10,8));footer.grid_columnconfigure(0,weight=1)
        info=ctk.CTkFrame(footer,fg_color='transparent');info.grid(row=0,column=0,rowspan=2,sticky='w')
        self.run_target=label(info,'실행 대상을 선택해 주세요.',size=12,bold=True,anchor='w')
        self.run_target.grid(row=0,column=0,sticky='w',pady=(0,3))
        label(info,'완료',size=10,color=MUTED).grid(row=0,column=1,padx=(16,4))
        self.count_label=label(info,'0건',size=11,color=MINT,bold=True);self.count_label.grid(row=0,column=2)
        self.shortcut_hint=label(info,'중지 키: '+self.stop_hotkey.value,size=10,color=MUTED,anchor='w')
        self.shortcut_hint.grid(row=1,column=0,columnspan=3,sticky='w')
        self.once_button=button(footer,'한 번 수령',lambda:self.launch('once'),width=100);self.once_button.grid(row=0,column=1,rowspan=2,padx=(8,6));self.controls.append(self.once_button)
        self.start_button=button(footer,'자동 수령 시작',lambda:self.launch('repeat'),primary=True,width=143);self.start_button.grid(row=0,column=2,rowspan=2,padx=(0,6));self.controls.append(self.start_button)
        self.pause_button=button(footer,'일시중지',self.toggle_pause,width=88,state='disabled');self.pause_button.grid(row=0,column=3,rowspan=2,padx=(0,6))
        self.stop_button=button(footer,'중지',self.stop_run,width=70,state='disabled',text_color=RED,fg_color='#EADCCD',hover_color='#DFC5B5');self.stop_button.grid(row=0,column=4,rowspan=2)
        self.status_label=label(footer,textvariable=self.status,size=10,color=MUTED,anchor='w',wraplength=820,justify='left')
        self.status_label.grid(row=2,column=0,columnspan=5,sticky='ew',pady=(4,0))
        self.render_roster(force=True)

    def show_detail_tab(self,value):
        preview=value=='최근 화면'
        self.detail_tabs.set(value)
        if preview:
            self.detail_tasks.grid_remove();self.detail_checked.grid_remove()
            self.preview_frame.grid();self.preview_stamp.grid();self.render_thumbnail()
        else:
            self.preview_frame.grid_remove();self.preview_stamp.grid_remove()
            self.detail_tasks.grid();self.detail_checked.grid()

    def inspect_selected(self):
        self.show_detail_tab('최근 화면');self.launch('inspect')

    def show_roster(self):
        self.roster_query.set('');self.roster_filter.set('전체');self.render_roster(force=True)
        self.root.focus_set()

    def update_cards(self):
        self.refresh_history()

    def set_busy(self,value):
        for control in self.controls:control.configure(state='disabled' if value else 'normal')
        self.stop_button.configure(state='normal' if value else 'disabled')
        self.pause_button.configure(state='normal' if value and self.pause_allowed else 'disabled',text='재시작' if self.stop.paused else '일시중지')
        if not value:self.pause_allowed=False
        self.render_roster(force=True,working=value)

    def stop_run(self):
        self.stop.set();self.pause_button.configure(text='일시중지',state='disabled')
        if self.busy():self.status.set('중지하고 있습니다…')

    def render_thumbnail(self):
        if self.preview_image is None:return
        scale=self.preview_frame._get_widget_scaling()
        w=max(30,int(self.preview_frame.winfo_width()/scale)-20)
        h=max(30,int(self.preview_frame.winfo_height()/scale)-16)
        im=Image.fromarray(cv2.cvtColor(self.preview_image,cv2.COLOR_BGR2RGB));im.thumbnail((w,h))
        self.thumbnail=ctk.CTkImage(light_image=im,dark_image=im,size=im.size)
        self.preview_label.configure(text='',image=self.thumbnail)

    def toggle_logs(self):
        self.logs_open=not self.logs_open
        if self.logs_open:self.logbox.grid(row=1,column=0,sticky='ew',padx=12,pady=(0,10))
        else:self.logbox.grid_remove()
        self.log_toggle.configure(text='실행 기록 접기' if self.logs_open else '실행 기록 펼치기')

    def copy_logs(self):
        self.root.clipboard_clear();self.root.clipboard_append(self.logbox.get('1.0','end-1c'))
        self.copy_log_button.configure(text='복사됨')
        self.root.after(1500,lambda:self.copy_log_button.configure(text='복사') if not self.closing else None)

    def guide_dialog(self):
        win=ctk.CTkToplevel(self.root);win.title('사용 가이드');win.geometry('550x450');win.configure(fg_color=BG);win.transient(self.root)
        label(win,'연결하고, 정하고, 실행하세요.',size=22,bold=True).pack(anchor='w',padx=25,pady=(24,17))
        for title,text in [('01  뮤뮤 연결','게임을 실행하고 뮤뮤 연결을 누릅니다. 목록의 이름을 누르면 해당 화면과 기록을 볼 수 있습니다.'),('02  뮤뮤별 세팅','각 뮤뮤의 설정에서 농장, 목공소, 광산과 추가 작업을 선택합니다. 수련은 재료를 사용하는 작업입니다.'),('03  실행과 제어','체크된 뮤뮤만 순서대로 실행합니다. 한 번 수령은 한 차례, 자동 수령은 설정한 간격으로 반복합니다.'),('04  중지와 일시중지','일시중지 후 재시작하면 이어서 진행합니다. 중지는 실행을 종료합니다. 중지 키는 세팅 설정에서 바꿉니다.')]:
            label(win,title,size=13,bold=True).pack(anchor='w',padx=25,pady=(9,3))
            label(win,text,size=11,color=MUTED,wraplength=490,justify='left').pack(anchor='w',padx=25)
