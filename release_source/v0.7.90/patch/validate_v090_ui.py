"""Native Windows smoke for v0.7.90 controls, with no ADB or network work."""
import copy
from contextlib import ExitStack
from pathlib import Path
import queue
import threading
from unittest.mock import patch

import customtkinter as ctk
from game_watch import GameWatch
from run_control import RunControl
from task_catalog import REGULAR_LABELS
from ui_layout import fit_window
from validate_run_controls_ui import descendants
from validate_workspace_ui import capture_window


def check(app, output):
    """Exercise real widgets; restore model, Tk variables and windows afterward."""
    root=app.root;output=Path(output)
    assert not app.busy(), 'v0.7.90 UI smoke requires an idle app'
    assert not (app.watch_thread and app.watch_thread.is_alive()), 'Recovery must be idle'
    assert not (app.update_thread and app.update_thread.is_alive()), 'Update worker must be idle'
    assert not app.update_continue_scheduled, 'Update continuation must be idle'
    geometry=root.geometry()
    variable_names=('watch_value','status','countdown','serial_value','connection_text','device_info',
                    'fleet_summary','scope_value','minutes','restore','roster_query','roster_filter',
                    'update_mode_value','update_notes','update_message')
    variables={name:getattr(app,name).get() for name in variable_names}
    selected={key:value.get() for key,value in app.selected.items()}
    button_options={name:{key:getattr(app,name).cget(key) for key in ('text','state','text_color')}
                    for name in ('pause_button','update_button')}
    watch_text=app.watch_status.cget('text')
    window_names=('fleet_window','connection_window','update_window')
    old_windows={name:getattr(app,name,None) for name in window_names}
    hidden=[];created=[]
    for window in old_windows.values():
        if window is not None and window.winfo_exists() and window.state()!='withdrawn':
            hidden.append((window,window.state()));window.withdraw()
    ident='v090-ui-fixture'
    player={'name':'연결·안전 설정 검사','serial':'','enabled':True,'minutes':60,
            'selected':{key:key=='farm' for key in REGULAR_LABELS},'daily_selected':{'daily_guild':True},
            'restore_sleep':True,'daily_profile':'','account_profiles':['저장 본캐','저장 부캐']}
    config=copy.deepcopy(app.config);config.pop('update_mode',None)
    config.update(update_check=False,run_scope='regular',game_watch=True)
    saved=[]
    def save_snapshot():
        saved.append(copy.deepcopy({'players':app.players,'config':app.config}))
    def forbidden(*args,**kwargs):
        raise AssertionError('UI smoke must not start ADB, network or update work')
    replacements={
        'players':{ident:player},'fleet_states':{ident:{'next_at':12345}},'view_id':ident,
        'device_reports':{},'device_options':{},'unavailable_devices':set(),
        'config':config,'stop':RunControl(),'game_watch':GameWatch(lambda _:None),
        'events':queue.Queue(),'live_watch':False,'active_instance':None,'next_at':12345,
        'pause_allowed':False,'finish_text':'','preview_image':None,'compact_details':False,
        'roster_collapsed':False,'update_info':None,'update_meta':None,'update_work':None,
        'update_pending':threading.Event(),'update_requested':False,'update_explicit_apply':False,
        'update_manual_retry':False,'update_applying':False,'update_apply_button':None,
        'fleet_window':None,'connection_window':None,'update_window':None,
        'save':save_snapshot,'log':lambda _:None,'connect':forbidden,'run_worker':forbidden,
        'check_updates':forbidden,'download_update':forbidden,'apply_update':forbidden,
    }
    # References restored by the stack are deliberately not copied: controls,
    # locks, recovery bookkeeping and pre-existing windows belong to the app.
    restore_attributes=('settings_editor','hotkey_label','roster_signature','_layout_signature',
                        'workflow_plan','workflow_error','_workflow_refresh','history_control_state',
                        'compact_layout')
    for name in restore_attributes:
        if hasattr(app,name):replacements[name]=getattr(app,name)
    try:
        with ExitStack() as stack:
            for name,value in replacements.items():stack.enter_context(patch.object(app,name,value,create=True))
            stack.enter_context(patch('ui_updates.check_feed',side_effect=forbidden))
            stack.enter_context(patch('ui_updates.download_update',side_effect=forbidden))
            stack.enter_context(patch('exe_updater.policy_blocked',return_value=False))
            try:
                app.watch_value.set(True);app.game_watch.enable(True)
                app.scope_value.set('일반 작업');app.roster_query.set('');app.roster_filter.set('전체')
                app.serial_value.set('');app.update_mode_value.set(app.update_mode())
                app.watch_status.configure(text='게임 자동 복구 보류 / 뮤뮤 연결 주소와 실행 중인 게임 화면을 확인하지 못했습니다. 연결 설정에서 진단한 뒤 다시 시도하세요.')
                fit_window(root,(680,800));root.update();app.apply_layout();app.render_roster(force=True);root.update()
                stop=app.stop_all_button
                assert stop.winfo_ismapped(), 'Complete stop is hidden at 680 px'
                assert stop.winfo_rootx()>=root.winfo_rootx()
                assert stop.winfo_rootx()+stop.winfo_width()<=root.winfo_rootx()+root.winfo_width()
                assert stop.winfo_rooty()+stop.winfo_height()<=root.winfo_rooty()+root.winfo_height()
                assert stop.cget('state')=='normal'
                stop.invoke();root.update()
                assert app.stop.is_set() and not app.game_watch.enabled
                assert not app.watch_value.get() and app.config['game_watch'] is False
                assert app.next_at is None and app.fleet_states[ident]['next_at'] is None
                assert saved[-1]['config']['game_watch'] is False
                capture_window(root,output.with_name('review-v090-stop.png'))
                app.stop.clear();saved.clear()

                app.fleet_dialog(ident);root.update();editor=app.settings_editor;created.append(editor.window)
                assert isinstance(editor.account_entry,ctk.CTkComboBox)
                assert editor.account_entry.cget('values')==['','저장 본캐','저장 부캐']
                assert editor.daily_profile.get()=='' and editor.guild_paid_limit.get()=='0'
                assert editor.donation_limit_menu.cget('values')==[str(n) for n in range(0,751,50)]
                before=copy.deepcopy(app.players)
                editor.account_entry._dropdown_callback('저장 부캐')
                editor.donation_limit_menu._dropdown_callback('50')
                with patch('ui_player_settings.messagebox.askyesno',return_value=False):
                    assert editor.apply() is False
                assert app.players==before and saved==[], 'Declined spending consent changed persisted settings'
                assert editor.window.winfo_exists() and '적용하지 않았습니다' in editor.error.cget('text')
                with patch('ui_player_settings.messagebox.askyesno',return_value=True):
                    assert editor.apply() is True
                assert app.players[ident]['daily_profile']=='저장 부캐'
                assert app.players[ident]['guild_paid_limit']==50
                assert saved[-1]['players'][ident]['guild_paid_limit']==50
                assert saved[-1]['players'][ident]['daily_profile']=='저장 부캐'
                app.fleet_dialog(ident);root.update();editor=app.settings_editor;created.append(editor.window)
                assert editor.guild_paid_limit.get()=='50' and editor.daily_profile.get()=='저장 부캐'
                editor.body._parent_canvas.yview_moveto(1);root.update()
                capture_window(editor.window,output.with_name('review-v090-accounts.png'))
                editor.account_entry._dropdown_callback('');editor.donation_limit_menu._dropdown_callback('0')
                with patch('ui_player_settings.messagebox.askyesno',side_effect=AssertionError('Free-only default must not request spending consent')):
                    assert editor.apply() is True
                assert saved[-1]['players'][ident]['daily_profile']==''
                assert saved[-1]['players'][ident]['guild_paid_limit']==0
                assert saved[-1]['players'][ident]['account_profiles']==['저장 본캐','저장 부캐']

                labels=[app.more_menu.entrycget(i,'label') for i in range(app.more_menu.index('end')+1)]
                assert '뮤뮤 연결 설정 · 진단' in labels
                app.more_menu.invoke(labels.index('뮤뮤 연결 설정 · 진단'));root.update()
                window=app.connection_window;created.append(window)
                texts=[str(w.cget('text')) for w in descendants(window) if isinstance(w,(ctk.CTkLabel,ctk.CTkButton))]
                for expected in ('ADB 실행 파일','로컬 주소 또는 포트 (선택)','자동 탐색','설정 저장','저장 후 연결 진단'):
                    assert expected in texts, 'Missing connection control: '+expected
                for expected in ('1. 뮤뮤 탐색','2. ADB · 기기 연결','3. 실행 중인 게임','4. 화면 캡처 · 인식'):
                    assert any(text.startswith(expected) for text in texts), 'Missing diagnosis stage: '+expected
                assert any('미확인' in text for text in texts)
                capture_window(window,output.with_name('review-v090-connection.png'))
                window.destroy();root.update()

                app.updates_dialog();root.update();window=app.update_window;created.append(window)
                radios=[w for w in descendants(window) if isinstance(w,ctk.CTkRadioButton)]
                assert {w.cget('text') for w in radios}=={'알림만 받기','자동으로 적용하기'}
                assert app.update_mode()=='notify' and app.update_mode_value.get()=='notify'
                assert app.update_apply_button.cget('state')=='disabled'
                app.update_apply_button.invoke()
                assert not app.update_requested and not app.update_explicit_apply
                release={'version':'9.90.0','notes':'연결 설정과 진단 추가\n완전 중지와 계정별 안전 설정 개선'}
                app.handle_update_event('update_checked',release);root.update()
                assert app.update_notes.get()==release['notes']
                notes=[w for w in descendants(window) if isinstance(w,ctk.CTkLabel)
                       and str(w.cget('textvariable'))==str(app.update_notes)]
                assert len(notes)==1 and notes[0].winfo_ismapped()
                assert app.update_apply_button.cget('state')=='normal'
                assert not app.update_requested and not app.update_explicit_apply and not app.update_pending.is_set()
                capture_window(window,output.with_name('review-v090-updates.png'))
                app.update_info=None;app.refresh_update_controls()
                assert app.update_apply_button.cget('state')=='disabled'
            finally:
                for window in reversed(created):
                    if window.winfo_exists():window.destroy()
                for name in window_names:
                    window=getattr(app,name,None)
                    if window is not None and window.winfo_exists():window.destroy()
    finally:
        for name,value in variables.items():getattr(app,name).set(value)
        for key,value in selected.items():app.selected[key].set(value)
        for name,options in button_options.items():getattr(app,name).configure(**options)
        app.watch_status.configure(text=watch_text)
        root.geometry(geometry);app.update_fleet_summary();app.refresh_workflow(force=True)
        app.render_roster(force=True);app.apply_layout();app.sync_stop_key();root.update()
        # A redraw can update derived summaries; restore the original text too.
        for name,value in variables.items():getattr(app,name).set(value)
        for window,state in hidden:
            if window.winfo_exists():window.state(state)
