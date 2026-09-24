"""Explicit, scoped resolution of outcomes that the game cannot verify again."""
import copy
from pathlib import Path
from daily_state import ManualQuestLedger,DailyLedger,DAILY_TASKS,DAILY_STEPS,step_label,korea_now
from action_state import ActionState,account_scope


def _ledger(data,scope):
    ledger=ManualQuestLedger(Path(data)/'daily_manual.json')
    legacy=Path(data)/'daily_tasks.json'
    if scope not in ledger.data and legacy.exists():
        old=DailyLedger(legacy);tasks={}
        for day in sorted(old.data.get(scope,{})):
            tasks.update(old.snapshot(scope,day))
        ledger.data[scope]={'manual':copy.deepcopy(tasks)}
    return ledger


def retry_ledger(data,scope,tasks):
    selected=[task for task in tasks if task in DAILY_TASKS]
    if not selected:return None
    ledger=_ledger(data,scope)
    for task in selected:
        ledger.update(scope,task,{})
        ledger.reset_blocked(scope,task)
    return ledger


def pending_choices(data,scope,task):
    if task=='training':
        state=ActionState(Path(data)/'action_state.json',scope);entry=state.get(task)
        return [{'step':'claim','label':'수련 결과','record':entry}] if state.pending(task) else []
    if task not in DAILY_TASKS:return []
    ledger=_ledger(data,scope);entry=ledger.snapshot(scope).get(task,{})
    choices=[]
    for step in DAILY_STEPS[task]:
        if (task,step)==('daily_guild','raid'):continue
        detail=ledger.detail(scope,task,step)
        if detail.get('pending'):
            choices.append({'step':step,'label':step_label(task,step),'record':entry})
    return choices


def resolve_choice(data,scope,task,choice,outcome,*,confirmed=False):
    if not confirmed or outcome not in {'completed','not_executed'}:
        raise ValueError('게임에서 해당 작업의 결과를 직접 확인한 뒤 선택해 주세요.')
    if choice not in pending_choices(data,scope,task):
        raise ValueError('작업 기록이 변경되었습니다. 기록창을 다시 열어 확인해 주세요.')
    prior=choice['record']
    previous=(prior.get('pending',{}).get('claim') if task=='training' else
              {'value':prior.get(choice['step']),
               'pending':prior.get('_steps',{}).get(choice['step'],{}).get('pending')})
    stamp={'outcome':outcome,'at':korea_now().isoformat(timespec='milliseconds'),
           'source':'user_confirmed','prior':copy.deepcopy(previous)}
    if task=='training':
        state=ActionState(Path(data)/'action_state.json',scope)
        state.confirm(task,status='done' if outcome=='completed' else 'not_executed',
                      source='user_confirmed',manual_resolution=stamp,blocked=False,failures=0,fingerprint='')
        return outcome=='completed'
    ledger=_ledger(data,scope);step=choice['step'];complete=outcome=='completed'
    # Keep earlier confirmed donations when only the last dispatched input was absent.
    values={step:'done' if complete else None,'_complete':None}
    if step=='donation' and not complete:
        prior=choice['record'];paid=prior.get('donation_paid') or 0;verified=prior.get('donation_verified') or 0
        values['donation_paid']=max(verified,paid-1)
    group_done=complete and all(s==step or ledger.done(scope,task,s) for s in DAILY_STEPS[task])
    if group_done:values['_complete']='done'
    ledger.checkpoint(scope,task,step,'done' if complete else 'pending',values=values,
                      pending=None,failures=0,fingerprint='',manual_resolution=stamp)
    return group_done


def show_resolution(app,ident,task):
    import tkinter as tk
    import customtkinter as ctk
    from tkinter import messagebox
    from app import DATA
    from task_catalog import TASK_LABELS
    from ui_theme import BG,GOLD,MUTED,font,label,heading,button
    from ui_layout import fit_window
    blocked=app.retry_block_reason()
    if blocked:app.status.set(blocked);return
    player=app.players.get(ident)
    if not player:return
    scope=account_scope(ident,player.get('daily_profile',''))
    try:choices=pending_choices(DATA,scope,task)
    except Exception as exc:messagebox.showerror('기록 확인',str(exc));return
    if not choices:
        messagebox.showinfo('보류 해결','결과 확인이 필요한 입력 기록이 없습니다. 실패 작업 재시도를 이용해 주세요.');return
    win=ctk.CTkToplevel(app.root);win.title('보류 결과 확인');win.configure(fg_color=BG);win.transient(app.root)
    width,_=fit_window(win,(570,450),(480,410))
    heading(win,player.get('name','뮤뮤')+' / '+TASK_LABELS[task],size=20,wraplength=width-44).pack(anchor='w',padx=22,pady=(20,12))
    label(win,'이전 입력의 결과를 확인하지 못해 보류된 작업입니다.\n게임에서 선택한 항목 전체의 완료 여부를 확인해 주세요.\n미실행으로 선택하면 해당 항목을 다시 실행할 수 있습니다.',
          color=MUTED,wraplength=width-44,justify='left').pack(anchor='w',padx=22,pady=(0,14))
    selected=tk.StringVar(value=choices[0]['label']);confirmed=tk.BooleanVar(value=False)
    ctk.CTkOptionMenu(win,variable=selected,values=[c['label'] for c in choices],width=width-44,
                      command=lambda _:confirmed.set(False)).pack(padx=22,pady=8)
    ctk.CTkCheckBox(win,text='게임에서 이 항목의 결과를 직접 확인했습니다.',variable=confirmed,font=font(12)).pack(anchor='w',padx=22,pady=16)
    def apply(outcome):
        try:
            blocked=app.retry_block_reason()
            if blocked:raise ValueError(blocked)
            current=app.players.get(ident)
            if not current or account_scope(ident,current.get('daily_profile',''))!=scope:
                raise ValueError('선택 계정이 변경되었습니다. 기록창을 다시 열어 주세요.')
            choice=next(c for c in choices if c['label']==selected.get())
            complete=resolve_choice(DATA,scope,task,choice,outcome,confirmed=confirmed.get())
            reason=choice['label']+' / 사용자 결과 확인: '+('완료' if outcome=='completed' else '미실행')
            app.log(reason)
            if complete:app.history.record(ident,task,'already_complete',reason=reason)
            app.status.set(reason);app.request_history_refresh()
        except Exception as exc:messagebox.showerror('보류 결과 확인',str(exc),parent=win);return
        win.destroy()
        if outcome=='not_executed':app.retry_failed(ident,[task])
    button(win,'완료 확인 반영',lambda:apply('completed'),primary=True,width=width-44).pack(padx=22,pady=4)
    button(win,'미실행 확인 후 재시도',lambda:apply('not_executed'),width=width-44).pack(padx=22,pady=4)
    button(win,'취소',win.destroy,width=100).pack(pady=8)
    win.after(100,lambda:win.grab_set() if win.winfo_exists() else None)
    return win
