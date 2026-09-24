"""Per-player results, failure evidence and explicit failed-task retries."""
from datetime import datetime
import tkinter as tk
import customtkinter as ctk
from PIL import Image
from diagnostics import failure_snapshot
from history import ISSUES,history_day
from task_catalog import TASK_LABELS
from ui_state import selected_tasks,task_summary,short_time,retry_tasks,daily_step_summary
from ui_theme import BG,PANEL,MUTED,TEXT,GOLD,RED,TONES,font,label,heading,button,panel,GameTabs
from ui_layout import fit_window


class HistoryUI:
    def history_entries(self,ident):
        p=self.players.get(ident,{})
        return self.history.snapshot(ident,p.get('serial',''))

    def retry_failed(self,ident,requested=None):
        if self.busy() or self.update_pending.is_set() or self.update_applying:return
        p=self.players.get(ident)
        if not p:return
        tasks=retry_tasks(p,self.history_entries(ident),requested)
        if not tasks:self.status.set('현재 선택된 작업 중 재시도할 실패 항목이 없습니다.');return
        self.select_player(ident)
        win=getattr(self,'history_window',None)
        if win is not None and win.winfo_exists():win.destroy()
        self.launch('retry',{ident:tasks})

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
        label(footer,'오늘 완료 건수는 v0.7.11 이후 확인된 작업부터 집계합니다.',size=10,color=MUTED,wraplength=width-48,justify='left').grid(row=0,column=0,columnspan=3,sticky='w',pady=(0,10))
        retry=button(footer,'실패 작업만 재시도',lambda:self.retry_failed(ident,[task_filter] if task_filter else None),primary=True,width=158)
        retry.grid(row=1,column=1,padx=(8,8));button(footer,'닫기',win.destroy,width=78).grid(row=1,column=2)
        def render():
            if not win.winfo_exists():return
            for child in body.winfo_children():child.destroy()
            if ident not in self.players:
                win.destroy();return
            entries=self.history_entries(ident);day=history_day()
            from app import DATA
            from daily_state import ManualQuestLedger,LedgerError
            daily_error=''
            try:
                from action_state import account_scope
                daily_records=ManualQuestLedger(DATA/'daily_manual.json').snapshot(account_scope(ident,p.get('daily_profile','')))
            except LedgerError as exc:daily_records={};daily_error=str(exc)
            stats=self.history.stats(ident,alternate=p.get('serial',''))
            summary.configure(text=f"오늘 완료 (KST) {stats['today']}건   /   마지막 성공 {short_time(stats['last_success'])}")
            blocked=self.busy() or self.update_pending.is_set() or self.update_applying
            retry.configure(state='normal' if retry_tasks(self.players[ident],entries,[task_filter] if task_filter else None) and not blocked else 'disabled')
            rows=[(task,entry) for task,entry in entries.items() if task in TASK_LABELS and (task_filter is None or task==task_filter) and (mode.get()!='확인 필요' or entry.get('result') in ISSUES)]
            if not rows:
                label(body,('해당 작업의 실행 기록이 없습니다.' if task_filter else '기록된 실패 작업이 없습니다.\n연결 미확인은 뮤뮤 연결에서 확인하세요.'),size=12,color=MUTED,wraplength=width-80,justify='left').grid(row=0,column=0,sticky='w',padx=12,pady=30)
            if daily_error:
                summary.configure(text=summary.cget('text')+'\n'+daily_error,text_color=RED)
            for index,(task,entry) in enumerate(rows):
                card=panel(body);card.grid(row=index,column=0,sticky='ew',padx=3,pady=(0,8));card.grid_columnconfigure(0,weight=1)
                text,tone=task_summary(task,entry.get('result'))
                chosen=task.startswith('daily_') or task in selected_tasks(self.players[ident])
                label(card,TASK_LABELS[task]+('' if chosen else ' / 사용 안 함'),size=13,bold=True).grid(row=0,column=0,sticky='w',padx=13,pady=(10,4))
                label(card,text,size=11,color=TONES[tone]).grid(row=0,column=1,sticky='e',padx=13,pady=(10,4))
                daily=entry.get('daily',{});count=daily.get(day,0) if isinstance(daily,dict) else 0
                detail=f"오늘 {count}건   /   최근 성공 {short_time(entry.get('collected_at'))}"
                steps=daily_step_summary(task,daily_records.get(task,{}))
                if steps:detail+='\n'+(daily_error or steps)
                if entry.get('result') in ISSUES:
                    failures=entry.get('consecutive_failures')
                    detail+=f'   /   연속 실패 {failures}회' if type(failures) is int else '   /   이전 실패 기록'
                label(card,detail,size=10,color=MUTED,wraplength=width-80,justify='left').grid(row=1,column=0,columnspan=2,sticky='w',padx=13,pady=(0,9))
                if entry.get('result') not in ISSUES:continue
                reason=entry.get('reason') or '이전 버전의 기록입니다. 실행 기록이나 진단 파일에서 원인을 확인해 주세요.'
                label(card,reason,size=11,color=RED,wraplength=width-85,justify='left').grid(row=2,column=0,columnspan=2,sticky='w',padx=13,pady=(0,8))
                actions=ctk.CTkFrame(card,fg_color='transparent');actions.grid(row=3,column=0,columnspan=2,sticky='ew',padx=10,pady=(0,10))
                from app import DATA
                snapshot=failure_snapshot(DATA,ident,task,entry.get('checked_at'),entry.get('run_id'))
                button(actions,'실패 화면' if snapshot else '저장된 실패 화면 없음',lambda item=snapshot:self.failure_image(item),width=150,height=29,font=font(10),state='normal' if snapshot else 'disabled').pack(side='left',padx=3)
                button(actions,'이 작업만 재시도',lambda key=task:self.retry_failed(ident,[key]),primary=True,width=125,height=29,font=font(10),state='normal' if chosen and not blocked else 'disabled').pack(side='right',padx=3)
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
