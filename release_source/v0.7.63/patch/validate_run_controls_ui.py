"""Run the actual Tk controls in the Windows EXE health check."""
import json
import threading
import time
from pathlib import Path
import customtkinter as ctk
from PIL import ImageGrab


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def check(app, output):
    from app import CONFIG
    root=app.root
    def pump_until(predicate, timeout=2):
        deadline=time.monotonic()+timeout
        while not predicate() and time.monotonic()<deadline:
            root.update();time.sleep(.01)
        assert predicate(), 'UI control did not reach expected state'
        root.update()
    texts=[w.cget('text') for w in descendants(root) if isinstance(w,(ctk.CTkLabel,ctk.CTkButton,ctk.CTkCheckBox))]
    assert '작업 설정' in texts and '더보기' in texts
    assert app.more_menu.entrycget(0,'label')=='사용 가이드'
    assert app.more_menu.entrycget(1,'label')=='진단 파일 저장'
    assert not any(t in texts for t in ['대시보드','수령 대시보드','뮤뮤 관리','수령할 시설','백그라운드 모드'])
    assert not app.cards and not app.switches
    assert app.pause_button.cget('state')=='disabled'
    original=app.stop_hotkey.value
    app.fleet_dialog();root.update()
    assert app.fleet_window.title()=='작업 설정'
    app.hotkey_dialog();root.update()
    pump_until(lambda:app.hotkey_window.grab_current()==app.hotkey_window
               and app.hotkey_window.focus_get()==app.hotkey_window)
    app.hotkey_window.event_generate('<KeyPress-F10>',state=0,when='tail');root.update()
    save=next(w for w in descendants(app.hotkey_window) if isinstance(w,ctk.CTkButton) and w.cget('text')=='저장')
    save.invoke();root.update()
    assert app.stop_hotkey.value=='F10', 'Captured shortcut: '+app.stop_hotkey.value
    assert json.loads(CONFIG.read_text(encoding='utf-8'))['stop_hotkey']=='F10'
    assert 'F10' in app.shortcut_hint.cget('text')
    assert not app.hotkey_capture
    ImageGrab.grab().save(Path(output).with_name(Path(output).stem+'-settings.png'))
    app.fleet_window.destroy()
    # Longest supported combination and the minimum window size must fit.
    app.apply_stop_hotkey('Ctrl+Alt+Shift+F12')
    root.geometry('1040x740');root.update()
    for widget in [app.once_button,app.start_button,app.scope_selector,app.connect_button,app.update_button,app.more_button]:
        assert widget.winfo_rootx()>=root.winfo_rootx()
        assert widget.winfo_rootx()+widget.winfo_width()<=root.winfo_rootx()+root.winfo_width()
    root.geometry('1140x820');root.update()
    app.apply_stop_hotkey(original)
    started=threading.Event()
    def work():
        started.set()
        app.stop.wait(60)
    app.run_worker(work,'검사 중',pausable=True)
    pump_until(started.is_set)
    assert app.pause_button.cget('state')=='normal'
    assert app.pause_button.winfo_ismapped() and app.stop_button.winfo_ismapped()
    assert not app.once_button.winfo_ismapped() and not app.start_button.winfo_ismapped() and not app.scope_selector.winfo_ismapped()
    app.pause_button.invoke();root.update()
    assert app.stop.paused and app.busy()
    assert app.pause_button.cget('text')=='재시작'
    app.events.put(('progress','일시중지 중 도착한 진행 알림'));app.poll()
    assert '일시중지' in app.status.get()
    app.pause_button.invoke();root.update()
    assert not app.stop.paused and app.busy()
    assert app.pause_button.cget('text')=='일시중지'
    app.pause_button.invoke();root.update()
    app.stop_button.invoke()
    pump_until(lambda:not app.busy())
    app.poll();root.update()
    assert app.stop.is_set() and not app.stop.paused
    assert app.pause_button.cget('state')=='disabled'
    assert app.stop_button.cget('state')=='disabled'
    assert app.once_button.winfo_ismapped() and app.start_button.winfo_ismapped()
    assert not app.pause_button.winfo_ismapped() and not app.stop_button.winfo_ismapped()
    ImageGrab.grab().save(Path(output).with_name(Path(output).stem+'-list.png'))
