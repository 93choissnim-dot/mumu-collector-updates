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
from ui_layout import fit_window


class Dashboard:
    def build(self):
        install_theme()
        self.root.title('창키 도우미 '+VERSION)
        if os.name=='nt':self.root.iconbitmap(str(Path(__file__).parent/'assets/chanki.ico'))
        fit_window(self.root)
        self.compact_layout=False;self.compact_details=False;self.short_layout=False;self._layout_signature=None;self._layout_after=None
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

        banner=ctk.CTkFrame(self.root,fg_color=HEADER,height=54,corner_radius=0)
        banner.grid(row=0,column=0,columnspan=2,sticky='ew');banner.grid_propagate(False)
        label(banner,'',image=icon('brand',color=CREAM,size=32)).pack(side='left',padx=(17,9),pady=6)
        heading(banner,'창키 도우미',size=21,color=CREAM).pack(side='left')
        self.brand_subtitle=label(banner,'창세기전 키우기  ·  수령 도우미',size=11,color='#CEDCD3');self.brand_subtitle.pack(side='left',padx=15)
        label(banner,'v'+VERSION,size=10,color='#CEDCD3').pack(side='right',padx=18)
        ctk.CTkFrame(banner,height=1,fg_color='#A38D5C',corner_radius=0).place(relx=0,rely=1,anchor='sw',relwidth=1)

        side=PaperFrame(self.root,width=162,corner_radius=0,fg_color=SIDE);self.sidebar=side;self.nav_buttons=[]
        side.grid(row=1,column=0,sticky='nsew');side.grid_propagate(False)
        side.grid_columnconfigure(0,weight=1);side.grid_rowconfigure(3,weight=1)
        self.list_button=button(side,'수령 현황',self.show_roster,width=138,height=45,anchor='w',
            image=icon('list',color=CREAM,size=21),fg_color=HEADER,hover_color=ACCENT_HOVER,text_color=CREAM)
        self.list_button.grid(row=0,column=0,padx=12,pady=(26,9))
        self.fleet_button=button(side,'작업 설정',self.fleet_dialog,width=138,height=43,anchor='w',
            image=icon('settings',color=MUTED,size=22),fg_color='transparent')
        self.fleet_button.grid(row=1,column=0,padx=12,pady=3)
        self.nav_buttons.extend([self.list_button,self.fleet_button])
        self.side_note=label(side,'작업 설정은 뮤뮤별로\n저장됩니다.',size=10,color=MUTED,justify='left');self.side_note.grid(row=2,column=0,sticky='w',padx=20,pady=(13,0))
        for row,(text,command,kind) in enumerate([('사용 가이드',self.guide_dialog,'guide'),('진단 파일 저장',self.export_diagnostics,'screen')],4):
            nav=button(side,text,command,width=140,height=32,anchor='w',image=icon(kind,color=MUTED,size=19),
                   fg_color='transparent',text_color=MUTED,font=font(11));nav.grid(row=row,column=0,padx=11,pady=2);self.nav_buttons.append(nav)
        self.update_button=button(side,'업데이트',self.updates_dialog,width=140,height=32,anchor='w',
            image=icon('update',color=MUTED,size=19),fg_color='transparent',text_color=MUTED,font=font(11))
        self.update_button.grid(row=6,column=0,padx=11,pady=2)
        self.nav_buttons.append(self.update_button)
        self.side_brand=label(side,'CHANKI HELPER',size=10,color=GOLD);self.side_brand.grid(row=7,column=0,pady=(14,18))

        main=ctk.CTkFrame(self.root,fg_color='transparent');self.main_panel=main
        main.grid(row=1,column=1,sticky='nsew',padx=20,pady=(14,10))
        main.grid_columnconfigure(0,weight=1);main.grid_rowconfigure(3,weight=1)
        header=ctk.CTkFrame(main,fg_color='transparent');header.grid(row=0,column=0,sticky='ew',pady=(0,9))
        header.grid_columnconfigure(0,weight=1)
        heading(header,'수령 현황',size=26).grid(row=0,column=0,sticky='w')
        self.header_note=label(header,'오늘의 작업과 다음 수령을 한눈에 확인하세요.',size=11,color=MUTED);self.header_note.grid(row=1,column=0,sticky='w')
        self.layout_button=button(header,'상세 보기',self.toggle_compact_details,width=85,height=32,font=font(11))
        self.connect_button=button(header,'뮤뮤 연결',self.connect,primary=True,width=112,height=38)
        self.connect_button.grid(row=0,column=2,rowspan=2,sticky='e');self.controls.append(self.connect_button)
        metrics=panel(main,height=54);self.metrics_panel=metrics;metrics.grid(row=1,column=0,sticky='ew',pady=(0,10));metrics.grid_propagate(False)
        metrics.grid_columnconfigure((0,1,2),weight=1,uniform='metrics');metrics.grid_rowconfigure(0,weight=1)
        self.metric_values=[]
        for i,title in enumerate(['연결된 뮤뮤','실행 대상','확인 필요']):
            box=ctk.CTkFrame(metrics,fg_color='transparent');box.grid(row=0,column=i,padx=12,pady=8)
            label(box,title,size=12,color=MUTED).pack(side='left',padx=(0,10))
            value=label(box,'0개',size=22,bold=True,color=ACCENT if i<2 else GOLD)
            value.pack(side='left');self.metric_values.append(value)
        self.issue_metric=self.metric_values[2]
        for x in (1/3,2/3):ctk.CTkFrame(metrics,width=1,height=21,fg_color=RULE,corner_radius=0).place(relx=x,rely=.5,anchor='center')

        tools=ctk.CTkFrame(main,fg_color='transparent');tools.grid(row=2,column=0,sticky='ew',pady=(0,9));tools.grid_columnconfigure(1,weight=1)
        label(tools,'이름 검색',size=11,color=MUTED).grid(row=0,column=0,padx=(0,8))
        self.search_entry=ctk.CTkEntry(tools,textvariable=self.roster_query,width=150,height=36,font=font(12),fg_color=PANEL,border_color=RULE)
        self.search_entry.grid(row=0,column=1,sticky='ew',padx=(0,10))
        self.filter_menu=GameTabs(tools,['전체','실행 대상','확인 필요'],variable=self.roster_filter,width=254,height=32,command=lambda _:self.render_roster(force=True))
        self.filter_menu.grid(row=0,column=2)
        self.roster_query.trace_add('write',lambda *_:self.render_roster(force=True))

        body=ctk.CTkFrame(main,fg_color='transparent');self.workspace_body=body;body.grid(row=3,column=0,sticky='nsew')
        body.grid_columnconfigure(0,weight=0,minsize=320);body.grid_columnconfigure(1,weight=1,minsize=360);body.grid_rowconfigure(0,weight=1)
        roster=panel(body,width=320);self.roster_panel=roster
        roster.grid(row=0,column=0,sticky='nsew',padx=(0,14));roster.grid_propagate(False)
        roster.grid_columnconfigure(0,weight=1);roster.grid_rowconfigure(1,weight=1)
        columns=ctk.CTkFrame(roster,fg_color='transparent');columns.grid(row=0,column=0,sticky='ew',padx=18,pady=(16,8));columns.grid_columnconfigure(0,weight=1)
        label(columns,'뮤뮤 플레이어',size=13,bold=True,anchor='w').grid(row=0,column=0,sticky='w')
        self.roster_total=label(columns,'0개',size=11,color=MUTED);self.roster_total.grid(row=0,column=1,sticky='e')
        self.roster_body=ctk.CTkScrollableFrame(roster,fg_color='transparent',corner_radius=0,scrollbar_button_color=LINE)
        self.roster_body.grid(row=1,column=0,sticky='nsew',padx=9,pady=(0,4));self.roster_body.grid_columnconfigure(0,weight=1)
        label(roster,'체크한 뮤뮤만 순서대로 실행합니다.',size=10,color=MUTED).grid(row=2,column=0,sticky='w',padx=18,pady=(8,14))

        detail=panel(body,width=360);self.detail_panel=detail
        detail.grid(row=0,column=1,sticky='nsew');detail.grid_columnconfigure(0,weight=1);detail.grid_rowconfigure(4,weight=1)
        self.detail_name=heading(detail,'뮤뮤를 선택하세요',size=21,anchor='w')
        self.detail_name.grid(row=0,column=0,sticky='w',padx=20,pady=(16,0))
        self.connection_badge=label(detail,textvariable=self.connection_text,size=11,color=MUTED,anchor='w',height=18)
        self.connection_badge.grid(row=1,column=0,sticky='w',padx=21,pady=(1,12))
        summary=ctk.CTkFrame(detail,fg_color=INSET,corner_radius=8);self.detail_summary_panel=summary
        summary.grid(row=2,column=0,sticky='ew',padx=18,pady=(0,14))
        summary.grid_columnconfigure((0,1,2),weight=1,uniform='detail-summary')
        self.detail_summary=[]
        for col,title in enumerate(['현재 상태','다음 수령','수령 간격']):
            box=ctk.CTkFrame(summary,fg_color='transparent');box.grid(row=0,column=col,sticky='ew',padx=10,pady=10)
            label(box,title,size=10,color=MUTED).pack(side='left',padx=(0,7))
            value=label(box,'—',size=13,bold=True);value.pack(side='left');self.detail_summary.append(value)
        self.detail_tabs=GameTabs(detail,['수령 결과','최근 화면'],width=268,height=32,command=self.show_detail_tab)
        self.detail_tabs.grid(row=3,column=0,sticky='ew',padx=18,pady=(0,10));self.detail_tabs.set('수령 결과')
        self.detail_content=ctk.CTkFrame(detail,fg_color='transparent')
        self.detail_content.grid(row=4,column=0,sticky='nsew',padx=12)
        self.detail_content.grid_columnconfigure(0,weight=1);self.detail_content.grid_rowconfigure(0,weight=1)
        self.preview_frame=ctk.CTkFrame(self.detail_content,fg_color=INSET,corner_radius=8,height=150)
        self.preview_frame.grid(row=0,column=0,sticky='nsew',padx=6);self.preview_frame.grid_propagate(False)
        self.preview_placeholder=icon('screen',color=MUTED,size=30)
        self.preview_label=label(self.preview_frame,'화면 확인을 누르면\n최근 화면을 볼 수 있습니다.',size=12,color=MUTED,image=self.preview_placeholder,compound='top',width=0,height=0,padx=0,pady=0)
        self.preview_label.place(relx=.5,rely=.5,anchor='center',relwidth=1,relheight=1);self.preview_label.bind('<Button-1>',lambda _:self.preview())
        self.preview_frame.bind('<Configure>',lambda _:self.render_thumbnail())
        self.preview_stamp=label(detail,'최근 캡처 / 클릭하면 확대',size=10,color=MUTED,height=18)
        self.preview_stamp.grid(row=5,column=0,sticky='w',padx=20,pady=(8,0))
        self.detail_tasks=ctk.CTkScrollableFrame(self.detail_content,fg_color='transparent',corner_radius=0,scrollbar_button_color=LINE)
        tasks=self.detail_tasks;tasks.grid(row=0,column=0,sticky='nsew')
        self.detail_results={};self.detail_task_rows={};self.show_disabled_tasks=False;self._task_layout=None
        for key,title in TASK_LABELS.items():
            row=ctk.CTkFrame(tasks,fg_color=INSET,corner_radius=8);row.grid_columnconfigure(1,weight=1)
            label(row,'',image=icon(key,color=ACCENT,size=23),width=28,height=30).grid(row=0,column=0,rowspan=2,padx=(10,8),pady=4)
            label(row,title,size=12,color=TEXT,height=17,anchor='w').grid(row=0,column=1,sticky='w',pady=(4,0),padx=(0,7))
            result=label(row,'기록 없음',size=11,color=MUTED,height=17,anchor='w')
            result.grid(row=1,column=1,sticky='w',pady=(0,4),padx=(0,7))
            self.detail_results[key]=result;self.detail_task_rows[key]=row
        self.detail_content.bind('<Configure>',lambda _:self.layout_task_cards())
        self.detail_checked=label(detail,'설정과 기록은 뮤뮤별로 유지됩니다.',size=10,color=MUTED,height=18)
        # Latest successful collection is shown in detail_stats below.
        self.detail_stats=label(detail,'',size=11,color=MUTED,height=18,anchor='w',wraplength=340)
        self.detail_stats.grid(row=6,column=0,sticky='w',padx=20,pady=(8,0))
        actions=ctk.CTkFrame(detail,fg_color='transparent');self.detail_actions=actions;actions.grid(row=7,column=0,sticky='ew',padx=18,pady=(10,16));actions.grid_columnconfigure(1,weight=1)
        self.history_button=button(actions,'수령 기록',self.history_dialog,width=80,height=32,font=font(11));self.history_button.grid(row=0,column=0,sticky='w')
        self.disabled_tasks_button=button(actions,'',self.toggle_disabled_tasks,width=110,height=32,font=font(10),fg_color='transparent',text_color=MUTED)
        self.disabled_tasks_button.grid(row=0,column=1,padx=4,sticky='w')
        self.inspect_button=button(actions,'화면 확인',self.inspect_selected,width=84,height=32,font=font(11))
        self.inspect_button.grid(row=0,column=2,sticky='e');self.controls.append(self.inspect_button)
        self.show_detail_tab('수령 결과')

        logs=panel(main,border_width=0,fg_color=INSET);self.log_panel=logs
        logs.grid(row=4,column=0,sticky='ew',pady=(9,0));logs.grid_columnconfigure(0,weight=1)
        row=ctk.CTkFrame(logs,fg_color='transparent');row.grid(row=0,column=0,sticky='ew',padx=10,pady=4);row.grid_columnconfigure(1,weight=1)
        self.log_toggle=button(row,'실행 기록 펼치기',self.toggle_logs,width=119,height=27,font=font(11),fg_color='transparent')
        self.log_toggle.grid(row=0,column=0,padx=(0,9))
        self.log_summary=label(row,'실행 기록이 여기에 표시됩니다.',size=10,color=MUTED,anchor='w')
        self.log_summary.grid(row=0,column=1,sticky='w')
        self.copy_log_button=button(row,'복사',self.copy_logs,width=49,height=27,font=font(10),fg_color='transparent');self.copy_log_button.grid(row=0,column=2)
        self.logbox=ctk.CTkTextbox(logs,height=90,fg_color=INSET,text_color=TEXT,font=font(11),wrap='word',scrollbar_button_color=LINE)
        self.logbox.insert('end','첫 수령을 시작하면 진행 상황이 표시됩니다.');self.logbox.configure(state='disabled')

        footer_outer=panel(self.root,fg_color=PANEL,corner_radius=0);footer_outer.grid(row=2,column=0,columnspan=2,sticky='ew')
        footer=ctk.CTkFrame(footer_outer,fg_color='transparent');self.footer=footer
        footer.pack(fill='x',padx=18,pady=(10,8));footer.grid_columnconfigure(0,weight=1)
        info=ctk.CTkFrame(footer,fg_color='transparent');self.run_info=info;info.grid(row=0,column=0,rowspan=2,sticky='w')
        self.run_target=label(info,'실행 대상을 선택해 주세요.',size=12,bold=True,anchor='w')
        self.run_target.grid(row=0,column=0,sticky='w',pady=(0,3))
        label(info,'완료',size=10,color=MUTED).grid(row=0,column=1,padx=(16,4))
        self.count_label=label(info,'0건',size=11,color=MINT,bold=True);self.count_label.grid(row=0,column=2)
        self.shortcut_hint=label(info,'중지 키: '+self.stop_hotkey.value,size=10,color=MUTED,anchor='w')
        self.shortcut_hint.grid(row=1,column=0,columnspan=3,sticky='w')
        self.once_button=button(footer,'한 번 수령',lambda:self.launch('once'),width=100,height=42);self.once_button.grid(row=0,column=1,rowspan=2,padx=(8,6));self.controls.append(self.once_button)
        self.start_button=button(footer,'자동 수령 시작',lambda:self.launch('repeat'),primary=True,width=143,height=42);self.start_button.grid(row=0,column=2,rowspan=2,padx=(0,6));self.controls.append(self.start_button)
        self.pause_button=button(footer,'일시중지',self.toggle_pause,width=88,state='disabled');self.pause_button.grid(row=0,column=3,rowspan=2,padx=(0,6))
        self.stop_button=button(footer,'중지',self.stop_run,width=70,state='disabled',text_color=RED,fg_color='#F7EEEB',hover_color='#F0DDD7');self.stop_button.grid(row=0,column=4,rowspan=2)
        self.status_label=label(footer,textvariable=self.status,size=10,color=MUTED,anchor='w',wraplength=820,justify='left')
        self.status_label.grid(row=2,column=0,columnspan=5,sticky='ew',pady=(4,0))
        self.render_roster(force=True)
        self.root.bind('<Configure>',self.schedule_layout,add='+')
        self.root.after_idle(self.apply_layout)

    def schedule_layout(self,event):
        if event.widget is not self.root or self.closing:return
        if self._layout_after is not None:self.root.after_cancel(self._layout_after)
        self._layout_after=self.root.after(30,self.apply_layout)

    def apply_layout(self):
        self._layout_after=None
        if self.closing or self.root.winfo_width()<100:return
        scale=self.root._get_window_scaling();width=self.root.winfo_width()/scale;height=self.root.winfo_height()/scale
        compact=width<960;short=height<700;micro=height<520
        signature=(compact,short,micro,self.compact_details,scale,self.root._get_widget_scaling())
        if signature==self._layout_signature:return
        self._layout_signature=signature;self.compact_layout=compact;self.short_layout=short
        self.sidebar.configure(width=132 if compact else 162)
        for nav in self.nav_buttons:nav.configure(width=108 if compact else 138)
        if compact:
            self.brand_subtitle.pack_forget()
            self.layout_button.configure(text='목록 보기' if self.compact_details else '상세 보기')
            self.layout_button.grid(row=0,column=1,rowspan=2,padx=(6,8))
            self.workspace_body.grid_columnconfigure(0,weight=1,minsize=0)
            self.workspace_body.grid_columnconfigure(1,weight=0,minsize=0)
            if self.compact_details:
                self.roster_panel.grid_remove();self.detail_panel.grid(row=0,column=0,columnspan=2,sticky='nsew')
            else:
                self.detail_panel.grid_remove();self.roster_panel.grid(row=0,column=0,columnspan=2,sticky='nsew',padx=0)
            self.run_info.grid(row=0,column=0,columnspan=5,rowspan=1,sticky='w',pady=(0,6))
            self.shortcut_hint.grid(row=0,column=3,columnspan=1,padx=(16,0))
            for col,control in enumerate([self.once_button,self.start_button,self.pause_button,self.stop_button],1):
                control.grid(row=1,column=col,rowspan=1)
        else:
            self.brand_subtitle.pack(side='left',padx=15);self.layout_button.grid_remove()
            self.workspace_body.grid_columnconfigure(0,weight=0,minsize=320)
            self.workspace_body.grid_columnconfigure(1,weight=1,minsize=360)
            self.roster_panel.grid(row=0,column=0,columnspan=1,sticky='nsew',padx=(0,14))
            self.detail_panel.grid(row=0,column=1,columnspan=1,sticky='nsew')
            self.run_info.grid(row=0,column=0,columnspan=1,rowspan=2,sticky='w',pady=0)
            self.shortcut_hint.grid(row=1,column=0,columnspan=3,padx=0)
            for col,control in enumerate([self.once_button,self.start_button,self.pause_button,self.stop_button],1):
                control.grid(row=0,column=col,rowspan=2)
        if short:
            self.detail_summary_panel.grid_remove();self.detail_stats.grid_remove()
            self.detail_checked.grid_remove();self.preview_stamp.grid_remove()
        else:
            self.detail_summary_panel.grid()
            if self.detail_tabs.get()=='수령 결과':self.detail_stats.grid()
            else:self.preview_stamp.grid()
        self.main_panel.grid_configure(pady=(6,6) if micro else (14,10))
        if micro:
            self.connection_badge.grid_remove()
            self.detail_name.grid_configure(pady=(5,0))
            self.detail_tabs.grid_configure(pady=(0,4))
            self.detail_actions.grid_configure(pady=(4,6))
        else:
            self.connection_badge.grid()
            self.detail_name.grid_configure(pady=(16,0))
            self.detail_tabs.grid_configure(pady=(0,10))
            self.detail_actions.grid_configure(pady=(10,16))
        if short:
            self.metrics_panel.grid_remove();self.header_note.grid_remove();self.side_note.grid_remove();self.side_brand.grid_remove()
            self.list_button.grid_configure(pady=(10,3));self.fleet_button.grid_configure(pady=2)
        else:
            self.metrics_panel.grid();self.header_note.grid();self.side_note.grid();self.side_brand.grid()
            self.list_button.grid_configure(pady=(26,9));self.fleet_button.grid_configure(pady=3)
        self.show_detail_tab(self.detail_tabs.get())

    def toggle_compact_details(self):
        self.compact_details=not self.compact_details;self.apply_layout()

    def show_detail_tab(self,value):
        preview=value=='최근 화면'
        self.detail_tabs.set(value)
        if preview:
            self.detail_tasks.grid_remove();self.detail_checked.grid_remove()
            self.preview_frame.grid();self.preview_stamp.grid();self.detail_stats.grid_remove();self.disabled_tasks_button.grid_remove();self.render_thumbnail()
        else:
            self.preview_frame.grid_remove();self.preview_stamp.grid_remove()
            self.detail_tasks.grid();self.disabled_tasks_button.grid();self.layout_task_cards()
            if not self.short_layout:self.detail_stats.grid()
        if self.short_layout:self.detail_checked.grid_remove();self.preview_stamp.grid_remove()

    def toggle_disabled_tasks(self):
        self.show_disabled_tasks=not self.show_disabled_tasks
        self.layout_task_cards()

    def layout_task_cards(self):
        from ui_state import selected_tasks
        if not hasattr(self,'detail_task_rows'):return
        selected=set(selected_tasks(self.players.get(self.view_id,{}))) if self.view_id in self.players else set()
        visible=[key for key in TASK_LABELS if key in selected or self.show_disabled_tasks]
        # Two columns fit even the compact desktop detail pane. On narrow
        # windows use one column rather than squeezing task names and results.
        width=self.detail_content.winfo_width()/self.detail_content._get_widget_scaling()
        columns=2 if width>=340 else 1
        signature=(tuple(visible),columns)
        if signature!=self._task_layout:
            self._task_layout=signature
            for row in self.detail_task_rows.values():row.grid_forget()
            for col in (0,1):self.detail_tasks.grid_columnconfigure(col,weight=1 if col<columns else 0,uniform='task-cards' if col<columns else '',minsize=0)
            for i,key in enumerate(visible):
                self.detail_task_rows[key].grid(row=i//columns,column=i%columns,sticky='ew',padx=3,pady=2)
        disabled=len(TASK_LABELS)-len(selected)
        self.disabled_tasks_button.configure(text='사용 안 함 접기' if self.show_disabled_tasks else f'사용 안 함 {disabled}개',state='normal' if disabled else 'disabled')

    def inspect_selected(self):
        self.show_detail_tab('최근 화면');self.launch('inspect')

    def show_roster(self):
        self.compact_details=False;self.apply_layout()
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
        w=max(1,int(self.preview_frame.winfo_width()/scale)-4)
        h=max(1,int(self.preview_frame.winfo_height()/scale)-4)
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
        for title,text in [('01  뮤뮤 연결','게임을 실행하고 뮤뮤 연결을 누릅니다. 목록의 이름을 누르면 해당 화면과 기록을 볼 수 있습니다.'),('02  뮤뮤별 작업 설정','각 뮤뮤의 설정에서 수령할 작업과 간격을 선택합니다. 수련은 재료를 사용하는 작업입니다.'),('03  실행과 제어','체크된 뮤뮤만 순서대로 실행합니다. 한 번 수령은 한 차례, 자동 수령은 설정한 간격으로 반복합니다.'),('04  중지와 일시중지','일시중지 후 재시작하면 이어서 진행합니다. 중지는 실행을 종료합니다. 중지 키는 작업 설정에서 바꿉니다.')]:
            label(win,title,size=13,bold=True).pack(anchor='w',padx=25,pady=(9,3))
            label(win,text,size=11,color=MUTED,wraplength=490,justify='left').pack(anchor='w',padx=25)
