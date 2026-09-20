"""Run controls and a shortcut editor, accessed only from Tk's main thread."""
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
from stop_hotkey import StopHotkey, from_tk_event
from ui_theme import BG, MUTED, GOLD, label, button


class RunControls:
    def toggle_pause(self):
        if not self.busy() or not self.pause_allowed or self.stop.is_set():
            return
        if self.stop.paused:
            self.stop.resume()
            self.pause_button.configure(text='일시중지')
            self.status.set(self.running_status)
            self.log('재시작: 남은 수령을 이어갑니다.')
        elif self.stop.pause():
            self.running_status = self.status.get()
            self.pause_button.configure(text='재시작')
            self.status.set('일시중지 중 / 재시작을 누르면 이어서 진행합니다.')
            self.countdown.set('일시중지')
            self.log('일시중지: 수령 진행과 예약을 유지합니다.')

    def apply_stop_hotkey(self, value):
        from stop_hotkey import normalize
        previous = self.stop_hotkey
        self.stop_hotkey = StopHotkey(normalize(value))
        self.config['stop_hotkey'] = self.stop_hotkey.value
        try:
            self.save()
        except Exception:
            self.stop_hotkey = previous
            self.config['stop_hotkey'] = previous.value
            raise
        self.shortcut_hint.configure(text='중지 키: '+self.stop_hotkey.value)
        self.sync_stop_key()
        if getattr(self, 'hotkey_label', None) is not None and self.hotkey_label.winfo_exists():
            self.hotkey_label.configure(text='중지 키: '+self.stop_hotkey.value)

    def hotkey_dialog(self):
        if self.hotkey_capture:
            return
        self.hotkey_capture = True
        self.sync_stop_key()
        self.stop_hotkey.reset()
        parent = self.fleet_window if self.fleet_window is not None and self.fleet_window.winfo_exists() else self.root
        win = ctk.CTkToplevel(parent)
        self.hotkey_window = win
        win.title('중지 키 설정');win.geometry('430x250');win.resizable(False,False)
        win.configure(fg_color=BG);win.transient(parent)
        candidate = tk.StringVar(value=self.stop_hotkey.value)
        label(win,'중지할 때 누를 키를 입력하세요.',size=18,bold=True).pack(padx=22,pady=(24,12))
        label(win,textvariable=candidate,size=23,color=GOLD).pack(pady=5)
        label(win,'F1~F12, 문자 키, Ctrl/Alt/Shift 조합 등을 지정할 수 있습니다.',
              size=11,color=MUTED,wraplength=380).pack(pady=8)
        def capture(event):
            value = from_tk_event(event)
            if value:
                candidate.set(value)
            return 'break'
        def close():
            self.hotkey_capture = False
            self.stop_hotkey.reset()
            self.sync_stop_key()
            win.destroy()
            if parent.winfo_exists() and parent is not self.root:
                parent.focus_set()
        def save():
            try:
                self.apply_stop_hotkey(candidate.get())
            except Exception as exc:
                messagebox.showerror('중지 키 저장 실패',str(exc),parent=win)
                return
            close()
        row=ctk.CTkFrame(win,fg_color='transparent');row.pack(pady=15)
        button(row,'취소',close,width=90).pack(side='left',padx=5)
        button(row,'저장',save,primary=True,width=90).pack(side='left',padx=5)
        win.bind('<KeyPress>',capture)
        win.protocol('WM_DELETE_WINDOW',close)
        win.after(100,lambda:(win.grab_set(),win.focus_force()) if win.winfo_exists() else None)
