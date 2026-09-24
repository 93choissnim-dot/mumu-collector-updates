"""Visible-window capture/input for Windows. No ADB, memory access, or injection."""
import ctypes
from ctypes import wintypes as W
import os
import time
import numpy as np
from collector import Halt

if os.name != "nt":
    raise RuntimeError("이 프로그램은 Windows에서 실행하세요.")

U = ctypes.WinDLL("user32", use_last_error=True)
U.GetForegroundWindow.restype = W.HWND
U.GetAncestor.argtypes, U.GetAncestor.restype = [W.HWND, W.UINT], W.HWND
U.WindowFromPoint.argtypes, U.WindowFromPoint.restype = [W.POINT], W.HWND
U.GetClientRect.argtypes, U.GetClientRect.restype = [W.HWND, ctypes.POINTER(W.RECT)], W.BOOL
U.ClientToScreen.argtypes, U.ClientToScreen.restype = [W.HWND, ctypes.POINTER(W.POINT)], W.BOOL
U.IsWindow.argtypes, U.IsWindow.restype = [W.HWND], W.BOOL
U.IsWindowVisible.argtypes, U.IsWindowVisible.restype = [W.HWND], W.BOOL
U.IsIconic.argtypes, U.IsIconic.restype = [W.HWND], W.BOOL
U.ShowWindow.argtypes, U.ShowWindow.restype = [W.HWND, ctypes.c_int], W.BOOL
U.SetForegroundWindow.argtypes, U.SetForegroundWindow.restype = [W.HWND], W.BOOL
U.GetWindowTextLengthW.argtypes, U.GetWindowTextLengthW.restype = [W.HWND], ctypes.c_int
U.GetWindowTextW.argtypes, U.GetWindowTextW.restype = [W.HWND, W.LPWSTR, ctypes.c_int], ctypes.c_int
U.GetWindowThreadProcessId.argtypes = [W.HWND, ctypes.POINTER(W.DWORD)]
U.GetWindowThreadProcessId.restype = W.DWORD
U.GetAsyncKeyState.argtypes, U.GetAsyncKeyState.restype = [ctypes.c_int], ctypes.c_short
CALLBACK = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
U.EnumWindows.argtypes, U.EnumWindows.restype = [CALLBACK, W.LPARAM], W.BOOL


def dpi_awareness():
    try:
        U.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        U.SetProcessDpiAwarenessContext.restype = W.BOOL
        if U.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except AttributeError:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        U.SetProcessDPIAware()


def windows():
    found = []
    @CALLBACK
    def callback(hwnd, _):
        if not U.IsWindowVisible(hwnd):
            return True
        pid = W.DWORD()
        U.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == os.getpid():
            return True
        buf = ctypes.create_unicode_buffer(U.GetWindowTextLengthW(hwnd)+1)
        U.GetWindowTextW(hwnd, buf, len(buf))
        title = buf.value
        if any(s in title.lower() for s in ("mumu", "뮤뮤", "창세기전")):
            found.append((int(hwnd), title))
        return True
    U.EnumWindows(callback, 0)
    return found


def client_rect(hwnd):
    if not U.IsWindow(hwnd) or U.IsIconic(hwnd):
        raise Halt("뮤뮤 창이 닫혔거나 최소화되었습니다.")
    rect, point = W.RECT(), W.POINT(0, 0)
    if not U.GetClientRect(hwnd, ctypes.byref(rect)) or not U.ClientToScreen(hwnd, ctypes.byref(point)):
        raise Halt("뮤뮤 창 위치를 읽지 못했습니다.")
    if rect.right < 320 or rect.bottom < 180:
        raise Halt("뮤뮤 게임 창을 충분히 크게 열어 주세요.")
    return point.x, point.y, rect.right, rect.bottom


def focus(hwnd):
    if U.IsIconic(hwnd):
        U.ShowWindow(hwnd, 9)
    U.SetForegroundWindow(hwnd)


def belongs(hwnd, x, y):
    return U.GetAncestor(U.WindowFromPoint(W.POINT(int(x), int(y))), 2) == hwnd


def screenshot(rect):
    import mss
    x, y, w, h = rect
    with mss.mss() as sct:
        bounds = sct.monitors[0]
        if x < bounds['left'] or y < bounds['top'] or x+w > bounds['left']+bounds['width'] or y+h > bounds['top']+bounds['height']:
            raise Halt("게임 창 일부가 화면 밖에 있습니다.")
        return np.array(sct.grab({'left': x, 'top': y, 'width': w, 'height': h}))[:, :, :3].copy()


class Device:
    def __init__(self, hwnd, region, expected_size, stop):
        self.hwnd, self.region = hwnd, tuple(region)
        self.expected_size, self.stop = tuple(expected_size), stop
        self.last_rect = None

    def check(self):
        if self.stop.is_set() or U.GetAsyncKeyState(0x77) & 0x8000:
            raise Halt("사용자가 중지했습니다.")
        rect = client_rect(self.hwnd)
        if tuple(rect[2:]) != self.expected_size:
            raise Halt("창 크기가 바뀌었습니다. 게임 영역을 다시 지정하세요.")
        if U.GetAncestor(U.GetForegroundWindow(), 2) != self.hwnd:
            raise Halt("게임 창에서 포커스가 벗어나 중지했습니다.")
        x, y, w, h = self.region
        if min(x, y) < 0 or w < 320 or h < 180 or x+w > rect[2] or y+h > rect[3]:
            raise Halt("게임 영역 설정이 올바르지 않습니다.")
        box = rect[0]+x, rect[1]+y, w, h
        for fx in (.03, .5, .97):
            for fy in (.03, .5, .97):
                if not belongs(self.hwnd, box[0]+w*fx, box[1]+h*fy):
                    raise Halt("다른 창이 게임 화면을 가려 중지했습니다.")
        return box

    def capture(self):
        box = self.check()
        im = screenshot(box)
        if box != self.check():
            raise Halt("화면 확인 중 창이 움직였습니다. 다시 시작하세요.")
        self.last_rect = box
        return im

    def position(self, p):
        box = self.check()
        if self.last_rect is None or box != self.last_rect:
            raise Halt("인식 이후 창이 움직였습니다. 다시 시작하세요.")
        x = round(box[0]+p[0]*box[2]/960)
        y = round(box[1]+p[1]*box[3]/540)
        if not belongs(self.hwnd, x, y):
            raise Halt("클릭 위치가 게임 창이 아닙니다.")
        return x, y

    def click(self, p):
        import pyautogui as pg
        pg.FAILSAFE = True
        pg.PAUSE = .1
        x, y = self.position(p)
        pg.moveTo(x, y, duration=.12)
        self.position(p)
        pg.click()

    def drag(self, start, end):
        import pyautogui as pg
        pg.FAILSAFE = True
        pg.PAUSE = .05
        x1, y1 = self.position(start)
        x2, y2 = self.position(end)
        pg.moveTo(x1, y1, duration=.1)
        self.position(start)
        pg.mouseDown()
        try:
            for i in range(1, 13):
                self.position(start)
                pg.moveTo(x1+(x2-x1)*i/12, y1+(y2-y1)*i/12)
        finally:
            # Releasing a held button must succeed even if the pointer reached a fail-safe corner.
            old = pg.FAILSAFE
            pg.FAILSAFE = False
            pg.mouseUp()
            pg.FAILSAFE = old

    def back(self):
        import pyautogui as pg
        self.position((480, 270))
        pg.FAILSAFE = True
        pg.press('esc')
