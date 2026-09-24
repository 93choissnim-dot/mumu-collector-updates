"""Observe only a stop shortcut; never store or suppress typed input.

Windows callback and message-loop requirements:
https://learn.microsoft.com/en-us/windows/win32/winmsg/lowlevelkeyboardproc
"""
import os
import threading
from stop_hotkey import normalize, KEYS

MOD_KEYS={'Ctrl':{0x11,0xa2,0xa3},'Alt':{0x12,0xa4,0xa5},'Shift':{0x10,0xa0,0xa1}}


class KeyEdges:
    def __init__(self,value='F8',held=()):
        parts=normalize(value).split('+')
        self.key=KEYS[parts[-1]];self.mods=set(parts[:-1]);self.down=set(held)
        self.relevant={self.key,*(key for keys in MOD_KEYS.values() for key in keys)}
        self.down.intersection_update(self.relevant)

    def event(self,key,down):
        if key not in self.relevant:return False
        repeated=key in self.down
        if down:self.down.add(key)
        else:self.down.discard(key)
        return bool(down and not repeated and key==self.key and
                    all(bool(self.down & keys)==(name in self.mods) for name,keys in MOD_KEYS.items()))


class GlobalStopShortcut:
    def __init__(self,callback,value='F8'):
        self.callback=callback;self.value=normalize(value);self.enabled=False
        self.matcher=KeyEdges(value);self.lock=threading.Lock()
        self.ready=threading.Event();self.closed=threading.Event();self.error=None
        self.thread_id=None;self.thread=None;self.user32=None

    def start(self):
        if os.name!='nt':return False
        self.thread=threading.Thread(target=self._run,name='stop-shortcut',daemon=True)
        self.thread.start()
        if not self.ready.wait(3) or self.error:
            self.close();raise RuntimeError('중지 키를 연결하지 못했습니다: '+str(self.error or '시간 초과'))
        return True

    def configure(self,value,enabled):
        value=normalize(value)
        keys=KeyEdges(value).relevant-{0x11,0x12,0x10}
        held={key for key in keys if self.user32 and self.user32.GetAsyncKeyState(key)&0x8000}
        with self.lock:
            self.value=value;self.matcher=KeyEdges(value,held);self.enabled=bool(enabled)

    def close(self):
        self.closed.set()
        if self.user32 and self.thread_id:self.user32.PostThreadMessageW(self.thread_id,0x0012,0,0)
        if self.thread and self.thread is not threading.current_thread():self.thread.join(2)

    def _run(self):
        import ctypes
        from ctypes import wintypes as w
        hook=None
        try:
            user=ctypes.WinDLL('user32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            self.user32=user
            callback_type=ctypes.WINFUNCTYPE(ctypes.c_ssize_t,ctypes.c_int,w.WPARAM,w.LPARAM)
            class KeyData(ctypes.Structure):
                _fields_=[('vkCode',w.DWORD),('scanCode',w.DWORD),('flags',w.DWORD),('time',w.DWORD),('extra',ctypes.c_size_t)]
            user.SetWindowsHookExW.argtypes=[ctypes.c_int,callback_type,w.HINSTANCE,w.DWORD];user.SetWindowsHookExW.restype=w.HANDLE
            user.CallNextHookEx.argtypes=[w.HANDLE,ctypes.c_int,w.WPARAM,w.LPARAM];user.CallNextHookEx.restype=ctypes.c_ssize_t
            user.UnhookWindowsHookEx.argtypes=[w.HANDLE];user.UnhookWindowsHookEx.restype=w.BOOL
            user.GetMessageW.argtypes=[ctypes.POINTER(w.MSG),w.HWND,w.UINT,w.UINT];user.GetMessageW.restype=ctypes.c_int
            user.PostThreadMessageW.argtypes=[w.DWORD,w.UINT,w.WPARAM,w.LPARAM];user.PostThreadMessageW.restype=w.BOOL
            user.GetAsyncKeyState.argtypes=[ctypes.c_int];user.GetAsyncKeyState.restype=ctypes.c_short
            kernel.GetModuleHandleW.argtypes=[w.LPCWSTR];kernel.GetModuleHandleW.restype=w.HMODULE
            kernel.GetCurrentThreadId.restype=w.DWORD
            self.thread_id=kernel.GetCurrentThreadId()
            message=w.MSG();user.PeekMessageW(ctypes.byref(message),None,0,0,0)
            @callback_type
            def on_key(code,kind,address):
                try:
                    if code==0 and kind in (0x100,0x101,0x104,0x105):
                        key=ctypes.cast(address,ctypes.POINTER(KeyData)).contents.vkCode
                        with self.lock:
                            fired=self.matcher.event(key,kind in (0x100,0x104)) and self.enabled
                        if fired:self.callback()
                except Exception:
                    pass  # Never disrupt the system's keyboard chain.
                return user.CallNextHookEx(None,code,kind,address)
            hook=user.SetWindowsHookExW(13,on_key,kernel.GetModuleHandleW(None),0)
            if not hook:raise ctypes.WinError(ctypes.get_last_error())
            self.ready.set()
            while not self.closed.is_set():
                result=user.GetMessageW(ctypes.byref(message),None,0,0)
                if result<=0:break
                user.TranslateMessage(ctypes.byref(message));user.DispatchMessageW(ctypes.byref(message))
        except Exception as exc:self.error=exc;self.ready.set()
        finally:
            if hook:self.user32.UnhookWindowsHookEx(hook)
