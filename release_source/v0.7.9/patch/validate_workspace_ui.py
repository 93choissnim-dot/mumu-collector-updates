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


def capture_window(root,path):
    root.lift();root.update()
    x,y=root.winfo_rootx(),root.winfo_rooty()
    ImageGrab.grab(bbox=(x,y,x+root.winfo_width(),y+root.winfo_height())).save(path)


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
    app.roster_filter.set('확인 필요');app.render_roster(force=True)
    assert 'preview-1' in app.roster_rows and 'preview-10' in app.roster_rows
    app.show_roster();root.update()
    # Inspecting and discarding settings must leave all saved profiles intact.
    saved=copy.deepcopy(app.players)
    app.fleet_dialog('preview-0');root.update();editor=app.settings_editor
    editor.tasks['training'].set(True);editor.select('preview-1');editor.select('preview-0')
    assert editor.tasks['training'].get() and app.players==saved
    editor.window.destroy()
    app.fleet_dialog('preview-0');root.update();editor=app.settings_editor
    assert not editor.tasks['training'].get()
    capture_window(editor.window,output.with_name('review-settings.png'))
    editor.window.destroy()
    # All primary controls stay visible at the minimum supported window size.
    root.geometry('1040x680');root.update()
    app.render_roster(force=True)
    for widget in [app.start_button,app.once_button,app.stop_button,app.pause_button,app.inspect_button]:
        assert widget.winfo_rootx()>=root.winfo_rootx(), widget.cget('text')
        assert widget.winfo_rootx()+widget.winfo_width()<=root.winfo_rootx()+root.winfo_width(), widget.cget('text')
        assert widget.winfo_rooty()+widget.winfo_height()<=root.winfo_rooty()+root.winfo_height(), widget.cget('text')
    capture_window(root,output.with_name('review-compact.png'))
    root.geometry('1220x820');root.update()
    capture_window(root,output.with_name('review-list.png'))
    started=threading.Event()
    def work():started.set();app.stop.wait(30)
    app.run_mode='repeat';app.run_worker(work,'본캐 / 랭킹 수령 확인 중',pausable=True)
    deadline=time.monotonic()+2
    while not started.is_set() and time.monotonic()<deadline:root.update();time.sleep(.01)
    app.events.put(('fleet_status',('preview-0',{'status':'수령 중','rooms':list(TASK_LABELS),'results':{'farm':'collected','wood':'collected'},'next_at':None})))
    app.events.put(('fleet_progress',('preview-0','랭킹 수령: 버튼 상태 확인')));app.poll();app.render_roster(force=True);root.update()
    assert app.roster_rows['preview-0']['check'].cget('state')=='disabled'
    app.fleet_dialog('preview-0');root.update();assert app.settings_editor.save_button.cget('state')=='disabled'
    app.settings_editor.window.destroy()
    capture_window(root,output.with_name('review-running.png'))
    app.toggle_pause();app.render_roster(force=True);root.update()
    assert app.pause_button.cget('text')=='재시작'
    assert app.roster_rows['preview-0']['status'].cget('text')=='일시중지'
    capture_window(root,output.with_name('review-paused.png'))
    app.stop_run();app.worker.join(2);assert not app.busy();app.poll()
    app.players={};app.device_reports={};app.device_options={};app.view_id=None;app.serial_value.set('');app.fleet_states={}
    app.render_roster(force=True);app.clear_preview();root.update()
    assert app.start_button.cget('state')=='disabled'
    capture_window(root,output.with_name('review-empty.png'))
