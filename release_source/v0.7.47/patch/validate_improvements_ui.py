"""Native controls, short Windows key events, draft merges and failure UI."""
import copy
import ctypes
from datetime import datetime
import gc
from pathlib import Path
import threading
import time
from unittest.mock import Mock,patch
import numpy as np
import customtkinter as ctk
from mumu_names import name_options
from task_catalog import TASK_LABELS,REGULAR_LABELS
from validate_run_controls_ui import descendants
from validate_workspace_ui import capture_window
from ui_layout import fit_window,work_area


def check(app,output):
    root=app.root;output=Path(output)
    from history import History
    history_path=output.with_name(output.stem+'-improvement-history.json');history_path.unlink(missing_ok=True)
    app.history=History(history_path)
    def pump(predicate,timeout=3):
        deadline=time.monotonic()+timeout
        while not predicate() and time.monotonic()<deadline:root.update();time.sleep(.01)
        assert predicate(),'Native improvement UI did not reach expected state'
        root.update()
    app.players={};app.device_reports={};app.device_options={};app.fleet_states={};app.view_id=None
    for i in range(3):
        ident=f'{i+1:024x}';serial=f'127.0.0.1:{16384+32*i}'
        app.players[ident]={'name':['본캐','부캐 1','부캐 2'][i],'serial':serial,'enabled':i==0,'minutes':60,
                            'selected':{task:task in {'farm','ranking'} for task in TASK_LABELS},'restore_sleep':True}
        app.device_reports[serial]={'instance_id':ident,'window_name':app.players[ident]['name'],'image':None,'state':'unknown','package':'fixture'}
    app.device_options=name_options(list(app.device_reports),app.device_reports)
    a,b,c=app.players;app.select_player(a);root.update()
    app.fleet_dialog(a);root.update();editor=app.settings_editor
    texts=[w.cget('text') for w in descendants(editor.window) if isinstance(w,(ctk.CTkLabel,ctk.CTkButton,ctk.CTkSwitch))]
    assert '작업을 마치면 게임 절전 모드로 복귀' not in texts
    assert '수령할 작업' in texts and '자원 시설' not in texts and '추가 작업' not in texts
    assert set(editor.task_checks)==set(REGULAR_LABELS)
    assert editor.task_checks['autumn'].cget('text')=='가을맞이 수령'
    assert not editor.tasks['autumn'].get()
    editor.tasks['autumn'].set(True);editor.capture();editor.select(b);editor.select(a)
    assert editor.tasks['autumn'].get() and not app.players[a]['selected']['autumn']
    assert all(w.master is editor.task_group for w in editor.task_checks.values())
    assert editor.interval_presets.cget('values')==['1시간','2시간','3시간']
    for title,minutes in [('1시간','60'),('2시간','120'),('3시간','180')]:
        editor.interval_presets._dropdown_callback(title)
        assert editor.minutes.get()==minutes and editor.interval_presets.get()==title
    editor.select(b);assert editor.interval_presets.get()=='1시간'
    editor.select(a);assert editor.minutes.get()=='180' and editor.interval_presets.get()=='3시간'
    editor.minutes.set('45');assert editor.interval_presets.get()=='직접 입력'
    editor.select_all_button.invoke();assert all(v.get() for v in editor.tasks.values())
    editor.clear_all_button.invoke();assert not any(v.get() for v in editor.tasks.values())
    assert editor.apply() and not any(app.players[a]['selected'].values())
    app.fleet_dialog(a);root.update();editor=app.settings_editor
    editor.tasks['farm'].set(True);editor.tasks['ranking'].set(True);editor.minutes.set('30')
    app.roster_rows[b]['enabled'].set(True);app.toggle_player(b)
    assert editor.apply() and app.players[b]['enabled'] and app.players[a]['minutes']==30
    app.fleet_dialog(a);root.update();editor=app.settings_editor
    editor.minutes.set('15');editor.bulk_dialog();root.update()
    editor.bulk_targets[b].set(True);editor.bulk_targets[c].set(True);editor.bulk_apply();root.update()
    assert editor.draft[b]['minutes']=='15' and app.players[b]['minutes']==60
    assert editor.draft[c]['enabled'] is False
    editor.interval_presets._dropdown_callback('2시간')
    root.update()
    editor.daily_profile.set('검증 캐릭터');editor.capture()
    assert editor.draft[editor.active]['daily_profile']=='검증 캐릭터'
    capture_window(editor.window,output.with_name('review-settings-top.png'))
    autumn=editor.task_checks['autumn'];viewport=editor.body._parent_canvas
    target=autumn.winfo_rooty()-editor.body.winfo_rooty()
    viewport.yview_moveto(max(0,(target-35)/editor.body.winfo_height()));root.update()
    assert viewport.winfo_rooty()<=autumn.winfo_rooty()
    assert autumn.winfo_rooty()+autumn.winfo_height()<=viewport.winfo_rooty()+viewport.winfo_height()
    capture_window(editor.window,output.with_name('review-settings.png'))
    assert editor.apply() and app.players[b]['minutes']==15 and not app.players[c]['enabled']
    assert app.players[a]['daily_profile']=='검증 캐릭터'
    assert not app.players[b].get('daily_profile')
    assert all(p['restore_sleep'] for p in app.players.values())
    # Verify cancellation from a <150 ms native key event without servicing Tk.
    assert app.hotkey_listener is not None and app.hotkey_listener.ready.is_set() and app.hotkey_listener.error is None
    original=app.stop_hotkey.value;app.apply_stop_hotkey('F9')
    seen=[];binding=root.bind('<KeyPress-F9>',lambda event:seen.append(event.keysym),add='+')
    root.lift();root.focus_force();root.update();gc.collect()
    started=threading.Event()
    def work():started.set();app.stop.wait(5)
    app.run_worker(work,'중지 키 검사',pausable=True);assert started.wait(2)
    user=ctypes.windll.user32
    user.keybd_event(0x78,0,0,0);time.sleep(.02);user.keybd_event(0x78,0,2,0)
    assert app.stop.is_set(),'Short native stop key was missed'
    app.worker.join(2);app.poll();assert not app.busy()
    pump(lambda:bool(seen));app.poll();root.unbind('<KeyPress-F9>',binding)
    app.apply_stop_hotkey(original)
    # Actual history cards and one-task retry routing, with no ADB game input.
    stamp=datetime.now().astimezone().isoformat(timespec='seconds')
    app.history.record(a,'farm','collected',now=stamp)
    app.history.record(a,'ranking','failed',now=stamp,reason='랭킹 보상 버튼 상태를 확인하지 못했습니다.')
    app.history.record(a,'ranking','failed',now=stamp,reason='랭킹 보상 버튼 상태를 확인하지 못했습니다.')
    from app import DATA
    from diagnostics import save_collection_failure
    from types import SimpleNamespace
    im=np.full((540,960,3),150,dtype=np.uint8)
    save_collection_failure(DATA,a,im,SimpleNamespace(state='ranking',diagnostics={}), '랭킹 보상 버튼 상태를 확인하지 못했습니다.','ranking')
    app.history_dialog(a,issues_only=True);root.update()
    texts=[w.cget('text') for w in descendants(app.history_window) if isinstance(w,(ctk.CTkLabel,ctk.CTkButton))]
    assert any('연속 실패 2회' in t for t in texts)
    assert '랭킹 보상 버튼 상태를 확인하지 못했습니다.' in texts
    assert any(isinstance(w,ctk.CTkButton) and w.cget('text')=='실패 화면' and w.cget('state')=='normal' for w in descendants(app.history_window))
    app.players[a]['selected']['daily_dungeons']=True
    app.history.record(a,'daily_dungeons','deferred',reason='보물 창고: 같은 오류 반복으로 보류')
    with patch('daily_state.ManualQuestLedger') as ledger:
        ledger.return_value.snapshot.return_value={'daily_dungeons':{
            'equipment':'done','summon':'done','stone':'done','rune':'done','relic':'done',
            '_steps':{'treasure':{'status':'blocked'}}}}
        app.history_dialog(a,issues_only=True);root.update()
        texts=[w.cget('text') for w in descendants(app.history_window) if isinstance(w,(ctk.CTkLabel,ctk.CTkButton))]
        assert any('5/7 완료' in t and '보물 창고: 재시도 보류' in t and '아티팩트 공방: 미실행' in t for t in texts)
        capture_window(app.history_window,output.with_name('review-history.png'))
    original_launch=app.launch;spy=Mock();app.launch=spy
    try:
        app.retry_failed(a,['farm','ranking','training'])
        spy.assert_called_once_with('retry',{a:['ranking']})
    finally:app.launch=original_launch
    # Render the real outcome dialog and prove an unchecked attestation cannot
    # clear pending input. This fixture never sends any game input.
    from retry_resolution import show_resolution
    from daily_state import ManualQuestLedger
    from action_state import account_scope
    scope=account_scope(a,app.players[a].get('daily_profile',''))
    pending=ManualQuestLedger(DATA/'daily_manual.json')
    pending.mark(scope,'daily_guild','raid','started')
    dialog=show_resolution(app,a,'daily_guild');root.update()
    controls=[w for w in descendants(dialog) if isinstance(w,ctk.CTkButton)]
    complete=next(w for w in controls if w.cget('text')=='완료 확인 반영')
    with patch('tkinter.messagebox.showerror') as error:
        complete.invoke();error.assert_called_once()
    assert ManualQuestLedger(DATA/'daily_manual.json').get(scope,'daily_guild','raid')=='started'
    for control in controls:
        assert control.winfo_ismapped()
        assert control.winfo_rooty()+control.winfo_height()<=dialog.winfo_rooty()+dialog.winfo_height()
    capture_window(dialog,output.with_name('review-resolution.png'))
    next(w for w in descendants(dialog) if isinstance(w,ctk.CTkCheckBox)).select()
    complete.invoke();root.update()
    assert ManualQuestLedger(DATA/'daily_manual.json').done(scope,'daily_guild','raid')
    app.render_roster(force=True);root.update()
    assert app.roster_rows[a]['status'].cget('text')=='확인 필요'
    assert '오늘 완료' in app.detail_stats.cget('text')
    # Settings footer and task controls remain reachable on the actual work area.
    ctk.set_widget_scaling(1.5);ctk.set_window_scaling(1.5);fit_window(root);root.update();app.apply_layout()
    app.fleet_dialog(a);root.update();editor=app.settings_editor
    left,top,right,bottom=work_area(editor.window)
    assert editor.window.winfo_rootx()+editor.window.winfo_width()<=right+2
    assert editor.window.winfo_rooty()+editor.window.winfo_height()<=bottom+2
    assert editor.save_button.winfo_rooty()+editor.save_button.winfo_height()<=bottom+2
    editor.window.destroy();ctk.set_widget_scaling(1);ctk.set_window_scaling(1);fit_window(root);root.update();app.apply_layout();root.update()
