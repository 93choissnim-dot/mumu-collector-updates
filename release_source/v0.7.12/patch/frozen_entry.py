"""Standalone EXE entry; Python and all dependencies are bundled."""
import ctypes
import json
import os
from pathlib import Path
import sys
import traceback


def health_check(output,full_ui=True):
    import faulthandler
    import customtkinter as ctk
    from app import App
    from vision import Vision
    from version import VERSION
    from windows_shortcuts import write_link,read_link
    from PIL import ImageGrab
    output=Path(output).resolve();output.parent.mkdir(parents=True,exist_ok=True)
    def checkpoint(stage):
        output.with_suffix('.progress.json').write_text(json.dumps({'stage':stage,'full_ui':full_ui,'version':VERSION}),encoding='utf-8')
    checkpoint('vision')
    Vision()
    root=ctk.CTk()
    if not full_ui:root.withdraw()
    trace=output.with_suffix('.threads.log').open('w',encoding='utf-8')
    faulthandler.dump_traceback_later(25,repeat=True,file=trace)
    app=None
    try:
        checkpoint('startup_ui')
        app=App(root,autoconnect=False,tray=False);app.config['update_check']=False
        root.update()
        assert app.start_button.winfo_exists() and app.pause_button.winfo_exists()
        assert app.stop_button.cget('state')=='disabled'
        assert app.fleet_button.cget('command') is not None
        if full_ui:
            checkpoint('fleet_ui')
            from validate_fleet_ui import check
            check(app)
            checkpoint('run_controls_ui')
            from validate_run_controls_ui import check as check_run_controls
            check_run_controls(app,output)
            checkpoint('workspace_ui')
            from validate_workspace_ui import check as check_workspace
            check_workspace(app,output)
            checkpoint('improvements_ui')
            from validate_improvements_ui import check as check_improvements
            check_improvements(app,output)
        checkpoint('tray')
        app.setup_tray()
        import time
        deadline=time.monotonic()+5
        # Tray image encoding can trigger cyclic GC of discarded Tk fonts.
        # Tk only services those cross-thread destructors inside mainloop();
        # repeated update() calls leave them waiting and falsely fail startup.
        def await_tray():
            if app.tray_ready or time.monotonic()>=deadline:root.quit()
            else:root.after(25,await_tray)
        root.after(0,await_tray)
        root.mainloop()
        if not app.tray_ready:faulthandler.dump_traceback(file=trace,all_threads=True)
        assert app.tray is not None and app.tray_ready,'Tray initialization failed'
        if full_ui:
            checkpoint('taskbar_ui')
            from validate_taskbar_ui import check as check_taskbar
            check_taskbar(app)
        app.tray.close();app.tray=None
        if full_ui:
            app.updates_dialog();root.update()
            ImageGrab.grab().save(output.with_suffix('.png'))
        checkpoint('shortcut')
        test_link=output.with_suffix('.lnk');exe=Path(sys.executable).resolve()
        write_link(test_link,exe,'',exe.parent,exe)
        target,args=read_link(test_link)
        assert Path(target).resolve()==exe and args==''
    finally:
        if app is not None:
            app.closing=True;app.update_stop.set();app.stop.set()
            if getattr(app,'tray',None) is not None:app.tray.close()
            if getattr(app,'hotkey_listener',None) is not None:app.hotkey_listener.close()
        root.destroy()
        faulthandler.cancel_dump_traceback_later();trace.close()
    checkpoint('complete')
    output.write_text(json.dumps({'ok':True,'version':VERSION,'frozen':bool(getattr(sys,'frozen',False)),
        'ui':True,'startup_ui':True,'full_ui_checks':full_ui,'fleet_ui':full_ui,'run_controls_ui':full_ui,
        'workspace_ui':full_ui,'game_theme_ui':full_ui,'improvements_ui':full_ui,'taskbar_ui':full_ui,'tray':True,'shortcut':True,
        'bits':ctypes.sizeof(ctypes.c_void_p)*8},ensure_ascii=False),encoding='utf-8')


def main():
    data=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'MumuCollector';data.mkdir(parents=True,exist_ok=True)
    if len(sys.argv)>=3 and sys.argv[1]=='--health-check':
        health_check(sys.argv[2],full_ui='--full-ui-checks' in sys.argv);return
    if len(sys.argv)>=3 and sys.argv[1]=='--update-worker':
        from exe_updater import worker
        worker(sys.argv[2],recover='--recover' in sys.argv);return
    from instance_lock import InstanceLock
    lock=InstanceLock(data/'collector.lock')
    if not lock.acquire():
        ctypes.windll.user32.MessageBoxW(None,'이미 실행 중인 창키 도우미를 사용해 주세요.','창키 도우미',0x40);return
    try:
        from exe_updater import recover_pending,cleanup_updates
        if recover_pending(data):return
        cleanup_updates(data)
        from app import main as app_main
        app_main(lock)
    finally:lock.release()


if __name__=='__main__':
    try:main()
    except Exception:
        data=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'MumuCollector';data.mkdir(parents=True,exist_ok=True)
        log=data/'exe_error.log';log.write_text(traceback.format_exc(),encoding='utf-8')
        if len(sys.argv)==1:ctypes.windll.user32.MessageBoxW(None,'실행 오류가 발생했습니다.\n기록: '+str(log),'창키 도우미',0x10)
        sys.exit(1)
