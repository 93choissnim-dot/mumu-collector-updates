"""Live read-only summaries and explicit per-player run selection."""
import copy
import time
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
from ui_theme import BG,PANEL,INSET,LINE,RULE,TEXT,MUTED,GOLD,BLUE,ACCENT,CREAM,HOVER,SELECTED,TONES,TINTS,font,label,button
from ui_state import player_summary,visible_players,selected_tasks,task_summary,short_time
from task_catalog import TASK_LABELS


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
            recorded={task:entry.get('result') for task,entry in self.history_entries(ident).items() if task in selected_tasks(p)}
            state['history_issue']=any(value in {'failed','attempted','unrecognized'} for value in recorded.values())
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
                label(empty,title,size=14,bold=True).pack(pady=(0,8));label(empty,text,size=10,color=MUTED,wraplength=380).pack()
            for i,ident in enumerate(ids):
                row=ctk.CTkFrame(self.roster_body,fg_color=PANEL,border_width=1,border_color=RULE,corner_radius=0)
                row.grid(row=i,column=0,sticky='ew',padx=1,pady=0);row.grid_columnconfigure(1,weight=1)
                enabled=tk.BooleanVar(value=self.players[ident].get('enabled',False))
                check=ctk.CTkCheckBox(row,text='',variable=enabled,width=23,height=23,checkbox_width=18,checkbox_height=18,fg_color=ACCENT,checkmark_color=CREAM,border_color=MUTED,command=lambda key=ident:self.toggle_player(key))
                check.grid(row=0,column=0,rowspan=2,padx=(9,4),pady=11)
                name=button(row,'',lambda key=ident:self.select_player(key),width=105,height=27,anchor='w',fg_color='transparent',hover_color=HOVER,font=font(12,True))
                name.grid(row=0,column=1,sticky='ew',pady=(6,0));tooltip(name)
                status=button(row,'',lambda key=ident:self.history_dialog(key,issues_only=True),font=font(10),width=76,height=24,fg_color=INSET,border_spacing=3)
                status.grid(row=0,column=2,padx=(3,3),pady=(6,0))
                next_label=label(row,'',size=11,color=MUTED,width=67,justify='center')
                next_label.grid(row=0,column=3,pady=(6,0))
                edit=button(row,'설정',lambda key=ident:self.fleet_dialog(key),primary=True,width=46,height=30,font=font(10))
                edit.grid(row=0,column=4,rowspan=2,padx=(3,6))
                phase=label(row,'',size=10,color=MUTED,anchor='w')
                phase.grid(row=1,column=1,columnspan=3,sticky='w',pady=(0,7),padx=(6,0))
                self.roster_rows[ident]={'frame':row,'check':check,'enabled':enabled,'name':name,'status':status,'next':next_label,'phase':phase,'edit':edit}
        for ident,widgets in self.roster_rows.items():
            p=self.players[ident];state=summaries[ident]
            if widgets['enabled'].get()!=bool(p.get('enabled')):
                widgets['enabled'].set(bool(p.get('enabled')))
            update(widgets['check'],state='disabled' if busy else 'normal')
            limit=max(8,min(23,int((widgets['name'].winfo_width()/widgets['name']._get_widget_scaling()-12)/12)))
            update(widgets['name'],text=short(p.get('name','뮤뮤'),limit))
            widgets['name']._tooltip_text=p.get('name','뮤뮤')
            update(widgets['frame'],border_color=GOLD if ident==self.view_id else RULE,fg_color=SELECTED if ident==self.view_id else PANEL)
            update(widgets['status'],text=state['status'],text_color=TONES[state['tone']],fg_color=TINTS[state['tone']],hover_color=HOVER)
            update(widgets['next'],text=state['next'])
            phase=state['phase']
            if state['status'] in {'수령 중','재시도 중','일시중지'} and state['total']:
                phase=f"{state['completed']}/{state['total']} 확인  /  "+phase
            update(widgets['phase'],text=short(phase,31))
        connected=sum(s['connected'] for s in summaries.values())
        enabled=sum(bool(p.get('enabled')) for p in self.players.values())
        update(self.metric_values[0],text=f'{connected}개 / {len(self.players)}개')
        update(self.metric_values[1],text=f'{enabled}개')
        update(self.issue_metric,text=f"{sum(s['issue'] or not s['connected'] for s in summaries.values())}개")
        update(self.roster_total,text=f'{len(ids)} / {len(self.players)}개')
        available=any(s['connected'] and s['enabled'] and selected_tasks(self.players[k]) for k,s in summaries.items())
        blocked=busy or getattr(self,'update_applying',False) or (getattr(self,'update_pending',None) is not None and self.update_pending.is_set())
        for widget in [self.once_button,self.start_button]:update(widget,state='normal' if available and not blocked else 'disabled')
        update(self.inspect_button,state='normal' if self.chosen_serial() and not busy else 'disabled')
        hint=f'{enabled}개 뮤뮤 순차 실행' if enabled else '체크하여 실행 대상을 선택하세요.'
        if enabled and not available:hint='선택한 뮤뮤를 먼저 연결해 주세요.'
        if busy and self.pause_allowed:hint='일시중지 중' if self.stop.paused else ('자동 수령 중' if self.run_mode=='repeat' else '한 번 수령 중')
        update(self.run_target,text=hint)
        self.refresh_details()

    def select_player(self,ident):
        if ident not in self.players:return
        serial=next((s for s,r in self.device_reports.items() if r.get('instance_id')==ident),'')
        option=next((name for name,s in self.device_options.items() if s==serial),'')
        if option:
            self.serial_value.set(option);self.on_device_changed()
        else:
            self.serial_value.set('');self.view_id=ident;self.clear_preview()
            self.connection_text.set('연결 미확인');self.connection_badge.configure(text_color=GOLD)
        self.render_roster(force=True)

    def toggle_player(self,ident):
        p=self.players[ident]
        if self.busy():self.render_roster(force=True);return
        enabled=self.roster_rows[ident]['enabled'].get()
        if enabled and not selected_tasks(p):
            self.status.set('실행할 작업을 먼저 선택해 주세요.');self.render_roster(force=True);self.fleet_dialog(ident);return
        previous=bool(p.get('enabled'));p['enabled']=enabled
        try:self.save()
        except OSError as exc:
            p['enabled']=previous;messagebox.showerror('설정 저장 실패',str(exc),parent=self.root)
        self.update_fleet_summary();self.render_roster(force=True)

    def refresh_details(self):
        if not hasattr(self,'detail_name'):return
        ident=self.view_id;p=self.players.get(ident)
        update(self.detail_name,text=short(p.get('name','뮤뮤'),17) if p else '뮤뮤를 선택하세요')
        stamps=[]
        for task,widget in self.detail_results.items():
            if p and task in selected_tasks(p):
                entry=self.history.get(ident,task) or self.history.get(p.get('serial',''),task)
                text,tone=task_summary(task,entry.get('result'))
                if entry.get('checked_at'):stamps.append(entry['checked_at'])
            else:text,tone=('사용 안 함','muted') if p else ('—','muted')
            update(widget,text=text,text_color=TONES[tone])
        update(self.detail_checked,text='최근 확인  '+short_time(max(stamps)) if stamps else '아직 확인한 작업 기록이 없습니다.')
        if hasattr(self,'detail_stats'):
            stats=self.history.stats(ident,alternate=p.get('serial','')) if p else None
            update(self.detail_stats,text=f"오늘 완료 {stats['today']}건 / 최근 성공 {short_time(stats['last_success'])}" if stats else '')
            update(self.history_button,state='normal' if p else 'disabled')
        report=next((r for r in self.device_reports.values() if r.get('instance_id')==ident),{}) if ident else {}
        stamp=report.get('captured_at') if report.get('image') is not None else None
        update(self.preview_stamp,text=('캡처 '+short_time(stamp)) if stamp else ('최근 캡처 / 클릭하면 확대' if report.get('image') is not None else '캡처 기록 없음'))
