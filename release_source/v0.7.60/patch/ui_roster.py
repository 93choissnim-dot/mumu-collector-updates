from ui_theme import HEADER_MUTED,HEADER_GOLD,HEADER_SUCCESS,HEADER_ERROR
"""Live read-only summaries and explicit per-player run selection."""
import copy
import time
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
from ui_theme import HEADER,RULE,BG,PANEL,INSET,LINE,TEXT,MUTED,GOLD,BLUE,ACCENT,CREAM,HOVER,SELECTED,TONES,TINTS,font,label,button
from ui_state import player_summary,visible_players,selected_tasks,task_summary,short_time,entry_summary
from task_catalog import TASK_LABELS,DAILY_LABELS
from history import ISSUES


def short(text, limit):
    text=str(text)
    return text if len(text)<=limit else text[:limit-1]+'…'


def update(widget, **values):
    changed={key:value for key,value in values.items() if widget.cget(key)!=value}
    if changed:widget.configure(**changed)


def tooltip(widget):
    pending=[None];tip=[None]
    def hide(_=None):
        if pending[0] is not None:widget.after_cancel(pending[0]);pending[0]=None
        if tip[0] is not None:tip[0].destroy();tip[0]=None
    def show():
        pending[0]=None
        if not widget.winfo_exists():return
        win=ctk.CTkToplevel(widget);tip[0]=win;win.overrideredirect(True);win.attributes('-topmost',True)
        label(win,getattr(widget,'_tooltip_text',''),size=11,wraplength=350,justify='left',fg_color=PANEL,corner_radius=6).pack(ipadx=10,ipady=7)
        win.update_idletasks();x=min(widget.winfo_rootx(),widget.winfo_screenwidth()-win.winfo_reqwidth()-12)
        y=min(widget.winfo_rooty()+widget.winfo_height()+5,widget.winfo_screenheight()-win.winfo_reqheight()-12)
        win.geometry(f'+{max(0,x)}+{max(0,y)}')
    widget.bind('<Enter>',lambda _ :pending.__setitem__(0,widget.after(550,show)),add='+')
    widget.bind('<Leave>',hide,add='+');widget.bind('<Button-1>',hide,add='+');widget.bind('<Destroy>',hide,add='+')


class RosterUI:
    def summaries(self,working=None):
        busy=self.busy() if working is None else working
        live={r.get('instance_id') for s,r in self.device_reports.items() if s not in self.unavailable_devices}
        now=self.stop.clock()
        result={}
        for ident,p in self.players.items():
            state=copy.deepcopy(self.fleet_states.get(ident,{}))
            from daily_state import korea_day
            from action_state import account_scope
            scoped='session_day' in state
            if scoped and (state.get('session_day')!=korea_day() or state.get('scope')!=account_scope(ident,p.get('daily_profile',''))):state={}
            if not state and hasattr(self,'current_record'):
                record=self.current_record(ident);rooms=record.get('planned',record.get('tasks',[]))
                results={t:v for t,v in record.get('results',{}).items() if t in rooms}
                from history import TERMINAL_RESULTS
                status='확인 완료' if rooms and all(results.get(t) in TERMINAL_RESULTS for t in rooms) else '확인 필요' if any(v in ISSUES for v in results.values()) else '대기'
                state={'rooms':rooms,'results':results,'status':status} if rooms else {}
            recorded={task:entry.get('result') for task,entry in self.history_entries(ident).items() if task in selected_tasks(p) or task in DAILY_LABELS}
            state['history_issue']=any(value in ISSUES for value in recorded.values()) if not scoped and not hasattr(self,'current_record') else False
            result[ident]=player_summary(p,state,ident in live,busy,self.stop.paused,now)
        return result

    def render_roster(self,force=False,working=None):
        if not hasattr(self,'roster_body'):return
        now=time.monotonic()
        active=any(s.get('status') in {'수령 중','재시도 중'} for s in self.fleet_states.values())
        interval=.35 if active else 1.
        if not force and not getattr(self,'roster_dirty',False) and now-self.ui_last_refresh<interval:return
        self.roster_dirty=False
        self.ui_last_refresh=now
        busy=self.busy() if working is None else working
        if len(self.players)==1 and self.view_id not in self.players:self.view_id=next(iter(self.players))
        if hasattr(self,'refresh_workflow'):self.refresh_workflow(force=force)
        summaries=self.summaries(working)
        ids=visible_players(self.players,summaries,self.roster_query.get(),self.roster_filter.get())
        signature=tuple(ids)
        if signature!=self.roster_signature:
            for child in self.roster_body.winfo_children():child.destroy()
            self.roster_rows={};self.roster_signature=signature
            if not ids:
                empty=ctk.CTkFrame(self.roster_body,fg_color='transparent');empty.grid(row=0,column=0,sticky='ew',pady=38)
                title='연결된 뮤뮤가 없습니다.' if not self.players else '조건에 맞는 뮤뮤가 없습니다.'
                text='게임을 실행하고 위의 뮤뮤 연결을 눌러 주세요.' if not self.players else '이름 검색이나 목록 필터를 바꿔 주세요.'
                label(empty,title,size=14,bold=True).pack(pady=(0,8));label(empty,text,size=10,color=MUTED,wraplength=245).pack()
            for i,ident in enumerate(ids):
                row=ctk.CTkFrame(self.roster_body,fg_color=PANEL,border_width=1,border_color=RULE,corner_radius=9)
                row.grid(row=i,column=0,sticky='ew',padx=2,pady=(0,8));row.grid_columnconfigure(1,weight=1)
                enabled=tk.BooleanVar(value=self.players[ident].get('enabled',False))
                check=ctk.CTkCheckBox(row,text='',variable=enabled,width=22,height=24,checkbox_width=18,checkbox_height=18,fg_color=ACCENT,checkmark_color=HEADER,border_color=MUTED,command=lambda key=ident:self.toggle_player(key))
                check.grid(row=0,column=0,padx=(12,3),pady=(11,0))
                name=button(row,'',lambda key=ident:self.select_player(key),width=92,height=30,anchor='w',fg_color='transparent',hover_color=HOVER,font=font(13,True),border_spacing=3)
                name.grid(row=0,column=1,sticky='ew',pady=(9,0));tooltip(name)
                status=button(row,'',lambda key=ident:self.history_dialog(key,issues_only=True),font=font(10),width=78,height=25,fg_color=INSET,border_spacing=3)
                status.grid(row=0,column=2,padx=(4,10),pady=(9,0))
                phase=label(row,'',size=10,color=MUTED,anchor='w')
                phase.grid(row=1,column=0,columnspan=3,sticky='w',pady=(3,4),padx=14)
                next_label=label(row,'',size=11,color=MUTED,anchor='w')
                next_label.grid(row=2,column=0,columnspan=2,sticky='w',padx=14,pady=(0,10))
                edit=button(row,'설정',lambda key=ident:self.fleet_dialog(key),width=50,height=26,font=font(10),fg_color='transparent',text_color=ACCENT)
                edit.grid(row=2,column=2,sticky='e',padx=10,pady=(0,10))
                self.roster_rows[ident]={'frame':row,'check':check,'enabled':enabled,'name':name,'status':status,'next':next_label,'phase':phase,'edit':edit}
        for ident,widgets in self.roster_rows.items():
            p=self.players[ident];state=summaries[ident]
            if widgets['enabled'].get()!=bool(p.get('enabled')):
                widgets['enabled'].set(bool(p.get('enabled')))
            update(widgets['check'],state='disabled' if busy else 'normal')
            limit=max(5,min(23,int((widgets['name'].winfo_width()/widgets['name']._get_widget_scaling()-8)/13)))
            update(widgets['name'],text=short(p.get('name','뮤뮤'),limit))
            widgets['name']._tooltip_text=p.get('name','뮤뮤')
            update(widgets['frame'],border_color=ACCENT if ident==self.view_id else RULE,fg_color=SELECTED if ident==self.view_id else PANEL)
            update(widgets['status'],text=state['status'],text_color=TONES[state['tone']],fg_color=TINTS[state['tone']],hover_color=HOVER)
            update(widgets['next'],text='다음 수령  '+state['next'])
            phase=state['phase']
            if state['status'] in {'수령 중','재시도 중','일시중지'} and state['total']:
                phase=f"{state['completed']}/{state['total']} 확인  /  "+phase
            update(widgets['phase'],text=short(phase,28))
        connected=sum(s['connected'] for s in summaries.values())
        enabled=sum(bool(p.get('enabled')) for p in self.players.values())
        issues=sum(s['issue'] or not s['connected'] for s in summaries.values())
        update(self.fleet_overview,text=f'{len(self.players)}개 뮤뮤  /  연결 {connected}개  /  실행 대상 {enabled}개  /  확인 필요 {issues}개')
        update(self.roster_total,text=f'{len(ids)} / {len(self.players)}개')
        from session_workflow import task_scope
        scope=self.config.get('run_scope','regular')
        available=any(s['connected'] and s['enabled'] and task_scope(self.players[k],scope) for k,s in summaries.items())
        auto_available=any(s['connected'] and s['enabled'] and task_scope(self.players[k],scope,repeat=True) for k,s in summaries.items())
        blocked=busy or getattr(self,'update_applying',False) or (getattr(self,'update_pending',None) is not None and self.update_pending.is_set())
        update(self.once_button,state='normal' if available and not blocked else 'disabled')
        update(self.start_button,state='normal' if auto_available and not blocked else 'disabled')
        daily_available=any(s['connected'] and s['enabled'] for s in summaries.values())
        update(self.inspect_button,state='normal' if self.chosen_serial() and not busy else 'disabled')
        hint=f'{enabled}개 뮤뮤 순차 실행' if enabled else '체크하여 실행 대상을 선택하세요.'
        if not self.players:hint='뮤뮤를 연결해 주세요.'
        if enabled and not daily_available:hint='선택한 뮤뮤를 먼저 연결해 주세요.'
        if busy and self.pause_allowed:hint='일시중지 중' if self.stop.paused else ('자동 수령 중' if self.run_mode=='repeat' else '일일 작업 중' if self.run_mode=='daily' else '미완료 이어하기 중' if self.run_mode=='resume' else '일반 작업 중')
        if busy and getattr(self,'active_instance',None) in self.players:
            hint=('일시정지: ' if self.stop.paused else '실행: ')+short(self.players[self.active_instance].get('name','뮤뮤'),18)
        elif not busy and enabled:
            total=sum(len(task_scope(p,scope)) for p in self.players.values() if p.get('enabled'))
            hint=f'{enabled}개 뮤뮤 / 선택 작업 {total}개'
        update(self.run_target,text=hint)
        self.refresh_details(summaries)
        self.apply_layout();self.sync_run_actions(busy)

    def select_player(self,ident):
        if ident not in self.players:return
        serial=next((s for s,r in self.device_reports.items() if r.get('instance_id')==ident),'')
        option=next((name for name,s in self.device_options.items() if s==serial),'')
        if option:
            self.serial_value.set(option);self.on_device_changed()
        else:
            self.serial_value.set('');self.view_id=ident;self.clear_preview()
            self.connection_text.set('연결 미확인');self.connection_badge.configure(text_color=HEADER_GOLD)
        if self.compact_layout:self.compact_details=True
        self.render_roster(force=True)

    def toggle_player(self,ident,enabled=None):
        p=self.players[ident]
        if self.busy():self.render_roster(force=True);return
        if enabled is None:enabled=self.roster_rows[ident]['enabled'].get()
        previous=bool(p.get('enabled'));p['enabled']=enabled
        try:self.save()
        except OSError as exc:
            p['enabled']=previous;messagebox.showerror('설정 저장 실패',str(exc),parent=self.root)
        self.update_fleet_summary();self.render_roster(force=True)

    def refresh_details(self,summaries=None):
        if not hasattr(self,'detail_name'):return
        ident=self.view_id;p=self.players.get(ident)
        width=self.root.winfo_width()/self.root._get_window_scaling()
        limit=18 if width<800 else max(6,min(24,int((width-410)/24)))
        update(self.detail_name,text=short(p.get('name','뮤뮤'),limit) if p else '뮤뮤를 연결하세요')
        self.detail_name._tooltip_text=('보고 있는 뮤뮤: '+p.get('name','뮤뮤')) if p else '뮤뮤를 연결하세요'
        if not p:
            self.connection_text.set('연결된 뮤뮤 없음' if not self.players else '목록에서 뮤뮤를 선택하세요.')
            update(self.connection_badge,text_color=HEADER_MUTED)
        self.detail_enabled_value.set(bool(p and p.get('enabled')))
        update(self.detail_enabled,state='normal' if p and not self.busy() else 'disabled')
        state=(summaries if summaries is not None else self.summaries()).get(ident)
        if state:
            update(self.detail_summary[0],text=state['status'],text_color=TONES[state['tone']])
            update(self.detail_summary[1],text=state['next'])
            minutes=p.get('minutes',60)
            interval=f'{minutes/60:g}시간' if isinstance(minutes,(int,float)) and minutes%60==0 else f'{minutes:g}분' if isinstance(minutes,(int,float)) else str(minutes)+'분'
            update(self.detail_summary[2],text=interval)
        else:
            for widget in self.detail_summary:update(widget,text='—')
        self.layout_task_cards()
        entries=self.display_entries(ident) if hasattr(self,'display_entries') else self.history_entries(ident)
        current=self.fleet_states.get(ident,{})
        active=current.get('active_task') if self.busy() and current.get('status') in {'수령 중','재시도 중'} else None
        issues=sum(not e.get('previous') and e.get('result') in ISSUES for t,e in entries.items() if p and (t in selected_tasks(p) or t in DAILY_LABELS))
        attention=('진행 중: '+TASK_LABELS[active]) if active in TASK_LABELS else (f'이번 실행 확인 필요 {issues}개 / 결과를 눌러 이유 확인' if issues else '이번 실행 결과 / 이전 기록은 수령 기록에서 확인')
        if attention:
            self.attention_label.configure(text=attention,wraplength=max(230,int(self.detail_panel.winfo_width()/self.detail_panel._get_widget_scaling())-50))
            self.attention_label.grid(row=1,column=0,columnspan=2,sticky='ew',pady=(5,0))
        else:self.attention_label.grid_forget()
        stamps=[]
        for task,widget in self.detail_results.items():
            entry=entries.get(task,{}) if p and (task in selected_tasks(p) or task in DAILY_LABELS) else {}
            if p and (task in selected_tasks(p) or task in DAILY_LABELS):
                entry=entries.get(task,{})
                text,tone=entry_summary(task,entry)
                if entry.get('checked_at'):stamps.append(entry['checked_at'])
            else:text,tone=('사용 안 함','muted') if p else ('—','muted')
            active=self.busy() and self.fleet_states.get(ident,{}).get('status') in {'수령 중','재시도 중'} and self.fleet_states.get(ident,{}).get('active_task')==task
            if active:text,tone='일시중지' if self.stop.paused else '진행 중','active'
            update(widget,text=text,text_color=TONES[tone])
            widget._tooltip_text=entry.get('reason','') or text
            if not getattr(widget,'_reason_tooltip',False):tooltip(widget);widget._reason_tooltip=True
            stamp=entry.get('collected_at') if entry.get('previous') else entry.get('checked_at')
            update(self.detail_times[task],text=('최근 '+short_time(stamp) if entry.get('previous') else short_time(stamp)) if stamp else '—')
            update(self.detail_task_rows[task],fg_color=TINTS[tone] if tone in {'error','warning','active'} else PANEL,border_width=2 if active else 0,border_color=GOLD if active else RULE)
        update(self.detail_checked,text='최근 확인  '+short_time(max(stamps)) if stamps else '아직 확인한 작업 기록이 없습니다.')
        if hasattr(self,'detail_stats'):
            stats=self.history.stats(ident,alternate=p.get('serial','')) if p else None
            self.detail_stats.configure(wraplength=max(260,int(self.detail_panel.winfo_width()/self.detail_panel._get_widget_scaling())-48),justify='left')
            update(self.detail_stats,text=f"오늘 누적 수행 확인 {stats['today']}건 (KST) / 최근 성공 {short_time(stats['last_success'])}" if stats else '')
            update(self.history_button,state='normal' if p else 'disabled')
        report=next((r for r in self.device_reports.values() if r.get('instance_id')==ident),{}) if ident else {}
        stamp=report.get('captured_at') if report.get('image') is not None else None
        update(self.preview_stamp,text=('캡처 '+short_time(stamp)) if stamp else ('최근 캡처 / 클릭하면 확대' if report.get('image') is not None else '캡처 기록 없음'))
