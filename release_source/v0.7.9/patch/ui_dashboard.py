"""A multi-player workspace with a stable run bar and selected-player details."""
import os
from pathlib import Path
import tkinter as tk
import customtkinter as ctk
import cv2
from PIL import Image
from ui_theme import BG,SIDE,PANEL,INSET,LINE,TEXT,MUTED,GOLD,MINT,RED,font,label,button,panel,icon
from vision import LABELS
from task_catalog import TASK_LABELS
from version import VERSION


class Dashboard:
    def build(self):
        ctk.set_appearance_mode('dark')
        self.root.title('창키 도우미 '+VERSION)
        if os.name=='nt':self.root.iconbitmap(str(Path(__file__).parent/'assets/chanki.ico'))
        scale=self.root._get_window_scaling()
        width=max(980,min(1220,int(self.root.winfo_screenwidth()/scale)-40))
        height=max(640,min(820,int(self.root.winfo_screenheight()/scale)-100))
        self.root.geometry(f'{width}x{height}+12+12');self.root.minsize(980,640)
        self.root.configure(fg_color=BG)
        self.root.grid_columnconfigure(1,weight=1);self.root.grid_rowconfigure(0,weight=1)
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

        side=ctk.CTkFrame(self.root,width=152,corner_radius=0,fg_color=SIDE)
        side.grid(row=0,column=0,sticky='nsew');side.grid_propagate(False)
        side.grid_columnconfigure(0,weight=1);side.grid_rowconfigure(6,weight=1)
        label(side,'',image=icon('brand',size=34),height=38).grid(row=0,column=0,sticky='w',padx=19,pady=(25,8))
        label(side,'창키 도우미',size=18,bold=True).grid(row=1,column=0,sticky='w',padx=19)
        label(side,'창세기전 키우기',size=10,color=MUTED).grid(row=2,column=0,sticky='w',padx=19,pady=(2,27))
        self.list_button=button(side,'리스트',self.show_roster,width=124,anchor='w',fg_color='#283246',text_color=GOLD)
        self.list_button.grid(row=3,column=0,padx=14,pady=4)
        self.fleet_button=button(side,'세팅 설정',self.fleet_dialog,width=124,anchor='w',fg_color='transparent')
        self.fleet_button.grid(row=4,column=0,padx=14,pady=4)
        label(side,'작업 설정은 뮤뮤별로\n저장됩니다.',size=10,color=MUTED,justify='left').grid(row=5,column=0,sticky='w',padx=20,pady=(13,0))
        for row,(text,command) in enumerate([('사용 가이드',self.guide_dialog),('진단 파일 저장',self.export_diagnostics)],7):
            button(side,text,command,width=124,height=34,anchor='w',fg_color='transparent',text_color=MUTED,font=font(11)).grid(row=row,column=0,padx=14,pady=2)
        self.update_button=button(side,'업데이트',self.updates_dialog,width=124,height=34,anchor='w',fg_color='transparent',text_color=MUTED,font=font(11))
        self.update_button.grid(row=9,column=0,padx=14,pady=2)
        label(side,'v'+VERSION,size=10,color=MUTED).grid(row=10,column=0,sticky='w',padx=20,pady=(18,20))

        main=ctk.CTkFrame(self.root,fg_color='transparent');self.main_panel=main
        main.grid(row=0,column=1,sticky='nsew',padx=18,pady=(18,14))
        main.grid_columnconfigure(0,weight=1);main.grid_rowconfigure(2,weight=1)
        header=ctk.CTkFrame(main,fg_color='transparent');header.grid(row=0,column=0,sticky='ew',pady=(0,14))
        header.grid_columnconfigure(0,weight=1)
        label(header,'리스트',size=27,bold=True).grid(row=0,column=0,sticky='w')
        label(header,'뮤뮤별 진행 상황과 다음 수령을 확인하세요.',size=11,color=MUTED).grid(row=1,column=0,sticky='w',pady=(3,0))
        self.connect_button=button(header,'뮤뮤 연결',self.connect,width=108)
        self.connect_button.grid(row=0,column=1,rowspan=2,sticky='e');self.controls.append(self.connect_button)
        metrics=ctk.CTkFrame(main,fg_color='transparent');metrics.grid(row=1,column=0,sticky='ew',pady=(0,14))
        metrics.grid_columnconfigure((0,1,2),weight=1,uniform='metrics')
        self.metric_values=[]
        for i,title in enumerate(['연결된 뮤뮤','실행 대상','이번 실행 완료']):
            box=panel(metrics,height=66);box.grid(row=0,column=i,sticky='ew',padx=(0 if i==0 else 5,0 if i==2 else 5));box.grid_propagate(False)
            label(box,title,size=10,color=MUTED).place(x=15,y=10)
            value=label(box,'0개' if i<2 else '0건',size=21,bold=True,color=GOLD if i==1 else TEXT)
            value.place(x=15,y=30);self.metric_values.append(value)
        self.count_label=self.metric_values[2]

        body=ctk.CTkFrame(main,fg_color='transparent');body.grid(row=2,column=0,sticky='nsew')
        body.grid_columnconfigure(0,weight=1,minsize=470);body.grid_columnconfigure(1,weight=0,minsize=305);body.grid_rowconfigure(0,weight=1)
        roster=panel(body);roster.grid(row=0,column=0,sticky='nsew',padx=(0,12));roster.grid_columnconfigure(0,weight=1);roster.grid_rowconfigure(3,weight=1)
        row=ctk.CTkFrame(roster,fg_color='transparent');row.grid(row=0,column=0,sticky='ew',padx=16,pady=(15,8));row.grid_columnconfigure(0,weight=1)
        label(row,'뮤뮤 플레이어',size=15,bold=True).grid(row=0,column=0,sticky='w')
        self.roster_total=label(row,'0개',size=11,color=MUTED);self.roster_total.grid(row=0,column=1,sticky='e')
        tools=ctk.CTkFrame(roster,fg_color='transparent');tools.grid(row=1,column=0,sticky='ew',padx=14,pady=(0,10));tools.grid_columnconfigure(1,weight=1)
        label(tools,'이름 검색',size=10,color=MUTED).grid(row=0,column=0,padx=(0,8))
        self.search_entry=ctk.CTkEntry(tools,textvariable=self.roster_query,placeholder_text='뮤뮤 이름 검색',width=155,height=32,font=font(11),fg_color=INSET,border_color=LINE)
        self.search_entry.grid(row=0,column=1,sticky='ew',padx=(0,8))
        self.filter_menu=ctk.CTkOptionMenu(tools,values=['전체','실행 대상','확인 필요'],variable=self.roster_filter,width=108,height=32,font=font(11),fg_color='#243146',button_color='#243146',command=lambda _:self.render_roster(force=True))
        self.filter_menu.grid(row=0,column=2)
        label(roster,'체크: 실행 대상    이름: 상세 보기    설정: 작업 변경',size=10,color=MUTED).grid(row=2,column=0,sticky='w',padx=17,pady=(0,7))
        self.roster_body=ctk.CTkScrollableFrame(roster,fg_color='transparent',corner_radius=0,scrollbar_button_color=LINE)
        self.roster_body.grid(row=3,column=0,sticky='nsew',padx=7,pady=(0,8));self.roster_body.grid_columnconfigure(0,weight=1)
        self.roster_query.trace_add('write',lambda *_:self.render_roster(force=True))

        detail=panel(body,width=305);self.detail_panel=detail
        detail.grid(row=0,column=1,sticky='nsew');detail.grid_columnconfigure(0,weight=1);detail.grid_rowconfigure(4,weight=1)
        self.detail_name=label(detail,'뮤뮤를 선택하세요',size=15,bold=True,anchor='w',width=270)
        self.detail_name.grid(row=0,column=0,sticky='w',padx=16,pady=(15,2))
        self.connection_badge=label(detail,textvariable=self.connection_text,size=10,color=MUTED,anchor='w')
        self.connection_badge.grid(row=1,column=0,sticky='w',padx=16,pady=(0,9))
        self.preview_frame=ctk.CTkFrame(detail,fg_color=INSET,corner_radius=8,height=150)
        self.preview_frame.grid(row=2,column=0,sticky='ew',padx=14);self.preview_frame.grid_propagate(False)
        self.preview_placeholder=icon('screen',color='#65768D',size=30)
        self.preview_label=label(self.preview_frame,'화면 확인을 누르면\n최근 화면을 볼 수 있습니다.',size=11,color=MUTED,image=self.preview_placeholder,compound='top',padx=7,pady=5)
        self.preview_label.place(relx=.5,rely=.5,anchor='center')
        self.preview_label.bind('<Button-1>',lambda _:self.preview())
        self.preview_frame.bind('<Configure>',lambda _:self.render_thumbnail())
        row=ctk.CTkFrame(detail,fg_color='transparent');row.grid(row=3,column=0,sticky='ew',padx=14,pady=(7,9));row.grid_columnconfigure(0,weight=1)
        self.preview_stamp=label(row,'최근 캡처 / 클릭하면 확대',size=9,color=MUTED)
        self.preview_stamp.grid(row=0,column=0,sticky='w')
        self.inspect_button=button(row,'화면 확인',lambda:self.launch('inspect'),width=79,height=28,font=font(10))
        self.inspect_button.grid(row=0,column=1);self.controls.append(self.inspect_button)
        tasks=ctk.CTkScrollableFrame(detail,fg_color='transparent',corner_radius=0,scrollbar_button_color=LINE)
        tasks.grid(row=4,column=0,sticky='nsew',padx=8,pady=(0,8));tasks.grid_columnconfigure(0,weight=1)
        label(tasks,'작업별 최근 결과',size=12,bold=True).grid(row=0,column=0,sticky='w',padx=7,pady=(0,5))
        self.detail_results={}
        for i,(key,title) in enumerate(TASK_LABELS.items(),1):
            row=ctk.CTkFrame(tasks,fg_color='transparent');row.grid(row=i,column=0,sticky='ew',padx=7,pady=2);row.grid_columnconfigure(0,weight=1)
            label(row,title,size=10,color=MUTED).grid(row=0,column=0,sticky='w')
            result=label(row,'기록 없음',size=10,color=MUTED);result.grid(row=0,column=1,sticky='e');self.detail_results[key]=result
        self.detail_checked=label(detail,'설정과 기록은 뮤뮤별로 유지됩니다.',size=9,color=MUTED)
        self.detail_checked.grid(row=5,column=0,sticky='w',padx=16,pady=(0,12))

        logs=panel(main);self.log_panel=logs
        logs.grid(row=3,column=0,sticky='ew',pady=(12,10));logs.grid_columnconfigure(0,weight=1)
        row=ctk.CTkFrame(logs,fg_color='transparent');row.grid(row=0,column=0,sticky='ew',padx=13,pady=7);row.grid_columnconfigure(1,weight=1)
        self.log_toggle=button(row,'실행 기록 펼치기',self.toggle_logs,width=120,height=29,font=font(10),fg_color='transparent')
        self.log_toggle.grid(row=0,column=0,padx=(0,9))
        self.log_summary=label(row,'실행 기록이 여기에 표시됩니다.',size=10,color=MUTED,anchor='w')
        self.log_summary.grid(row=0,column=1,sticky='w')
        self.copy_log_button=button(row,'복사',self.copy_logs,width=49,height=27,font=font(10),fg_color='transparent');self.copy_log_button.grid(row=0,column=2)
        self.logbox=ctk.CTkTextbox(logs,height=112,fg_color=INSET,text_color=MUTED,font=font(11),wrap='word',scrollbar_button_color=LINE)
        self.logbox.insert('end','첫 수령을 시작하면 진행 상황이 표시됩니다.');self.logbox.configure(state='disabled')

        footer=ctk.CTkFrame(main,fg_color='transparent');self.footer=footer
        footer.grid(row=4,column=0,sticky='ew');footer.grid_columnconfigure(0,weight=1)
        self.run_target=label(footer,'실행 대상을 선택해 주세요.',size=11,bold=True,anchor='w')
        self.run_target.grid(row=0,column=0,sticky='w',pady=(0,3))
        self.shortcut_hint=label(footer,'중지 키: '+self.stop_hotkey.value,size=9,color=MUTED,anchor='w')
        self.shortcut_hint.grid(row=1,column=0,sticky='w')
        self.once_button=button(footer,'한 번 수령',lambda:self.launch('once'),width=95);self.once_button.grid(row=0,column=1,rowspan=2,padx=(8,7));self.controls.append(self.once_button)
        self.start_button=button(footer,'자동 수령 시작',lambda:self.launch('repeat'),primary=True,width=130);self.start_button.grid(row=0,column=2,rowspan=2,padx=(0,7));self.controls.append(self.start_button)
        self.pause_button=button(footer,'일시중지',self.toggle_pause,width=85,state='disabled');self.pause_button.grid(row=0,column=3,rowspan=2,padx=(0,7))
        self.stop_button=button(footer,'중지',self.stop_run,width=65,state='disabled',fg_color='#35232B',hover_color='#4A3038',text_color=RED);self.stop_button.grid(row=0,column=4,rowspan=2)
        self.status_label=label(main,textvariable=self.status,size=10,color=MUTED,anchor='w',wraplength=820,justify='left')
        self.status_label.grid(row=5,column=0,sticky='ew',pady=(9,0))
        self.render_roster(force=True)

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
        w=max(30,self.preview_frame.winfo_width()-10);h=max(30,self.preview_frame.winfo_height()-10)
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
