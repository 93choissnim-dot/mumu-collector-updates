"""Standalone EXE entry; Python and all dependencies are bundled."""
import ctypes
import json
import os
from pathlib import Path
import sys
import traceback


def health_check(output):
    import customtkinter as ctk
    from app import App
    from vision import Vision
    from version import VERSION
    from windows_shortcuts import write_link,read_link
    from PIL import ImageGrab
    output=Path(output).resolve();output.parent.mkdir(parents=True,exist_ok=True)
    Vision()
    root=ctk.CTk();app=App(root,autoconnect=False,tray=False)
    root.update()
    from validate_fleet_ui import check
    check(app)
    from validate_run_controls_ui import check as check_run_controls
    check_run_controls(app, output)
    from validate_workspace_ui import check as check_workspace
    check_workspace(app, output)
    app.setup_tray()
    import time
    deadline=time.monotonic()+5
    while not app.tray_ready and time.monotonic()<deadline:
        root.update();time.sleep(.05)
    assert app.tray is not None and app.tray_ready, 'Tray initialization failed'
    app.tray.close();app.tray=None
    app.updates_dialog();root.update()
    ImageGrab.grab().save(output.with_suffix('.png'))
    test_link=output.with_suffix('.lnk')
    exe=Path(sys.executable).resolve()
    write_link(test_link,exe,'',exe.parent,exe)
    target,args=read_link(test_link)
    assert Path(target).resolve()==exe and args==''
    app.closing=True;app.update_stop.set();app.stop.set();root.destroy()
    output.write_text(json.dumps({'ok':True,'version':VERSION,'frozen':bool(getattr(sys,'frozen',False)),
        'ui':True,'fleet_ui':True,'run_controls_ui':True,'workspace_ui':True,'tray':True,'shortcut':True,'bits':ctypes.sizeof(ctypes.c_void_p)*8},ensure_ascii=False),encoding='utf-8')


def main():
    data=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'MumuCollector';data.mkdir(parents=True,exist_ok=True)
    if len(sys.argv)>=3 and sys.argv[1]=='--health-check':
        health_check(sys.argv[2]);return
    if len(sys.argv)>=3 and sys.argv[1]=='--update-worker':
        from exe_updater import worker
        worker(sys.argv[2],recover='--recover' in sys.argv);return
    from instance_lock import InstanceLock
    lock=InstanceLock(data/'collector.lock')
    if not lock.acquire():
        ctypes.windll.user32.MessageBoxW(None,'이미 실행 중인 창키 도우미를 사용해 주세요.','창키 도우미',0x40);return
    try:
        from exe_updater import recover_pending
        if recover_pending(data):return
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
