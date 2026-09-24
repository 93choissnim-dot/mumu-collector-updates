"""Exercise native minimize/restore with a live tray and harmless worker."""
import ctypes
from ctypes import wintypes
import os
import threading
import time


def check(app):
    assert os.name == 'nt', 'Taskbar validation requires Windows'
    root = app.root
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetAncestor.restype = wintypes.HWND
    for name in ('IsWindowVisible', 'IsIconic'):
        fn = getattr(user, name)
        fn.argtypes = [wintypes.HWND]
        fn.restype = wintypes.BOOL
    user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user.ShowWindow.restype = wintypes.BOOL

    def settle():
        # Service Tk events and the application's normal polling timer.
        root.after(400, root.quit)
        root.mainloop()

    root.deiconify()
    root.update()
    hwnd = user.GetAncestor(root.winfo_id(), 2)  # GA_ROOT: native Tk wrapper
    assert hwnd and user.IsWindowVisible(hwnd)
    assert app.tray is not None and app.tray_ready
    started = threading.Event()

    def harmless_work():
        started.set()
        app.stop.wait(15)

    app.run_worker(harmless_work, '최소화 동작 검사', pausable=True)
    assert started.wait(2)
    try:
        for restore_from_tray in (False, True):
            root.iconify()
            settle()
            assert root.state() == 'iconic', 'Minimized window was hidden'
            assert user.IsWindowVisible(hwnd), 'Taskbar window is no longer visible'
            assert user.IsIconic(hwnd), 'Native window is not minimized'
            assert app.busy() and not app.stop.is_set(), 'Minimization stopped work'
            if restore_from_tray:
                app.events.put(('tray_open', None))
            else:
                user.ShowWindow(hwnd, 9)  # SW_RESTORE: taskbar restore operation
            settle()
            assert root.state() == 'normal'
            assert user.IsWindowVisible(hwnd) and not user.IsIconic(hwnd)
            assert app.busy() and not app.stop.is_set(), 'Restoration stopped work'
    finally:
        app.stop_run()
        app.worker.join(2)
        root.deiconify()
        settle()
    assert not app.busy()
