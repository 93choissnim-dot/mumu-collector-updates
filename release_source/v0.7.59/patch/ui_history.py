"""Per-player results, failure evidence and explicit failed-task retries."""
from datetime import datetime
import tkinter as tk
import customtkinter as ctk
from PIL import Image
from diagnostics import failure_snapshot
from history import ISSUES,history_day
from task_catalog import TASK_LABELS,DAILY_LABELS,REGULAR_LABELS
from ui_state import selected_tasks,task_summary,short_time,retry_tasks,daily_step_summary,entry_summary
from ui_theme import BG,PANEL,MUTED,TEXT,GOLD,RED,TONES,font,label,heading,button,panel,GameTabs
from ui_layout import fit_window


class HistoryUI:
    def resume_unfinished(self):
        blocked=self.retry_block_reason()
        if blocked:self.status.set(blocked);return
        from app import DATA
        from run_journal import RunJournal
        from action_state import account_scope
        from daily_state import LedgerError
        try:
            journal=RunJournal(DATA/'run_progress.json');targets={}
            for ident,player in self.players.items():
                if not player.get('enabled'):continue
                tasks=journal.remaining(account_scope(ident,player.get('daily_profile','')))
                allowed=set(selected_tasks(player))|set(DAILY_LABELS)
                tasks=[t for t in tasks if t in allowed]
                if tasks:targets[ident]=tasks
        except LedgerError as exc:self.status.set(str(exc));return
        if not targets:
            self.status.set('선택한 계정에 오늘 이어갈 미완료 작업이 없습니다.');return
        self.launch('resume',targets)

    def history_entries(self,ident):
        p=self.players.get(ident,{})
        return self.history.snapshot(ident,p.get('serial',''))

    def request_history_refresh(self):
        win=getattr(self,'history_window',None)
        if win is None or not win.winfo_exists() or getattr(self,'history_refresh_pending',False):return
        self.history_refresh_pending=True
        def refresh():
            self.history_refresh_pending=False
            current=getattr(self,'history_window',None)
            render=getattr(self,'history_render',None)
            if current is not None and current.winfo_exists() and render:render()
        self.root.after_idle(refresh)

    def retry_block_reason(self):
        if self.update_pending.is_set() or self.update_applying:
            return '업데이트를 준비하거나 적용하고 있어 재시도할 수 없습니다.'
        if self.busy():
            if getattr(self.stop,'paused',False):
                return '일시중지한 작업이 남아 있습니다. 중지를 눌러 실행을 끝낸 뒤 재시도하세요.'
            return '실행 또는 예약 대기 중입니다. 작업이 끝나거나 중지를 누른 뒤 재시도하세요.'
        return ''

    def retry_failed(self,ident,requested=None):
        blocked=self.retry_block_reason()
        if blocked:self.status.set(blocked);return
        p=self.players.get(ident)
        if not p:return
        tasks=retry_tasks(p,self.history_entries(ident),requested)
        if not tasks:
            disabled=requested and any(task in REGULAR_LABELS and task not in selected_tasks(p) for task in requested)
            self.status.set('사용하지 않는 작업입니다. 작업 설정에서 선택한 뒤 재시도하세요.' if disabled else '재시도할 실패 항목이 없습니다.')
            return
        from app import DATA
        from action_state import account_scope
        from daily_state import LedgerError,DAILY_STEPS
        from retry_resolution import pending_choices,show_resolution
        try:
            scope=account_scope(ident,p.get('daily_profile',''))
            for task in tasks:
                resource_steps={'daily_guild':('donation','dungeon')}.get(task,())
                if not resource_steps:continue
                choices=pending_choices(DATA,scope,task)
                choices=[choice for choice in choices if choice['step'] in resource_steps]
                if choices:
                    show_resolution(self,ident,task)
                    return
        except (LedgerError,ValueError,OSError) as exc:
            self.status.set('보류 기록을 확인하지 못해 재시도할 수 없습니다: '+str(exc))
            return
        self.select_player(ident)
        win=getattr(self,'history_window',None)
        if win is not None and win.winfo_exists():win.destroy()
        self.launch('retry',{ident:tasks})

    def resolve_history_pending(self,ident,task):
        blocked=self.retry_block_reason()
        if blocked:self.status.set(blocked);return
        from retry_resolution import show_resolution
        show_resolution(self,ident,task)

    def review_dungeon_completion(self,ident):
        blocked=self.retry_block_reason()
        if blocked:self.status.set(blocked);return
        if ident not in self.players:return
        self.select_player(ident)
        win=getattr(self,'history_window',None)
        if win is not None and win.winfo_exists():win.destroy()
        self.launch('verify_daily',{ident:['daily_dungeons']})

    def history_dialog(self,ident=None,issues_only=False,task_filter=None):
        ident=ident or self.view_id
        if ident not in self.players:return
        previous=getattr(self,'history_window',None)
        if previous is not None and previous.winfo_exists():previous.destroy()
        win=ctk.CTkToplevel(self.root);self.history_window=win
        win.title('뮤뮤 수령 기록');win.configure(fg_color=BG);win.transient(self.root)
        width,_=fit_window(win,(720,650),(580,430))
        win.grid_columnconfigure(0,weight=1);win.grid_rowconfigure(3,weight=1)
        p=self.players[ident]
        heading(win,p.get('name','뮤뮤')+' / '+(TASK_LABELS[task_filter] if task_filter in TASK_LABELS else '수령 기록'),size=21,wraplength=width-42,justify='left').grid(row=0,column=0,sticky='w',padx=20,pady=(18,4))
        summary=label(win,'',size=12,color=GOLD,wraplength=width-42,justify='left');summary.grid(row=1,column=0,sticky='w',padx=20,pady=(0,9))
        toolbar=ctk.CTkFrame(win,fg_color='transparent');toolbar.grid(row=2,column=0,sticky='ew',padx=20,pady=(0,9));toolbar.grid_columnconfigure(1,weight=1)
        mode=tk.StringVar(value='확인 필요' if issues_only else '전체 기록')
        tabs=GameTabs(toolbar,['전체 기록','확인 필요'],variable=mode,width=220,height=30,command=lambda _:render())
        tabs.grid(row=0,column=0,sticky='w')
        button(toolbar,'새로고침',lambda:render(),width=87,height=30,font=font(11)).grid(row=0,column=2,sticky='e')
        body=ctk.CTkScrollableFrame(win,fg_color='transparent',corner_radius=0);body.grid(row=3,column=0,sticky='nsew',padx=14);body.grid_columnconfigure(0,weight=1)
        footer=ctk.CTkFrame(win,fg_color='transparent');footer.grid(row=4,column=0,sticky='ew',padx=20,pady=14);footer.grid_columnconfigure(0,weight=1)
        label(footer,'오늘 누적은 수행 결과가 확인된 작업 건수입니다. 클릭 횟수나 획득 재화량이 아닙니다.',size=10,color=MUTED,wraplength=width-48,justify='left').grid(row=0,column=0,columnspan=3,sticky='w',pady=(0,10))
        retry_hint=label(footer,'',size=11,color=GOLD,wraplength=width-48,justify='left');retry_hint.grid(row=1,column=0,columnspan=3,sticky='w',pady=(0,8))
        retry=button(footer,'실패/보류 작업 재시도',lambda:self.retry_failed(ident,[task_filter] if task_filter else None),primary=True,width=158)
        retry.grid(row=2,column=1,padx=(8,8));button(footer,'닫기',win.destroy,width=78).grid(row=2,column=2)
        def render():
            if not win.winfo_exists():return
            for child in body.winfo_children():child.destroy()
            if ident not in self.players:
                win.destroy();return
            p=self.players[ident]
            entries=self.history_entries(ident);day=history_day()
            from app import DATA
            from daily_state import ManualQuestLedger,LedgerError,step_label
            daily_error=''
            try:
                from action_state import account_scope
                daily_records=ManualQuestLedger(DATA/'daily_manual.json').snapshot(account_scope(ident,p.get('daily_profile','')))
            except LedgerError as exc:daily_records={};daily_error=str(exc)
            stats=self.history.stats(ident,alternate=p.get('serial',''))
            summary.configure(text=f"오늘 누적 수행 확인 (KST) {stats['today']}건   /   마지막 성공 {short_time(stats['last_success'])}\n실패 {stats['failed_tasks']}건   /   보류 {stats['held_tasks']}건",text_color=GOLD)
            blocked=self.retry_block_reason()
            retry_hint.configure(text=blocked or '일일 작업은 완료한 단계를 유지합니다. 결과가 미확인된 자원 사용은 보류 해결을 먼저 엽니다.')
            retry.configure(state='normal' if retry_tasks(self.players[ident],entries,[task_filter] if task_filter else None) and not blocked else 'disabled')
            rows=[(task,entry) for task,entry in entries.items() if task in TASK_LABELS and (task_filter is None or task==task_filter) and (mode.get()!='확인 필요' or entry.get('result') in ISSUES)]
            if not rows:
                label(body,('해당 작업의 실행 기록이 없습니다.' if task_filter else '기록된 실패/보류 작업이 없습니다.\n연결 미확인은 뮤뮤 연결에서 확인하세요.'),size=12,color=MUTED,wraplength=width-80,justify='left').grid(row=0,column=0,sticky='w',padx=12,pady=30)
            if daily_error:
                summary.configure(text=summary.cget('text')+'\n'+daily_error,text_color=RED)
            for index,(task,entry) in enumerate(rows):
                card=panel(body);card.grid(row=index,column=0,sticky='ew',padx=3,pady=(0,8));card.grid_columnconfigure(0,weight=1)
                text,tone=entry_summary(task,entry)
                chosen=task in DAILY_LABELS or task in selected_tasks(self.players[ident])
                label(card,TASK_LABELS[task]+('' if chosen else ' / 사용 안 함'),size=13,bold=True).grid(row=0,column=0,sticky='w',padx=13,pady=(10,4))
                label(card,text,size=11,color=TONES[tone]).grid(row=0,column=1,sticky='e',padx=13,pady=(10,4))
                daily=entry.get('daily',{});count=daily.get(day,0) if isinstance(daily,dict) else 0
                detail=f"오늘 {count}건   /   최근 성공 {short_time(entry.get('collected_at'))}"
                steps=daily_step_summary(task,daily_records.get(task,{}))
                if steps:detail+='\n'+(daily_error or steps)
                progress=entry.get('progress',{})
                for part in progress.get('steps',{}).values() if isinstance(progress,dict) else []:
                    status={'done':'완료 확인','excluded':'유료 항목 제외','failed':'인식 또는 진행 실패','uncertain':'결과 미확인','blocked':'재시도 보류','not_started':'미실행'}.get(part.get('status'),'확인 중')
                    detail+='\n'+part.get('label','')+': '+status+(' / '+part['reason'] if part.get('reason') else '')
                pending_details=daily_records.get(task,{}).get('_steps',{})
                if isinstance(pending_details,dict):
                    for step,info in pending_details.items():
                        if not isinstance(info,dict) or not info.get('pending'):continue
                        origin=info.get('input_request',{})
                        if not isinstance(origin,dict):origin={}
                        detail+=f"\n{step_label(task,step)} / 최초 입력 요청 {short_time(origin.get('requested_at'))} / 기록 버전 {origin.get('version') or '기록 없음'}"
                if not chosen:detail+='\n작업 설정에서 이 작업을 선택하면 재시도할 수 있습니다.'
                if entry.get('result') in ISSUES:
                    if entry.get('failure_count_version')==2:
                        detail+=f"   /   연속 실패 {entry.get('consecutive_failures',0)}회   /   연속 보류 {entry.get('consecutive_holds',0)}회"
                        legacy=entry.get('legacy_consecutive_issues')
                    else:legacy=entry.get('consecutive_failures')
                    if type(legacy) is int:detail+=f'\n이전 실패/보류 혼합 기록 {legacy}회'
                    elif entry.get('failure_count_version')!=2:detail+='\n이전 기록 / 실패와 보류 횟수 구분 불가'
                label(card,detail,size=10,color=MUTED,wraplength=width-80,justify='left').grid(row=1,column=0,columnspan=2,sticky='w',padx=13,pady=(0,9))
                if task=='daily_dungeons':
                    button(card,'던전 완료 재확인',lambda:self.review_dungeon_completion(ident),width=155,height=29,font=font(10),state='disabled' if blocked else 'normal').grid(row=5,column=0,columnspan=2,sticky='e',padx=13,pady=(0,10))
                if entry.get('result') not in ISSUES:continue
                reason=entry.get('reason') or '이전 버전의 기록입니다. 실행 기록이나 진단 파일에서 원인을 확인해 주세요.'
                label(card,reason,size=11,color=RED,wraplength=width-85,justify='left').grid(row=2,column=0,columnspan=2,sticky='w',padx=13,pady=(0,8))
                actions=ctk.CTkFrame(card,fg_color='transparent');actions.grid(row=3,column=0,columnspan=2,sticky='ew',padx=10,pady=(0,10))
                from app import DATA
                snapshot=failure_snapshot(DATA,ident,task,entry.get('checked_at'),entry.get('run_id'))
                button(actions,'실패 화면' if snapshot else '저장된 실패 화면 없음',lambda item=snapshot:self.failure_image(item),width=150,height=29,font=font(10),state='normal' if snapshot else 'disabled').pack(side='left',padx=3)
                if task in DAILY_LABELS:
                    button(actions,'보류 해결',lambda key=task:self.resolve_history_pending(ident,key),width=90,height=29,font=font(10),state='disabled' if blocked else 'normal').pack(side='left',padx=3)
                hook=getattr(self,'history_resolution_actions',None)
                if hook:hook(actions,ident,task,entry)
                button(actions,'이 작업만 재시도',lambda key=task:self.retry_failed(ident,[key]),primary=True,width=125,height=29,font=font(10),state='normal' if chosen and not blocked else 'disabled').pack(side='right',padx=3)
                if blocked:label(card,blocked,size=10,color=GOLD,wraplength=width-85,justify='left').grid(row=4,column=0,columnspan=2,sticky='w',padx=13,pady=(0,8))
        render();self.history_task_filter=task_filter;self.history_render=render;self.history_mode=mode;self.history_retry_button=retry

    def failure_image(self,snapshot):
        if not snapshot:return
        path,meta=snapshot
        try:
            with Image.open(path) as source:im=source.convert('RGB')
        except OSError as exc:self.status.set('실패 화면을 열지 못했습니다: '+str(exc));return
        win=ctk.CTkToplevel(self.root);win.title('저장된 실패 화면');win.configure(fg_color=BG);win.transient(self.root)
        width,height=fit_window(win,(im.width+24,im.height+60),(400,300))
        im.thumbnail((max(1,width-24),max(1,height-62)))
        photo=ctk.CTkImage(light_image=im,dark_image=im,size=im.size)
        label(win,'캡처 '+short_time(meta.get('created_at'))+' / 현재 화면 아님',size=11,color=MUTED).pack(padx=12,pady=(10,4))
        view=label(win,'',image=photo);view.image=photo;view.pack(padx=12,pady=(0,12))
