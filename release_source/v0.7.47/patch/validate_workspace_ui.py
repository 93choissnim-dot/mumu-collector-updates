"""Real Windows layout, roster routing, draft isolation, and preview captures."""
import copy
import threading
import time
from pathlib import Path
import customtkinter as ctk
from PIL import ImageGrab
from mumu_names import name_options
from task_catalog import TASK_LABELS
from validate_run_controls_ui import descendants
from ui_layout import fit_window,work_area


def capture_window(root,path):
    root.lift();root.update()
    ImageGrab.grab(window=root.winfo_id()).save(path)


def check(app,output):
    root=app.root;output=Path(output)
    app.config['update_check']=False
    app.players={};reports={}
    for i in range(12):
        ident=f'preview-{i}';serial=f'127.0.0.1:{16384+32*i}'
        name=['본캐 / 메인','부캐 / 자원 수령','길고 긴 뮤뮤 플레이어 이름을 확인하는 계정'][i] if i<3 else f'부캐 {i:02d}'
        app.players[ident]={'name':name,'serial':serial,'enabled':i<3,'minutes':30 if i==0 else 60,
                            'selected':{task:task!='training' for task in TASK_LABELS},'restore_sleep':True}
        if i<10:reports[serial]={'instance_id':ident,'window_name':name,'package':'game','image':None,'state':'unknown','error':'','package_error':''}
    app.device_reports=reports;app.device_options=name_options(list(reports),reports);app.view_id=None
    app.select_player('preview-0');app.render_roster(force=True);root.update()
    assert len(app.roster_rows)==12
    assert app.roster_panel.winfo_ismapped() and app.detail_panel.winfo_ismapped()
    original=copy.deepcopy(app.players)
    app.toggle_compact_details();root.update()
    assert not app.roster_panel.winfo_ismapped() and app.detail_panel.winfo_ismapped()
    assert app.players==original and app.view_id=='preview-0'
    app.toggle_compact_details();root.update()
    root.geometry('820x640+0+0');root.update();app.apply_layout();root.update()
    assert app.roster_panel.winfo_ismapped() and not app.detail_panel.winfo_ismapped()
    app.select_player('preview-1');root.update()
    assert app.detail_panel.winfo_ismapped() and not app.roster_panel.winfo_ismapped()
    assert app.players==original
    app.show_roster();root.update()
    assert app.roster_panel.winfo_ismapped()
    root.geometry('1220x820+0+0');root.update();app.apply_layout();root.update()
    app.select_player('preview-0')
    app.roster_query.set('길고 긴');root.update();assert list(app.roster_rows)==['preview-2']
    app.roster_query.set('');app.roster_filter.set('실행 대상');app.render_roster(force=True);root.update()
    assert len(app.roster_rows)==3
    app.roster_filter.set('전체');app.render_roster(force=True);root.update()
    # A non-selected player's frame must never replace the selected detail.
    import numpy as np
    first=np.full((540,960,3),20,dtype=np.uint8);other=np.full_like(first,220)
    first_serial=app.players['preview-0']['serial'];other_serial=app.players['preview-1']['serial']
    app.events.put(('device_checked',(first_serial,{**reports[first_serial],'image':first,'state':'menu'})));app.poll()
    app.events.put(('device_checked',(other_serial,{**reports[other_serial],'image':other,'state':'menu'})));app.poll()
    assert app.view_id=='preview-0' and int(app.preview_image[0,0,0])==20
    app.select_player('preview-1');assert int(app.preview_image[0,0,0])==220
    app.select_player('preview-11');assert app.preview_image is None and app.chosen_serial()==''
    app.select_player('preview-0')
    app.device_reports[first_serial]['image']=None;app.on_device_changed()
    for task,result in [('farm','collected'),('wood','collected'),('mine','skipped'),('ranking','attempted'),('worldboss','collected')]:
        app.history.record('preview-0',task,result,now='2026-09-20T17:20:00+09:00')
    app.fleet_states={'preview-0':{'status':'확인 완료','next_at':app.stop.clock()+540,'results':{'farm':'collected'}},
                      'preview-1':{'status':'확인 필요','results':{'ranking':'attempted'},'next_at':app.stop.clock()+120}}
    app.render_roster(force=True);root.update()
    assert app.detail_results['ranking'].cget('text')=='완료 미확인'
    app.detail_results['ranking'].invoke();root.update()
    assert app.history_task_filter=='ranking'
    assert '완료 미확인' in [w.cget('text') for w in descendants(app.history_window) if isinstance(w,ctk.CTkLabel)]
    app.history_window.destroy()
    app.detail_summary[0].invoke();root.update()
    assert app.history_task_filter is None and app.history_mode.get()=='확인 필요'
    app.history_window.destroy()
    assert app.display_task_order[0]=='worldboss'
    assert app.display_task_order.index('ranking')<app.display_task_order.index('farm')
    app.roster_filter.set('확인 필요');app.render_roster(force=True)
    assert 'preview-1' in app.roster_rows and 'preview-10' in app.roster_rows
    app.show_roster();root.update()
    # Inspecting and discarding settings must leave all saved profiles intact.
    saved=copy.deepcopy(app.players)
    app.fleet_dialog('preview-0');root.update();editor=app.settings_editor
    assert not any(key.startswith('daily_') for key in editor.tasks)
    editor.tasks['training'].set(True);editor.select('preview-1');editor.select('preview-0')
    assert editor.tasks['training'].get() and app.players==saved
    editor.window.destroy()
    app.fleet_dialog('preview-0');root.update();editor=app.settings_editor
    assert not editor.tasks['training'].get()
    capture_window(editor.window,output.with_name('review-settings.png'))
    editor.window.destroy()
    # All primary controls stay visible at the minimum supported window size.
    root.geometry('980x640+0+0');root.update();app.apply_layout();root.update()
    if not app.compact_details:app.toggle_compact_details();root.update()
    assert app.detail_panel.winfo_ismapped() and not app.roster_panel.winfo_ismapped()
    assert app.detail_panel.winfo_width()>=900, 'Narrow split view clips task text'
    app.render_roster(force=True)
    for widget in [app.start_button,app.once_button,app.daily_button,app.inspect_button]:
        assert widget.winfo_rootx()>=root.winfo_rootx(), widget.cget('text')
        assert widget.winfo_rootx()+widget.winfo_width()<=root.winfo_rootx()+root.winfo_width(), widget.cget('text')
        assert widget.winfo_rooty()+widget.winfo_height()<=root.winfo_rooty()+root.winfo_height(), widget.cget('text')
    capture_window(root,output.with_name('review-compact.png'))
    assert app.detail_tasks.winfo_ismapped() and app.detail_tasks._parent_canvas.winfo_height()>80, ('result area',app.detail_tasks._parent_canvas.winfo_height())
    app.show_detail_tab('최근 화면');root.update()
    assert app.preview_frame.winfo_ismapped() and not app.detail_tasks.winfo_ismapped()
    app.show_detail_tab('수령 결과');root.update()
    assert app.detail_tasks.winfo_ismapped() and not app.preview_frame.winfo_ismapped()
    # The game theme must preserve safe click targets, disabled controls and
    # layout bounds at enlarged Windows display settings.
    from ui_theme import GameButton, BG, TEXT, ACCENT, CREAM, HEADER
    assert ctk.get_appearance_mode()=='Light'
    assert isinstance(app.start_button,GameButton)
    assert app.start_button.cget('fg_color')==ACCENT
    assert app.start_button.cget('text_color')==HEADER
    for scale in (1.25,1.5):
        ctk.set_widget_scaling(scale);ctk.set_window_scaling(scale)
        fit_window(root);root.update();app.apply_layout();root.update();app.render_roster(force=True);root.update()
        left,top,right,bottom=work_area(root)
        assert root.winfo_rootx()>=left and root.winfo_rooty()>=top, ('monitor origin',scale)
        assert root.winfo_rootx()+root.winfo_width()<=right+2, ('monitor right',scale)
        assert root.winfo_rooty()+root.winfo_height()<=bottom+2, ('monitor bottom',scale)
        for widget in [app.start_button,app.once_button,app.daily_button,app.update_button,app.more_button]:
            assert widget.winfo_ismapped(), ('hidden action',widget.cget('text') if hasattr(widget,'cget') else '',scale)
            assert widget.winfo_rootx()>=root.winfo_rootx(), ('scaled left',scale)
            assert widget.winfo_rootx()+widget.winfo_width()<=root.winfo_rootx()+root.winfo_width()+2, ('scaled right',scale)
            assert widget.winfo_rooty()+widget.winfo_height()<=root.winfo_rooty()+root.winfo_height()+2, ('scaled bottom',scale)
        if app.compact_layout and not app.compact_details:app.toggle_compact_details();root.update()
        assert app.inspect_button.winfo_ismapped()
        assert app.inspect_button.winfo_rooty()+app.inspect_button.winfo_height()<=root.winfo_rooty()+root.winfo_height()+2
        app.preview_image=first;app.show_detail_tab('최근 화면');root.update();app.render_thumbnail();root.update()
        assert app.preview_label.winfo_width()<=app.preview_frame.winfo_width()+2, ('preview width',scale)
        assert app.preview_label.winfo_height()<=app.preview_frame.winfo_height()+2, ('preview height',scale,app.preview_label.winfo_height(),app.preview_frame.winfo_height())
        app.clear_preview();app.show_detail_tab('수령 결과');root.update()
        if app.compact_layout:app.toggle_compact_details();root.update()
        assert not app.detail_task_rows['training'].winfo_ismapped(), 'DPI change restored a disabled task'
        if scale==1.5:capture_window(root,output.with_name('review-scaled.png'))
    ctk.set_widget_scaling(1);ctk.set_window_scaling(1);root.geometry('980x640+0+0');root.update();app.apply_layout();root.update();app.apply_layout();root.update()
    app.toggle_logs();root.update()
    assert app.log_panel.winfo_ismapped() and not app.detail_tasks.winfo_ismapped()
    assert app.start_button.winfo_rooty()+app.start_button.winfo_height()<=root.winfo_rooty()+root.winfo_height()
    app.toggle_logs();root.update()
    capture_window(root,output.with_name('review-compact.png'))
    scale=root._get_window_scaling()
    width=max(980,min(1220,int(root.winfo_screenwidth()/scale)-40))
    height=max(640,min(820,int(root.winfo_screenheight()/scale)-100))
    root.geometry(f'{width}x{height}+0+0');root.update()
    capture_window(root,output.with_name('review-list.png'))
    started=threading.Event()
    def work():started.set();app.stop.wait(30)
    app.run_mode='repeat';app.run_worker(work,'본캐 / 랭킹 수령 확인 중',pausable=True)
    deadline=time.monotonic()+2
    while not started.is_set() and time.monotonic()<deadline:root.update();time.sleep(.01)
    app.events.put(('fleet_status',('preview-0',{'status':'수령 중','rooms':list(TASK_LABELS),'results':{'farm':'collected','wood':'collected'},'next_at':None})))
    app.events.put(('fleet_active',('preview-0','ranking')))
    app.events.put(('fleet_progress',('preview-0','랭킹 수령: 버튼 상태 확인')));app.poll();app.render_roster(force=True);root.update()
    assert app.detail_task_rows['ranking'].cget('border_width')==2
    assert app.detail_task_rows['ranking']._canvas.find_withtag('theme_art')
    assert app.roster_rows['preview-0']['check'].cget('state')=='disabled'
    assert app.detail_enabled.cget('state')=='disabled'
    app.detail_results['ranking'].invoke();root.update()
    assert app.history_task_filter=='ranking'
    assert app.history_retry_button.cget('state')=='disabled'
    app.history_window.destroy()
    app.detail_summary[0].invoke();root.update()
    assert app.history_window.winfo_exists()
    app.history_window.destroy()
    assert app.pause_button.winfo_ismapped() and app.stop_button.winfo_ismapped()
    assert not app.once_button.winfo_ismapped() and not app.start_button.winfo_ismapped() and not app.daily_button.winfo_ismapped()
    order=list(app.display_task_order)
    app.history.record('preview-0','farm','failed');app.render_roster(force=True);root.update()
    assert app.display_task_order==order, 'Rows moved during active collection'
    app.fleet_dialog('preview-0');root.update();assert app.settings_editor.save_button.cget('state')=='disabled'
    app.settings_editor.window.destroy()
    capture_window(root,output.with_name('review-running.png'))
    app.toggle_pause();app.render_roster(force=True);root.update()
    assert app.pause_button.cget('text')=='재시작'
    assert app.roster_rows['preview-0']['status'].cget('text')=='일시중지'
    capture_window(root,output.with_name('review-paused.png'))
    app.stop_run();app.worker.join(2);app.poll();assert not app.busy()
    # The common one-player workspace must prioritize enabled tasks while
    # allowing disabled tasks to be inspected without changing the profile.
    player=copy.deepcopy(app.players['preview-0'])
    player['name']='메인 캐릭터';player['minutes']=180
    player['selected']={task:not task.startswith('daily_') for task in TASK_LABELS}
    app.players={'preview-0':player};app.device_reports={first_serial:reports[first_serial]}
    app.device_options=name_options([first_serial],app.device_reports)
    app.fleet_states={'preview-0':{'status':'확인 완료','results':{},'next_at':None}}
    for task in TASK_LABELS:
        if player['selected'][task]:app.history.record('preview-0',task,'collected')
    app.select_player('preview-0');app.render_roster(force=True);root.update()
    assert len(app.roster_rows)==1
    assert not app.roster_panel.winfo_ismapped() and not app.fleet_bar.winfo_ismapped()
    assert app.detail_panel.winfo_width()>=app.workspace_body.winfo_width()-2
    assert app.detail_summary[2].cget('text')=='3시간'
    assert app.detail_task_rows['farm'].winfo_ismapped()
    assert (bool(app.detail_task_rows['daily_pass'].winfo_ismapped()) == bool(app.history_entries('preview-0').get('daily_pass')))
    saved=copy.deepcopy(app.players)
    # Single-player selection works even when an old roster filter hides the row.
    app.roster_query.set('no matching player');root.update();assert not app.roster_rows
    app.detail_enabled.toggle();root.update()
    assert not app.players['preview-0']['enabled'] and app.start_button.cget('state')=='disabled'
    app.detail_enabled.toggle();root.update();assert app.players==saved
    app.roster_query.set('');root.update()
    app.toggle_disabled_tasks();root.update()
    assert (bool(app.detail_task_rows['daily_pass'].winfo_ismapped()) == bool(app.history_entries('preview-0').get('daily_pass'))) and app.players==saved
    app.toggle_disabled_tasks();root.update()
    assert (bool(app.detail_task_rows['daily_pass'].winfo_ismapped()) == bool(app.history_entries('preview-0').get('daily_pass')))
    # PrintWindow captures the full client area for the regular 820px layout,
    # even when the CI monitor itself is shorter. Monitor-fitting is tested above.
    root.geometry('1220x820+0+0');root.update();app.apply_layout();root.update()
    capture_window(root,output.with_name('review-single.png'))
    viewport=app.detail_tasks._parent_canvas
    last=app.detail_task_rows['farm']
    assert last.winfo_rooty()+last.winfo_height()<=viewport.winfo_rooty()+viewport.winfo_height()+2, 'Enabled tasks clipped in regular workspace'

    for scale in (1.25,1.5):
        ctk.set_widget_scaling(scale);ctk.set_window_scaling(scale)
        fit_window(root);root.update();app.apply_layout();root.update()
        assert not app.roster_panel.winfo_ismapped() and not app.fleet_bar.winfo_ismapped()
        assert (bool(app.detail_task_rows['daily_pass'].winfo_ismapped()) == bool(app.history_entries('preview-0').get('daily_pass')))
        assert not app.pause_button.winfo_ismapped() and not app.stop_button.winfo_ismapped()
    ctk.set_widget_scaling(1);ctk.set_window_scaling(1)
    for geometry in ('680x430+0+0','820x520+0+0'):
        root.geometry(geometry);root.update();app.apply_layout();root.update()
        assert not app.roster_panel.winfo_ismapped() and not app.fleet_bar.winfo_ismapped()
        for widget in (app.start_button,app.once_button,app.daily_button,app.inspect_button,app.history_button):
            assert widget.winfo_ismapped(), ('minimum hidden action',geometry)
            assert widget.winfo_rootx()+widget.winfo_width()<=root.winfo_rootx()+root.winfo_width()+2, ('minimum right',geometry,widget.cget('text'))
            assert widget.winfo_rooty()+widget.winfo_height()<=root.winfo_rooty()+root.winfo_height()+2, ('minimum bottom',geometry,widget.cget('text'))
    app.compact_details=False;root.geometry(f'{width}x{height}+0+0');root.update();app.apply_layout();root.update()

    app.players={};app.device_reports={};app.device_options={};app.view_id=None;app.serial_value.set('');app.fleet_states={}
    app.render_roster(force=True);app.clear_preview();root.update()
    assert app.daily_button.cget('state')=='disabled'
    assert app.start_button.cget('state')=='disabled'
    assert app.connection_text.get()=='연결된 뮤뮤 없음'
    assert app.run_target.cget('text')=='뮤뮤를 연결해 주세요.'
    assert app.empty_panel.winfo_ismapped() and not app.detail_panel.winfo_ismapped()
    assert not app.roster_panel.winfo_ismapped() and not app.fleet_bar.winfo_ismapped()
    capture_window(root,output.with_name('review-empty.png'))
