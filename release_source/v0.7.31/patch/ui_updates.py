"""Non-blocking update UI. Apply only after collection has stopped."""
import json
import sys
from pathlib import Path
import shutil
import tempfile
import threading
import time
import tkinter as tk
import customtkinter as ctk
from ui_theme import BG, MUTED, GOLD, label, heading, button
from version import VERSION
from update_backend import check_feed, download_update, prepare_job, start_helper


class Updates:
    def setup_updates(self, base, data):
        self.update_base, self.update_data = base, data
        self.update_stop = threading.Event()
        self.update_thread = None
        self.update_applying = False
        self.update_requested = False
        self.update_pending = threading.Event()
        self.update_continue_scheduled = False
        self.update_info = self.update_work = self.update_meta = None
        self.update_window = None
        self.update_message = tk.StringVar(value="버튼을 눌러 새 버전을 확인하세요.")
        try:
            self.channel = json.loads((base/"update_channel.json").read_text(encoding="utf-8")).get("manifest_url", "")
        except (OSError, ValueError):
            self.channel = ""
        if not self.feed_url():self.update_message.set("배포 주소 연결이 필요합니다.")
        result_path = data/"update_result.json"
        if result_path.is_file():
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
                self.update_message.set(result["message"])
                self.log(result["message"])
                result_path.unlink()
            except (OSError, ValueError, KeyError):pass
        self.root.after(2000, self.auto_check_updates)

    def auto_check_updates(self):
        if self.closing:return
        if self.config.get("update_check", True) and self.feed_url():self.check_updates(manual=False)
        self.root.after(6*60*60*1000,self.auto_check_updates)

    def feed_url(self):
        if getattr(sys, "frozen", False):
            from exe_updater import CHANNEL
            return CHANNEL
        return self.config.get("update_url", "") or self.channel

    def update_busy(self):
        return self.update_thread is not None and self.update_thread.is_alive()

    def updates_dialog(self):
        if self.update_window is not None and self.update_window.winfo_exists():
            self.update_window.lift();return
        window = ctk.CTkToplevel(self.root)
        self.update_window = window
        window.title("창키 도우미 업데이트");window.geometry("490x280")
        window.configure(fg_color=BG);window.transient(self.root);window.resizable(False,False)
        body=ctk.CTkFrame(window,fg_color="transparent");body.pack(fill="both",expand=True,padx=26,pady=22)
        heading(body,"도우미 업데이트",size=23).pack(anchor="w")
        label(body,"현재 버전  v"+VERSION,size=12,color=MUTED).pack(anchor="w",pady=(4,12))
        label(body,textvariable=self.update_message,size=13,color=GOLD,wraplength=430,justify="left",height=52).pack(fill="x",anchor="w")
        label(body,"새 버전이 있으면 자동으로 설치하고 다시 시작합니다.\n수령 중이면 이번 수령이 끝난 뒤 적용합니다.",size=12,color=MUTED,justify="left").pack(anchor="w",pady=(5,17))
        button(body,"새 버전 확인",self.check_updates,primary=True,width=150).pack(anchor="e")

    def continue_update(self):
        self.update_continue_scheduled = False
        if self.closing or not self.update_requested or self.update_applying:return
        if self.update_busy():
            self.schedule_update_continue();return
        if self.update_meta:
            self.update_pending.set()
            if self.busy():
                if self.stop.paused:
                    self.stop_run()
                    self.update_message.set('일시중지된 작업을 중지한 뒤 업데이트합니다…')
                else:self.update_message.set("현재 작업이 끝나면 자동으로 업데이트합니다…")
                self.schedule_update_continue();return
            self.apply_update()
        elif self.update_info:
            self.download_update()

    def schedule_update_continue(self):
        if not self.update_continue_scheduled:
            self.update_continue_scheduled = True
            self.root.after(200,self.continue_update)

    def update_task(self, action):
        if self.update_busy() or self.update_applying:return
        self.update_stop.clear()
        def work():
            try:action()
            except Exception as exc:self.events.put(("update_error",str(exc)))
        self.update_thread=threading.Thread(target=work,daemon=True);self.update_thread.start()

    def check_updates(self, manual=True):
        if self.closing or self.update_applying:return
        if manual:self.update_requested = True
        if self.update_busy():
            if manual:self.schedule_update_continue()
            return
        if self.update_meta:
            if manual:self.schedule_update_continue()
            return
        url=self.feed_url()
        if not url:
            self.update_requested=False
            self.update_message.set("업데이트 주소를 찾지 못했습니다. 개발자에게 알려 주세요.");return
        self.update_message.set("새 버전을 확인하고 있습니다…")
        self.update_task(lambda:self.events.put(("update_checked",check_feed(url,VERSION,self.update_stop))))

    def download_update(self):
        if self.update_busy() or self.update_applying or self.update_meta:return
        if not self.update_info:
            self.check_updates();return
        info=dict(self.update_info)
        self.update_message.set("새 버전을 다운로드하고 검증합니다…")
        def action():
            updates=self.update_data/"updates";updates.mkdir(exist_ok=True)
            work=Path(tempfile.mkdtemp(prefix="release-",dir=updates))
            last_progress=[0.]
            def progress(size):
                now=time.monotonic()
                if size==0 or size==info['size'] or now-last_progress[0]>=.4:
                    last_progress[0]=now
                    self.events.put(('update_progress',(size,info['size'])))
            try:meta=download_update(info,work,self.update_stop,VERSION,self.update_base,progress=progress)
            except Exception:
                shutil.rmtree(work,ignore_errors=True);raise
            self.events.put(("update_staged",(work,meta)))
        self.update_task(action)

    def apply_update(self):
        if self.update_busy() or self.update_applying:return
        if self.busy():
            self.update_message.set("현재 작업이 끝나면 자동으로 업데이트합니다…")
            self.schedule_update_continue();return
        if not self.update_meta:
            self.check_updates();return
        try:
            self.save()
            job=prepare_job(self.update_base,self.update_data,self.update_work,self.update_meta)
            child=start_helper(job)
            if child.poll() is not None:raise RuntimeError("업데이트 적용 도우미를 시작하지 못했습니다.")
        except Exception as exc:
            self.update_requested=False;self.update_pending.clear()
            self.update_message.set("업데이트 시작 실패: "+str(exc));return
        self.update_applying=True
        self.set_busy(True)
        self.update_message.set("업데이트를 적용하고 다시 시작합니다…")
        self.close()

    def handle_update_event(self,kind,value):
        if kind=="update_progress":
            size,total=value
            if size>=total:self.update_message.set("다운로드 완료. 파일을 검증하고 있습니다…")
            else:self.update_message.set(f"새 버전 다운로드 중… {size/1_000_000:.1f} / {total/1_000_000:.1f} MB ({size*100//total}%)")
        elif kind=="update_error":
            self.update_requested=False;self.update_pending.clear()
            self.update_message.set("업데이트 확인/준비 실패: "+value)
            self.log("업데이트: "+value)
        elif kind=="update_checked":
            self.update_info=value
            if value:
                self.update_message.set("새 버전 v"+value["version"]+"가 있습니다.")
                self.update_button.configure(text="새 업데이트",text_color=GOLD)
                if self.update_requested:self.schedule_update_continue()
            else:
                self.update_requested=False;self.update_pending.clear()
                self.update_message.set("최신 버전입니다. (v"+VERSION+")")
        elif kind=="update_staged":
            self.update_work,self.update_meta=value
            self.update_message.set("업데이트 준비가 끝났습니다. 자동 적용 중…")
            if self.update_requested:self.schedule_update_continue()
            self.update_button.configure(text="업데이트 준비됨",text_color=GOLD)
