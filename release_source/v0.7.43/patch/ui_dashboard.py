"""A multi-player workspace with a stable run bar and selected-player details."""
import os
from pathlib import Path
import tkinter as tk
import customtkinter as ctk
import cv2
from PIL import Image
from ui_theme import (BG,SIDE,PANEL,INSET,LINE,RULE,TEXT,MUTED,GOLD,MINT,RED,ACCENT,ACCENT_HOVER,CREAM,HEADER,HOVER,SELECTED,font,label,heading,button,panel,icon,install_theme,PaperFrame,GameTabs,GamePanel)
from vision import LABELS
from task_catalog import TASK_LABELS,REGULAR_LABELS,DAILY_LABELS
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
        self.root.grid_columnconfigure(0,weight=1);self.root.grid_rowconfigure(1,weight=1)
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

        self._built=False;self.roster_collapsed=False;self.display_task_order=[]
        self.toolbar=ctk.CTkFrame(self.root,fg_color=HEADER,corner_radius=0,border_width=1,border_color=GOLD)
        self.toolbar.grid(row=0,column=0,sticky='ew');self.toolbar.grid_columnconfigure(0,weight=1)
        identity=ctk.CTkFrame(self.toolbar,fg_color='transparent')
        identity.grid(row=0,column=0,sticky='ew',padx=(24,10),pady=(10,10));identity.grid_columnconfigure(1,weight=1)
        label(identity,'',image=icon('brand',color='#C9A660',size=46),width=50).grid(row=0,column=0,rowspan=2,padx=(0,12))
        heading(identity,'창키 도우미',size=27,color=CREAM,anchor='w').grid(row=0,column=1,sticky='w')
        identity.grid_columnconfigure(2,weight=1)
        self.detail_name=label(identity,'뮤뮤를 연결하세요',size=12,color=MUTED,anchor='w')
        self.detail_name.grid(row=1,column=1,sticky='w')
        self.connection_badge=label(identity,textvariable=self.connection_text,size=11,color='#CDBD9D',anchor='w')
        self.connection_badge.grid(row=1,column=2,sticky='w',padx=(12,0))
        actions=ctk.CTkFrame(self.toolbar,fg_color='transparent');actions.grid(row=0,column=1,padx=(0,20))
        self.fleet_button=button(actions,'작업 설정',self.fleet_dialog,width=88,height=36,font=font(12))
        self.fleet_button.pack(side='left',padx=3)
        self.connect_button=button(actions,'뮤뮤 연결',self.connect,width=96,height=36,font=font(12))
        self.connect_button.pack(side='left',padx=3);self.controls.append(self.connect_button)
        self.update_button=button(actions,'업데이트',self.updates_dialog,width=80,height=36,font=font(11),fg_color='transparent')
        self.update_button.configure(text_color=CREAM,hover_color=ACCENT)
        self.update_button.pack(side='left',padx=3)
        self.more_button=button(actions,'더보기',self.open_more,width=64,height=36,font=font(11),fg_color='transparent')
        self.more_button.configure(text_color=CREAM,hover_color=ACCENT)
        self.more_button.pack(side='left',padx=3)
        self.more_menu=tk.Menu(self.root,tearoff=False,bg=PANEL,fg=TEXT,activebackground=HOVER,activeforeground=CREAM,bd=0)
        self.more_menu.add_command(label='사용 가이드',command=self.guide_dialog)
        self.more_menu.add_command(label='진단 파일 저장',command=self.export_diagnostics)

        main=ctk.CTkFrame(self.root,fg_color='transparent');self.main_panel=main
        main.grid(row=1,column=0,sticky='nsew',padx=24,pady=16);main.grid_columnconfigure(0,weight=1);main.grid_rowconfigure(1,weight=1)
        self.fleet_bar=ctk.CTkFrame(main,fg_color='transparent');self.fleet_bar.grid_columnconfigure(1,weight=1)
        self.layout_button=button(self.fleet_bar,'목록 접기',self.toggle_compact_details,width=112,height=32,font=font(12))
        self.layout_button.grid(row=0,column=0,padx=(0,14))
        self.fleet_overview=label(self.fleet_bar,'',size=12,color=MUTED,anchor='w')
        self.fleet_overview.grid(row=0,column=1,sticky='w')
        body=ctk.CTkFrame(main,fg_color='transparent');self.workspace_body=body
        body.grid(row=1,column=0,sticky='nsew');body.grid_columnconfigure(1,weight=1);body.grid_rowconfigure(0,weight=1)
        roster=panel(body,width=300);self.roster_panel=roster;roster.grid_propagate(False)
        roster.grid_columnconfigure(0,weight=1);roster.grid_rowconfigure(2,weight=1)
        roster_head=ctk.CTkFrame(roster,fg_color='transparent');roster_head.grid(row=0,column=0,sticky='ew',padx=15,pady=(14,8));roster_head.grid_columnconfigure(0,weight=1)
        label(roster_head,'뮤뮤 목록',size=14,bold=True).grid(row=0,column=0,sticky='w')
        self.roster_total=label(roster_head,'',size=11,color=MUTED);self.roster_total.grid(row=0,column=1)
        tools=ctk.CTkFrame(roster,fg_color='transparent');tools.grid(row=1,column=0,sticky='ew',padx=12,pady=(0,10));tools.grid_columnconfigure(0,weight=1)
        self.search_entry=ctk.CTkEntry(tools,textvariable=self.roster_query,placeholder_text='뮤뮤 이름 검색',height=34,font=font(12),fg_color=INSET,border_color=RULE)
        label(tools,'뮤뮤 이름 검색',size=10,color=MUTED,anchor='w').grid(row=0,column=0,sticky='w',pady=(0,4))
        self.search_entry.grid(row=1,column=0,sticky='ew',pady=(0,8))
        self.filter_menu=GameTabs(tools,['전체','실행 대상','확인 필요'],variable=self.roster_filter,width=252,height=30,command=lambda _:self.render_roster(force=True))
        self.filter_menu.grid(row=2,column=0,sticky='ew')
        self.roster_query.trace_add('write',lambda *_:self.render_roster(force=True))
        self.roster_body=ctk.CTkScrollableFrame(roster,fg_color='transparent',corner_radius=0,scrollbar_button_color=LINE)
        self.roster_body.grid(row=2,column=0,sticky='nsew',padx=7,pady=(0,8));self.roster_body.grid_columnconfigure(0,weight=1)
        label(roster,'체크한 뮤뮤만 실행합니다.',size=10,color=MUTED).grid(row=3,column=0,sticky='w',padx=16,pady=(2,12))

        detail=panel(body,ornament=True);self.detail_panel=detail;detail.grid_columnconfigure(0,weight=1);detail.grid_rowconfigure(2,weight=1)
        summary=ctk.CTkFrame(detail,fg_color='transparent');self.detail_summary_panel=summary
        summary.grid(row=0,column=0,sticky='ew',padx=22,pady=(18,16));summary.grid_columnconfigure((0,1,2),weight=1,uniform='summary')
        self.detail_summary=[];self.summary_titles=[]
        for col,title in enumerate(['현재 상태','다음 수령','수령 간격']):
            box=ctk.CTkFrame(summary,fg_color='transparent');box.grid(row=0,column=col,sticky='ew',padx=(0,12))
            title_label=label(box,title,size=11,color=MUTED);title_label.pack(anchor='w');self.summary_titles.append(title_label)
            value=(button(box,'—',self.open_status_history,width=145,height=29,font=font(21,True),anchor='w',border_spacing=0,fg_color='transparent') if col==0 else label(box,'—',size=21,bold=True))
            value.pack(anchor='w',pady=(3,0));self.detail_summary.append(value)
        section=ctk.CTkFrame(detail,fg_color='transparent');self.task_toolbar=section
        section.grid(row=1,column=0,sticky='ew',padx=20,pady=(0,10));section.grid_columnconfigure(0,weight=1)
        self.detail_tabs=GameTabs(section,['수령 결과','최근 화면','실행 기록'],width=306,height=34,command=self.show_detail_tab)
        self.detail_tabs.grid(row=0,column=0,sticky='w')
        self.detail_enabled_value=tk.BooleanVar(value=False)
        self.detail_enabled=ctk.CTkCheckBox(section,text='실행 대상',variable=self.detail_enabled_value,command=self.toggle_detail_enabled,font=font(11),width=104,checkbox_width=18,checkbox_height=18)
        self.detail_enabled.grid(row=0,column=1,padx=(12,0))
        self.detail_content=ctk.CTkFrame(detail,fg_color='transparent');self.detail_content.grid(row=2,column=0,sticky='nsew',padx=14)
        self.detail_content.grid_columnconfigure(0,weight=1);self.detail_content.grid_rowconfigure(0,weight=1)
        self.detail_tasks=ctk.CTkScrollableFrame(self.detail_content,fg_color='transparent',corner_radius=0,scrollbar_button_color=LINE)
        self.detail_tasks.grid_columnconfigure(0,weight=1)
        self.detail_content.bind('<Configure>',lambda _:self.layout_task_cards())
        self.detail_results={};self.detail_task_rows={};self.detail_times={};self.show_disabled_tasks=False;self._task_layout=None
        for row_index,(key,title) in enumerate(TASK_LABELS.items()):
            row=GamePanel(self.detail_tasks,fg_color=PANEL,corner_radius=0,ornament=True,art_index=row_index);row.grid_columnconfigure(1,weight=1)
            label(row,'',image=icon(key,color=GOLD,size=30),width=34,height=32).grid(row=0,column=0,padx=(12,9),pady=5)
            label(row,title,size=13,bold=True,anchor='w').grid(row=0,column=1,sticky='w',padx=(0,10))
            result=button(row,'기록 없음',lambda task=key:self.history_dialog(self.view_id,task_filter=task),font=font(12),text_color=MUTED,width=112,height=28,anchor='w',border_spacing=0,fg_color='transparent');result.grid(row=0,column=2,sticky='w',padx=(4,12))
            stamp=label(row,'',size=11,color=MUTED,width=112,anchor='e');stamp.grid(row=0,column=3,sticky='e',padx=(0,12))
            self.detail_results[key]=result;self.detail_task_rows[key]=row;self.detail_times[key]=stamp
        self.tasks_empty=label(self.detail_tasks,'작업 설정에서 수령할 작업을 선택해 주세요.',size=13,color=MUTED,wraplength=340)
        self.preview_frame=ctk.CTkFrame(self.detail_content,fg_color=INSET,corner_radius=8)
        self.preview_frame.grid_propagate(False);self.preview_placeholder=icon('screen',color=MUTED,size=30)
        self.preview_label=label(self.preview_frame,'화면 확인을 누르면 최근 화면을 볼 수 있습니다.',size=12,color=MUTED,image=self.preview_placeholder,compound='top',width=0,height=0)
        self.preview_label.place(relx=.5,rely=.5,anchor='center',relwidth=1,relheight=1);self.preview_label.bind('<Button-1>',lambda _:self.preview())
        self.preview_frame.bind('<Configure>',lambda _:self.render_thumbnail())
        self.log_panel=ctk.CTkFrame(self.detail_content,fg_color='transparent');self.log_panel.grid_columnconfigure(0,weight=1);self.log_panel.grid_rowconfigure(1,weight=1)
        self.log_summary=label(self.log_panel,'실행 기록이 여기에 표시됩니다.',size=11,color=MUTED,anchor='w')
        self.log_summary.grid(row=0,column=0,sticky='ew',padx=8,pady=(0,8))
        self.copy_log_button=button(self.log_panel,'복사',self.copy_logs,width=64,height=30,font=font(11));self.copy_log_button.grid(row=0,column=1,padx=8,pady=(0,8))
        self.logbox=ctk.CTkTextbox(self.log_panel,fg_color=INSET,text_color=TEXT,font=font(12),wrap='word',scrollbar_button_color=LINE)
        self.logbox.grid(row=1,column=0,columnspan=2,sticky='nsew');self.logbox.insert('end','첫 수령을 시작하면 진행 상황이 표시됩니다.');self.logbox.configure(state='disabled')
        self.preview_stamp=label(detail,'최근 캡처 / 클릭하면 확대',size=10,color=MUTED)
        self.detail_checked=label(detail,'',size=10,color=MUTED)
        self.detail_stats=label(detail,'',size=11,color=MUTED,anchor='w')
        self.detail_stats.grid(row=3,column=0,sticky='w',padx=22,pady=(8,0))
        actions=ctk.CTkFrame(detail,fg_color='transparent');self.detail_actions=actions
        actions.grid(row=4,column=0,sticky='ew',padx=20,pady=(10,16));actions.grid_columnconfigure(1,weight=1)
        self.history_button=button(actions,'수령 기록',self.history_dialog,width=86,height=34,font=font(12));self.history_button.grid(row=0,column=0)
        self.disabled_tasks_button=button(actions,'',self.toggle_disabled_tasks,width=130,height=34,font=font(11),fg_color='transparent',text_color=MUTED)
        self.disabled_tasks_button.grid(row=0,column=1,sticky='w',padx=8)
        self.inspect_button=button(actions,'화면 확인',self.inspect_selected,width=90,height=34,font=font(12));self.inspect_button.grid(row=0,column=2);self.controls.append(self.inspect_button)
        self.empty_panel=panel(body)
        empty_message=ctk.CTkFrame(self.empty_panel,fg_color='transparent')
        empty_message.place(relx=.5,rely=.5,anchor='center')
        label(empty_message,'뮤뮤를 연결하면 바로 시작할 수 있어요.',size=23,bold=True,wraplength=500).pack(padx=24,pady=(0,12))
        label(empty_message,'게임을 실행한 뒤 위의 뮤뮤 연결을 눌러 주세요.\n설정과 수령 기록은 뮤뮤별로 유지됩니다.',size=13,color=MUTED,justify='center').pack(padx=24)

        footer_outer=panel(self.root,fg_color=PANEL,corner_radius=0);footer_outer.grid(row=2,column=0,sticky='ew')
        footer=ctk.CTkFrame(footer_outer,fg_color='transparent');self.footer=footer
        footer.pack(fill='x',padx=24,pady=14);footer.grid_columnconfigure(0,weight=1)
        info=ctk.CTkFrame(footer,fg_color='transparent');self.run_info=info;info.grid(row=0,column=0,sticky='w')
        self.run_target=label(info,'실행 대상을 선택해 주세요.',size=13,bold=True);self.run_target.pack(side='left')
        label(info,'  완료 ',size=11,color=MUTED).pack(side='left');self.count_label=label(info,'0건',size=11,color=MINT);self.count_label.pack(side='left')
        self.status_label=label(footer,textvariable=self.status,size=11,color=MUTED,anchor='w',wraplength=700,justify='left')
        self.status_label.grid(row=1,column=0,sticky='w',pady=(3,0))
        self.shortcut_hint=label(footer,'중지 키: '+self.stop_hotkey.value,size=10,color=MUTED,anchor='w')
        self.shortcut_hint.grid(row=2,column=0,sticky='w',pady=(3,0))
        self.once_button=button(footer,'한 번 수령',lambda:self.launch('once'),width=120,height=44)
        self.start_button=button(footer,'자동 수령 시작',lambda:self.launch('repeat'),primary=True,width=158,height=44)
        self.daily_button=button(footer,'일일 퀘스트 수령',lambda:self.launch('daily'),width=156,height=44,border_color=GOLD,border_width=1)
        from ui_roster import tooltip
        self.daily_button._tooltip_text='패스 → 일일 던전 7종 → 길드 순차 실행\n길드 기부는 최대 루비 150 사용\n누를 때마다 현재 게임 상태를 확인합니다.'
        tooltip(self.daily_button)
        self.pause_button=button(footer,'일시중지',self.toggle_pause,width=120,height=44,state='disabled')
        self.stop_button=button(footer,'중지',self.stop_run,width=158,height=44,state='disabled',fg_color='#753E31',hover_color='#92513F',text_color=CREAM)
        self.controls.extend([self.once_button,self.start_button,self.daily_button])
        self._built=True;self.render_roster(force=True)
        self.root.bind('<Configure>',self.schedule_layout,add='+');self.root.after_idle(self.apply_layout)

    def schedule_layout(self,event):
        if event.widget is not self.root or self.closing:return
        if self._layout_after is not None:self.root.after_cancel(self._layout_after)
        self._layout_after=self.root.after(30,self.apply_layout)

    def apply_layout(self):
        self._layout_after=None
        if not getattr(self,'_built',False) or self.closing or self.root.winfo_width()<100:return
        scale=self.root._get_window_scaling();width=self.root.winfo_width()/scale;height=self.root.winfo_height()/scale
        compact=width<900;short=height<580;multi=len(self.players)>1;empty=not self.players;busy=self.busy()
        signature=(compact,short,multi,empty,self.compact_details,self.roster_collapsed,scale,self.main_panel._get_widget_scaling(),busy)
        self.status_label.configure(wraplength=max(180,int(width-80 if compact else width-560)))
        if signature==self._layout_signature:return
        self._layout_signature=signature;self.compact_layout=compact;self.short_layout=short
        self.connection_badge.grid_configure(row=2 if compact else 1,column=1 if compact else 2,padx=0 if compact else (12,0))
        self.toolbar.grid_configure(pady=0)
        self.main_panel.grid_configure(padx=16 if compact else 24,pady=8 if short else 16)
        for widget in (self.roster_panel,self.detail_panel,self.empty_panel):widget.grid_forget()
        self.workspace_body.grid_columnconfigure(0,weight=0,minsize=0)
        self.workspace_body.grid_columnconfigure(1,weight=1,minsize=0)
        if multi:
            self.fleet_bar.grid(row=0,column=0,sticky='ew',pady=(0,10))
            show_list=not self.compact_details if compact else not self.roster_collapsed
            self.layout_button.configure(text=('작업 보기' if show_list else '뮤뮤 목록') if compact else ('목록 접기' if show_list else '뮤뮤 목록'))
            if show_list:
                self.roster_panel.grid(row=0,column=0,columnspan=2 if compact else 1,sticky='nsew',padx=0 if compact else (0,16))
                self.workspace_body.grid_columnconfigure(0,weight=1 if compact else 0,minsize=0 if compact else 300)
                if compact:self.workspace_body.grid_columnconfigure(1,weight=0)
            if not compact or not show_list:
                self.detail_panel.grid(row=0,column=1 if show_list else 0,columnspan=1 if show_list else 2,sticky='nsew')
        else:
            self.fleet_bar.grid_forget()
            (self.empty_panel if empty else self.detail_panel).grid(row=0,column=0,columnspan=2,sticky='nsew')
        self.detail_summary_panel.grid_configure(pady=(10,8) if short else (18,16))
        for value in self.detail_summary:value.configure(font=font(15 if short else 21,True))
        self.detail_actions.grid_configure(pady=(6,8) if short else (10,16))
        self.sync_run_actions(busy)
        self.show_detail_tab(self.detail_tabs.get())
        self.layout_task_cards()

    def sync_run_actions(self,busy=None):
        if busy is None:busy=self.busy()
        signature=(busy,self.compact_layout,self.footer._get_widget_scaling())
        if signature==getattr(self,'_actions_signature',None):return
        self._actions_signature=signature
        for widget in (self.once_button,self.start_button,self.daily_button,self.pause_button,self.stop_button):widget.grid_forget()
        first,second=(self.pause_button,self.stop_button) if busy else (self.once_button,self.start_button)
        compact=self.compact_layout
        self.run_info.grid_configure(row=0,column=0,columnspan=4 if compact else 1)
        self.status_label.grid_configure(row=1,column=0,columnspan=4 if compact else 1)
        self.shortcut_hint.grid_configure(row=2,column=0,columnspan=4 if compact else 1)
        first.grid(row=3 if compact else 0,column=1,rowspan=1 if compact else 3,padx=(18,8),pady=(8,0) if compact else 0)
        second.grid(row=3 if compact else 0,column=2,rowspan=1 if compact else 3,pady=(8,0) if compact else 0)

        if not busy:self.daily_button.grid(row=3 if compact else 0,column=3,rowspan=1 if compact else 3,padx=(8,0),pady=(8,0) if compact else 0)

    def toggle_compact_details(self):
        if self.compact_layout:self.compact_details=not self.compact_details
        else:self.roster_collapsed=not self.roster_collapsed
        self.apply_layout()

    def show_detail_tab(self,value):
        self.detail_tabs.set(value);self.logs_open=value=='실행 기록'
        for widget in (self.detail_tasks,self.preview_frame,self.log_panel):widget.grid_forget()
        target=self.preview_frame if value=='최근 화면' else self.log_panel if self.logs_open else self.detail_tasks
        target.grid(row=0,column=0,sticky='nsew')
        self.preview_stamp.grid_forget();self.detail_stats.grid_forget();self.disabled_tasks_button.grid_forget()
        if value=='수령 결과':
            self.disabled_tasks_button.grid(row=0,column=1,sticky='w',padx=8)
            if not self.short_layout:self.detail_stats.grid(row=3,column=0,sticky='w',padx=22,pady=(8,0))
            self.layout_task_cards()
        elif value=='최근 화면':
            if not self.short_layout:self.preview_stamp.grid(row=3,column=0,sticky='w',padx=22,pady=(8,0))
            self.render_thumbnail()

    def toggle_disabled_tasks(self):
        self.show_disabled_tasks=not self.show_disabled_tasks;self.layout_task_cards()

    def layout_task_cards(self):
        from ui_state import selected_tasks,task_display_order
        if not hasattr(self,'detail_task_rows'):return
        p=self.players.get(self.view_id,{})
        selected=set(selected_tasks(p)) if p else set()
        entries=dict(self.history_entries(self.view_id))
        for task in self.fleet_states.get(self.view_id,{}).get('rooms',[]):
            if task in DAILY_LABELS and not entries.get(task):entries[task]={'active':True}
        visible=task_display_order(p,entries,self.show_disabled_tasks) if p else []
        # Keep positions stable while collection is actively updating the results.
        collecting=self.busy() and self.fleet_states.get(self.view_id,{}).get('status') in {'수령 중','재시도 중'}
        if collecting and set(visible)==set(self.display_task_order):visible=list(self.display_task_order)
        narrow=self.detail_content.winfo_width()/self.detail_content._get_widget_scaling()<620
        signature=(tuple(visible),narrow)
        if signature!=self._task_layout:
            self._task_layout=signature;self.display_task_order=visible
            for row in self.detail_task_rows.values():row.grid_forget()
            for i,key in enumerate(visible):
                self.detail_task_rows[key]._art_index=i
                self.detail_task_rows[key].grid(row=i,column=0,sticky='ew',padx=4,pady=0)
                if narrow:self.detail_times[key].grid_forget()
                else:self.detail_times[key].grid(row=0,column=3,sticky='e',padx=(0,12))
            self.tasks_empty.grid_forget()
            if not visible:self.tasks_empty.grid(row=0,column=0,pady=25,padx=15)
        disabled=len(REGULAR_LABELS)-len(selected)
        self.disabled_tasks_button.configure(text='사용 안 함 접기' if self.show_disabled_tasks else f'사용 안 함 {disabled}개 보기',state='normal' if disabled and p else 'disabled')

    def open_status_history(self):
        self.history_dialog(self.view_id,issues_only=self.summaries().get(self.view_id,{}).get('issue',False))

    def toggle_detail_enabled(self):
        if self.view_id in self.players:self.toggle_player(self.view_id,self.detail_enabled_value.get())

    def open_more(self):
        try:self.more_menu.tk_popup(self.more_button.winfo_rootx(),self.more_button.winfo_rooty()+self.more_button.winfo_height())
        finally:self.more_menu.grab_release()

    def inspect_selected(self):
        self.show_detail_tab('최근 화면');self.launch('inspect')

    def show_roster(self):
        self.compact_details=False;self.roster_collapsed=False;self.apply_layout()
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
        self.show_detail_tab('수령 결과' if self.logs_open else '실행 기록')

    def copy_logs(self):
        self.root.clipboard_clear();self.root.clipboard_append(self.logbox.get('1.0','end-1c'))
        self.copy_log_button.configure(text='복사됨')
        self.root.after(1500,lambda:self.copy_log_button.configure(text='복사') if not self.closing else None)

    def guide_dialog(self):
        win=ctk.CTkToplevel(self.root);win.title('사용 가이드');win.geometry('550x450');win.configure(fg_color=BG);win.transient(self.root)
        label(win,'연결하고, 정하고, 실행하세요.',size=22,bold=True).pack(anchor='w',padx=25,pady=(24,17))
        for title,text in [('01  뮤뮤 연결','게임을 실행하고 뮤뮤 연결을 누릅니다. 목록의 이름을 누르면 해당 화면과 기록을 볼 수 있습니다.'),('02  뮤뮤별 작업 설정','각 뮤뮤의 설정에서 수령할 작업과 간격을 선택합니다. 수련은 재료를 사용하는 작업입니다.'),('03  실행과 제어','체크된 뮤뮤만 순서대로 실행합니다. 한 번 수령과 자동 수령은 일반 작업을 실행합니다. 일일 퀘스트 수령은 패스·던전·길드를 체크 없이 한 차례 실행합니다.'),('04  중지와 일시중지','일시중지 후 재시작하면 이어서 진행합니다. 중지는 실행을 종료합니다. 중지 키는 작업 설정에서 바꿉니다.')]:
            label(win,title,size=13,bold=True).pack(anchor='w',padx=25,pady=(9,3))
            label(win,text,size=11,color=MUTED,wraplength=490,justify='left').pack(anchor='w',padx=25)
