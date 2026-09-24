"""Footer controls and a read-only preview before safe continuation."""
import time
import tkinter as tk
import customtkinter as ctk
from daily_state import korea_day,LedgerError
from action_state import account_scope
from session_workflow import continuation,session_entry,task_scope
from task_catalog import TASK_LABELS
from ui_theme import PANEL,MUTED,TEXT,GOLD,RED,ACCENT,HEADER,font,label,button,panel
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
            selected_color=ACCENT,selected_hover_color=ACCENT,unselected_color=PANEL,text_color=TEXT)
        self.resume_bar=ctk.CTkFrame(self.footer,fg_color='transparent');self.resume_bar.grid_columnconfigure(0,weight=1)
        self.resume_hint=label(self.resume_bar,'',size=12,color=GOLD,anchor='w')
        self.resume_hint.grid(row=0,column=0,sticky='w')
        self.resume_button=button(self.resume_bar,'미완료 확인',self.resume_unfinished,width=146,height=34,font=font(12))
        self.resume_button.grid(row=0,column=1,padx=(8,0))
        self.workflow_plan={'targets':{},'safe':[],'held':[],'records':{}}
        self.workflow_error='';self._workflow_refresh=0
    def change_scope(self,value):
        if self.busy():return
        self.config['run_scope']=SCOPES[value]
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
        visible=set(record.get('tasks',[]))|set(entries)|set(task_scope(self.players.get(ident,{}),self.config.get('run_scope','regular')))
        return {task:session_entry(task,record,entries.get(task,{})) for task in TASK_LABELS if not task.startswith('daily_') or task in visible}
    def sync_workflow(self,busy):
        if not hasattr(self,'scope_selector'):return
        self.refresh_workflow()
        blocked=busy or getattr(self,'update_applying',False) or (getattr(self,'update_pending',None) is not None and self.update_pending.is_set())
        self.scope_selector.configure(state='disabled' if blocked else 'normal')
        count=len(self.workflow_plan['safe']);held=len(self.workflow_plan['held'])
        self.resume_bar.grid_forget()
        if not busy and (count or held or self.workflow_error):
            self.resume_hint.configure(text=self.workflow_error or f'이어갈 작업 {count}개 / 결과 확인 필요 {held}개',wraplength=370)
            self.resume_button.configure(text='미완료 이어하기' if count else '보류 이유 보기',state='disabled' if blocked or self.workflow_error else 'normal')
            self.resume_bar.grid(row=2,column=0,columnspan=3,sticky='ew',pady=(6,3))
        scope=self.config.get('run_scope','regular')
        self.start_button.configure(text='일반 자동 실행')
        self.once_button.configure(text='한 번 실행')
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
