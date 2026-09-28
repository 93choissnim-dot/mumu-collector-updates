"""Footer controls and a read-only preview before safe continuation."""
import time
import tkinter as tk
import customtkinter as ctk
from daily_state import korea_day,LedgerError
from action_state import account_scope
from session_workflow import continuation,session_entry,task_scope
from task_catalog import TASK_LABELS
from ui_theme import PANEL,MUTED,TEXT,GOLD,RED,ACCENT,HEADER,SELECTED,font,label,button,panel
from ui_layout import fit_window

SCOPES={'일반 작업':'regular','일일 작업':'daily','전체':'all'}

class WorkflowUI:
    def build_workflow(self):
        value=self.config.get('run_scope','regular')
        if value not in SCOPES.values():value='regular'
        self.config['run_scope']=value
        self.scope_value=tk.StringVar(value=next(k for k,v in SCOPES.items() if v==value))
        self.scope_selector=ctk.CTkSegmentedButton(self.footer,values=list(SCOPES),variable=self.scope_value,
            command=self.change_scope,width=245,height=36,font=font(12),fg_color=PANEL,
            selected_color=SELECTED,selected_hover_color=SELECTED,unselected_color=PANEL,text_color=TEXT)
        self.resume_bar=ctk.CTkFrame(self.footer,fg_color='transparent');self.resume_bar.grid_columnconfigure(0,weight=1)
        self.resume_hint=label(self.resume_bar,'',size=12,color=GOLD,anchor='w')
        self.resume_hint.grid(row=0,column=0,sticky='w')
        # Keep the always-available overview on the existing information line;
        # an empty continuation row would take space from compact task results.
        self.today_button=button(self.run_info,'오늘 작업',self.today_overview_dialog,width=86,height=26,font=font(11))
        self.today_button.pack(side='left',padx=(12,0))
        self.resume_button=button(self.resume_bar,'미완료 확인',self.resume_unfinished,width=146,height=34,font=font(12))
        self.resume_button.grid(row=0,column=1,padx=(8,0))
        self.workflow_plan={'targets':{},'safe':[],'held':[],'records':{}}
        self.workflow_error='';self._workflow_refresh=0
    def change_scope(self,value):
        if self.busy():return
        self.config['run_scope']=SCOPES[value];self.scope_value.set(value)
        try:self.save()
        except OSError as exc:self.status.set('작업 범위 저장 실패: '+str(exc))
        self.render_roster(force=True)
    def refresh_workflow(self,force=False):
        if not hasattr(self,'workflow_plan'):return
        now=time.monotonic()
        if not force and now-self._workflow_refresh<1:return
        self._workflow_refresh=now
        from app import DATA
        try:self.workflow_plan=continuation(DATA,self.players);self.workflow_error=''
        except (LedgerError,ValueError,OSError) as exc:
            self.workflow_plan={'targets':{},'safe':[],'held':[],'records':{}}
            self.workflow_error=str(exc)
    def current_record(self,ident):
        p=self.players.get(ident,{})
        scope=account_scope(ident or '',p.get('daily_profile',''))
        state=self.fleet_states.get(ident,{})
        if state.get('session_day')==korea_day() and state.get('scope')==scope:
            return {'tasks':state.get('rooms',[]),'results':state.get('results',{}),'entries':state.get('run_entries',{})}
        return self.workflow_plan.get('records',{}).get(ident,{}) if hasattr(self,'workflow_plan') else {}
    def display_entries(self,ident):
        record=self.current_record(ident);entries=self.history_entries(ident)
        visible=set(record.get('planned',record.get('tasks',[])))|{t for t,e in entries.items() if e}|set(task_scope(self.players.get(ident,{}),self.config.get('run_scope','regular')))
        return {task:session_entry(task,record,entries.get(task,{})) for task in TASK_LABELS if not task.startswith('daily_') or task in visible}
    def sync_workflow(self,busy):
        if not hasattr(self,'scope_selector'):return
        self.refresh_workflow()
        blocked=busy or getattr(self,'update_applying',False) or (getattr(self,'update_pending',None) is not None and self.update_pending.is_set())
        count=len(self.workflow_plan['safe']);held=len(self.workflow_plan['held'])
        signature=(busy,blocked,count,held,self.workflow_error)
        if signature==getattr(self,'_resume_signature',None):return
        self._resume_signature=signature
        self.scope_selector.configure(state='disabled' if blocked else 'normal')
        visible=bool(not busy and (count or held or self.workflow_error))
        if not visible:
            if getattr(self,'_resume_visible',False):self.resume_bar.grid_forget()
        if visible:
            self.resume_hint.configure(text=self.workflow_error or f'이어하기 {count}개 / 확인 필요 {held}개',wraplength=245)
            self.resume_button.configure(text='미완료 이어하기' if count else '보류 이유 보기',state='disabled' if blocked or self.workflow_error or not (count or held) else 'normal')
            if not getattr(self,'_resume_visible',False):self.resume_bar.grid(row=2,column=0,columnspan=3,sticky='ew',pady=(6,3))
        self._resume_visible=visible
        scope=self.config.get('run_scope','regular')
        self.start_button.configure(text='일반 자동 실행')
        self.once_button.configure(text='한 번 실행')
    def today_overview_dialog(self):
        """Review all selected tasks without changing the execution selection."""
        from app import DATA
        from action_state import ActionState
        from daily_state import ManualQuestLedger,step_label
        from run_journal import RunJournal
        from today_overview import build_overview,STATUS_LABELS,donation_lines
        old=getattr(self,'today_window',None)
        if old is not None and old.winfo_exists():old.destroy()
        win=ctk.CTkToplevel(self.root);self.today_window=win
        win.title('오늘 작업 / 계정별 확인');win.configure(fg_color=PANEL);win.transient(self.root)
        width,_=fit_window(win,(650,620),(520,380));win.grid_columnconfigure(0,weight=1);win.grid_rowconfigure(2,weight=1)
        label(win,'오늘 작업',size=21,bold=True).grid(row=0,column=0,sticky='w',padx=20,pady=(16,5))
        summary=label(win,'',size=12,color=MUTED,wraplength=width-48,justify='left')
        summary.grid(row=1,column=0,sticky='w',padx=20,pady=(0,10))
        body=ctk.CTkScrollableFrame(win,fg_color='transparent');self.today_body=body
        body.grid(row=2,column=0,sticky='nsew',padx=12);body.grid_columnconfigure(0,weight=1)
        controls=ctk.CTkFrame(win,fg_color='transparent');controls.grid(row=3,column=0,sticky='e',padx=20,pady=12)
        button(controls,'새로고침',lambda:render(),width=95,height=32).pack(side='left',padx=(0,8))
        button(controls,'닫기',win.destroy,width=80,height=32).pack(side='left')
        def render():
            for child in body.winfo_children():child.destroy()
            try:
                report=build_overview(self.players,RunJournal(DATA/'run_progress.json').data,
                    ManualQuestLedger(DATA/'daily_manual.json').data,ActionState(DATA/'action_state.json').data,
                    histories={ident:self.history_entries(ident) for ident in self.players})
            except (LedgerError,ValueError,OSError) as exc:
                self.today_report=None;summary.configure(text='기록을 읽지 못했습니다: '+str(exc),text_color=RED);return
            self.today_report=report
            summary.configure(text=f"{report['day']} (KST) / 선택한 일반 + 일일 작업 전체\n일반 작업의 완료는 오늘 최근 확인 결과이며, 다시 실행할 수 있습니다.",text_color=MUTED)
            if not report['accounts']:
                label(body,'등록된 계정이 없습니다.',size=13,color=MUTED).grid(row=0,column=0,pady=24);return
            for index,account in enumerate(report['accounts']):
                card=panel(body);card.grid(row=index,column=0,sticky='ew',pady=(0,9));card.grid_columnconfigure(0,weight=1)
                title=account['name']+(' / '+account['profile'] if account['profile'] else '')
                title+=' / 사용 중' if account['enabled'] else ' / 사용 안 함 (실행 제외)'
                label(card,title,size=14,bold=True,color=TEXT if account['enabled'] else MUTED,
                      wraplength=width-82,justify='left').grid(row=0,column=0,sticky='w',padx=13,pady=(10,5))
                counts=account['counts']
                line=f"미실행 {counts['unrun']} / 일부 진행 {counts['partial']} / 확인/보류 {counts['uncertain']+counts['held']+counts['prior']} / 완료 {counts['done']}"
                label(card,line,size=11,color=GOLD,wraplength=width-82,justify='left').grid(row=1,column=0,sticky='w',padx=13,pady=(0,7))
                lines=[]
                for row in account['tasks']:
                    text=TASK_LABELS[row['task']]+' / '+STATUS_LABELS[row['status']]
                    if not row['selected']:text+=' (선택 해제 / 기록 보존)'
                    if row['total'] and row['status']!='done':text+=f" / 오늘 {row['complete']}/{row['total']}단계 확인"
                    if row['excluded']:text+=f" / 유료 제외 {row['excluded']}단계"
                    lines.append(text)
                    for step,info in row['pending'].items():
                        if not isinstance(info,dict):info={}
                        origin=info.get('input_request',info);origin=origin if isinstance(origin,dict) else {}
                        lines.append('  '+step_label(row['task'],step)+' 입력 결과 미확인 / '+(origin.get('requested_at') or '요청 시각 기록 없음'))
                label(card,'\n'.join(lines) or '선택한 작업이 없습니다.',size=12,wraplength=width-82,
                      justify='left').grid(row=2,column=0,sticky='w',padx=13,pady=(0,8))
                donation=account['donation']
                if any(row['task']=='daily_guild' for row in account['tasks']) or donation['verified'] or donation['pending'] or donation['completed']:
                    label(card,donation_lines(donation),size=11,color=RED,wraplength=width-82,
                          justify='left').grid(row=3,column=0,sticky='w',padx=13,pady=(0,8))
                button(card,'계정 기록 보기',lambda ident=account['id']:self.history_dialog(ident),width=130,height=29,
                       font=font(11)).grid(row=4,column=0,sticky='e',padx=13,pady=(0,10))
        self.today_render=render;render()
    def resume_unfinished(self):
        blocked=self.retry_block_reason()
        if blocked:self.status.set(blocked);return
        self.refresh_workflow(force=True);plan=self.workflow_plan
        if self.workflow_error:self.status.set(self.workflow_error);return
        if not plan['safe'] and not plan['held']:
            self.status.set('선택한 계정에 오늘 이어갈 미완료 작업이 없습니다.');return
        old=getattr(self,'resume_window',None)
        if old is not None and old.winfo_exists():old.destroy()
        win=ctk.CTkToplevel(self.root);self.resume_window=win;win.title('미완료 작업 확인');win.configure(fg_color=PANEL);win.transient(self.root)
        width,_=fit_window(win,(610,560),(520,380));win.grid_columnconfigure(0,weight=1);win.grid_rowconfigure(2,weight=1)
        label(win,'이어갈 작업과 보류된 작업',size=20,bold=True).grid(row=0,column=0,sticky='w',padx=20,pady=(18,8))
        label(win,f"이어하기 {len(plan['safe'])}개 / 결과 확인 필요 {len(plan['held'])}개\n완료한 작업과 결과가 불확실한 입력은 반복하지 않습니다.",size=12,color=MUTED,justify='left',wraplength=width-45).grid(row=1,column=0,sticky='w',padx=20,pady=(0,12))
        body=ctk.CTkScrollableFrame(win,fg_color='transparent');body.grid(row=2,column=0,sticky='nsew',padx=14);body.grid_columnconfigure(0,weight=1)
        for i,(held,item) in enumerate([(False,x) for x in plan['safe']]+[(True,x) for x in plan['held']]):
            card=panel(body);card.grid(row=i,column=0,sticky='ew',pady=(0,7));card.grid_columnconfigure(0,weight=1)
            label(card,item['name']+' / '+TASK_LABELS[item['task']],size=13,bold=True,wraplength=width-75,justify='left').grid(row=0,column=0,sticky='w',padx=12,pady=(10,4))
            label(card,('보류: ' if held else '이어하기: ')+item['reason'],size=12,color=GOLD if held else MUTED,wraplength=width-75,justify='left').grid(row=1,column=0,sticky='w',padx=12,pady=(0,8))
            if held:button(card,'기록과 해결 방법',lambda x=item:self.history_dialog(x['id'],task_filter=x['task']),width=145,height=30,font=font(12)).grid(row=2,column=0,sticky='e',padx=12,pady=(0,8))
        row=ctk.CTkFrame(win,fg_color='transparent');row.grid(row=3,column=0,sticky='e',padx=20,pady=14)
        button(row,'닫기',win.destroy,width=80).pack(side='left',padx=6)
        self.resume_confirm_button=button(row,f"{len(plan['safe'])}개 이어서 실행",lambda:self.confirm_resume(win),width=172,primary=True,state='normal' if plan['safe'] else 'disabled')
        self.resume_confirm_button.pack(side='left')
    def confirm_resume(self,win):
        if self.retry_block_reason():return
        self.refresh_workflow(force=True)
        if self.workflow_error:self.status.set(self.workflow_error);return
        targets=self.workflow_plan['targets']
        win.destroy()
        if targets:self.launch('resume',targets)
        else:self.status.set('이어하기 대상이 변경됐습니다. 남은 작업을 다시 확인해 주세요.')
