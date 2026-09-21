"""Background collector UI. All game input uses AdbDevice."""
import ctypes
import json
import os
import sys
from pathlib import Path
import queue
import threading
import time
import traceback
import tkinter as tk
from tkinter import messagebox, filedialog
import customtkinter as ctk
from ui_dashboard import Dashboard
from ui_theme import BG, MUTED, GOLD, MINT, RED
from PIL import Image, ImageTk
import cv2
from mumu_names import read_instances, read_catalog, name_options, name_issues
from fleet_ui import FleetUI
from fleet_collection import FleetCollection
from adb_device import Adb, AdbDevice, discover, inspect_device, select_verified_device, READY_STATES
from collector import Collector, Halt
from vision import Vision, LABELS, state_label
from version import VERSION
from history import History, RESULTS, last_success
from run_support import Schedule, cycle_with_recovery
from diagnostics import export_diagnostics, append_log
from instance_lock import InstanceLock
from ui_updates import Updates
from run_control import RunControl
from stop_hotkey import StopHotkey
from ui_run_controls import RunControls
from ui_roster import RosterUI, short
from ui_history import HistoryUI
from datetime import datetime

BASE = Path(sys.executable).resolve().parent if getattr(sys,"frozen",False) else Path(__file__).resolve().parent
DATA = Path(os.environ.get("LOCALAPPDATA", str(BASE))) / "MumuCollector"
DATA.mkdir(parents=True, exist_ok=True)
CONFIG = DATA / "background_settings.json"


class App(FleetCollection, FleetUI, Dashboard, Updates, RunControls, RosterUI, HistoryUI):
    def __init__(self, root, autoconnect=True, tray=True):
        self.root, self.events, self.stop = root, queue.Queue(), RunControl()
        self.pause_allowed=False
        self.hotkey_capture=False
        self.running_status='수령 중'
        self.worker, self.closing = None, False
        self.preview_image = None
        self.device_reports = {}
        self.device_options = {}
        self.unavailable_devices = set()
        self.failure = False
        self.finish_text = "작업을 마쳤습니다."
        self.history = History(DATA / "collection_history.json")
        try:
            self.config = json.loads(CONFIG.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.config = {}
        self.stop_hotkey=StopHotkey(self.config.get('stop_hotkey','F8'))
        self.hotkey_listener=None
        if os.name=='nt':
            from global_hotkey import GlobalStopShortcut
            listener=GlobalStopShortcut(self.on_stop_key,self.stop_hotkey.value)
            try:
                if listener.start():self.hotkey_listener=listener
            except RuntimeError as exc:self.log(str(exc)+' / 중지 버튼은 사용할 수 있습니다.')
        self.init_fleet()
        self.build()
        self.update_fleet_summary()
        self.setup_updates(BASE, DATA)
        self.refresh_history()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.poll)
        if tray:self.setup_tray()
        if autoconnect:root.after(700,self.auto_connect)

    def busy(self):
        return self.worker is not None and self.worker.is_alive()

    def log(self,text):
        self.events.put(("log",text))

    def save(self):
        self.capture_profile()
        value={**self.config,"adb_path":self.adb_path.get(),"address":self.address.get(),"serial":self.chosen_serial(),
               "selected":self.config.get("selected",{k:True for k in LABELS}),"minutes":self.config.get("minutes",60),
               "restore_sleep":True,"players":self.players,"stop_hotkey":self.stop_hotkey.value,
               "last_instance":self.view_id or self.config.get("last_instance","")}
        temp=CONFIG.with_suffix(".tmp")
        temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")
        temp.replace(CONFIG)
        self.config=value

    def chosen_serial(self):
        value=self.serial.get()
        return self.device_options.get(value,"")

    def clear_preview(self):
        self.preview_image=None
        self.preview_label.configure(image=self.preview_placeholder,text="화면 확인을 눌러 주세요.")

    def on_device_changed(self, value=None):
        serial=self.chosen_serial();self.select_profile(serial);self.clear_preview()
        report=self.device_reports.get(serial)
        if report is None:
            self.connection_text.set('목록에서 뮤뮤를 선택하세요.')
            self.connection_badge.configure(text_color=MUTED)
        elif serial in self.unavailable_devices:
            self.connection_text.set('연결을 다시 확인해 주세요.')
            self.connection_badge.configure(text_color=GOLD)
        elif report.get('image') is None:
            self.connection_text.set('연결됨 / 화면 확인 필요')
            self.connection_badge.configure(text_color=GOLD)
        else:
            self.preview_image=report['image'];self.render_thumbnail()
            known=report.get('state') in READY_STATES
            self.connection_text.set(state_label(report.get('state','unknown')) if known else '게임 화면 확인 필요')
            self.connection_badge.configure(text_color=MINT if known else GOLD)
        self.refresh_details()

    def run_worker(self,operation,status,pausable=False):
        if self.busy() or self.update_applying or self.update_pending.is_set():return
        self.stop.clear();self.status.set(status)
        self.running_status=status;self.pause_allowed=pausable
        self.stop_hotkey.reset()
        self.failure=False;self.finish_text="작업을 마쳤습니다."
        self.set_busy(True)
        def work():
            try:
                operation()
            except Halt as exc:
                self.log("중지: "+str(exc))
                self.events.put(("cancelled" if self.stop.is_set() else "failed",str(exc)))
            except Exception as exc:
                self.log("오류로 중지: "+str(exc))
                self.events.put(("failed",str(exc)))
                (DATA/"background_error.log").write_text(traceback.format_exc(),encoding="utf-8")
            else:
                if self.stop.is_set():
                    self.events.put(("cancelled",""))
            finally:
                self.events.put(("done",""))
        self.worker=threading.Thread(target=work,daemon=True);self.worker.start()
        self.sync_stop_key()

    def sync_stop_key(self):
        if self.hotkey_listener:
            self.hotkey_listener.configure(self.stop_hotkey.value,self.busy() and not self.hotkey_capture and not self.closing)

    def on_stop_key(self):
        # Native key thread: cancellation is immediate; all Tk changes are queued.
        if self.busy() and not self.hotkey_capture and not self.closing:
            self.stop.set();self.events.put(('hotkey_stop',self.stop.generation))

    def connect(self):
        if self.busy():return
        executable,address=self.adb_path.get(),self.address.get()
        saved=self.chosen_serial() or self.config.get("serial","")
        saved_id=self.view_id or self.config.get("last_instance")
        # Refresh transactionally. Cancellation or failure must not erase a
        # previously selected endpoint or force another full discovery.
        self.connection_text.set("연결 확인 중…")
        self.device_info.set("각 주소의 기기 정보와 화면을 확인합니다.")
        self.connection_badge.configure(text_color=GOLD)
        def operation():
            catalog=read_catalog(executable,self.stop,self.log,DATA/'last_mumu_discovery.json')
            names={s:p["name"] for s,p in catalog.items()}
            path,devices=discover(executable,"" if names else address,self.stop,self.log,instances=names)
            adb=Adb(path,self.stop);vision=Vision();reports={}
            self.log("사용 ADB: "+path)
            try:
                self.log("ADB 버전: "+" ".join(adb.run(["version"],timeout=4).decode("utf-8",errors="replace").split())[:240])
            except Halt:
                if self.stop.is_set():raise
            for serial in devices:
                self.log(serial+" / 기기 및 화면 확인 중")
                report=inspect_device(adb,serial,vision,self.log)
                report["window_name"]=names.get(serial,"")
                report["instance_id"]=catalog.get(serial,{}).get("instance_id")
                reports[serial]=report
                outcome="캡처 실패" if report["image"] is None else state_label(report["state"])
                self.log(f"{serial} / {report['model']} / {report['package']} / {outcome}")
            chosen=(next((s for s,r in reports.items() if r.get("instance_id")==saved_id),"") if saved_id
                    else ((saved if saved in reports else "") if saved else select_verified_device(reports,"")))
            self.events.put(("connected",(path,devices,reports,chosen)))
        self.run_worker(operation,"뮤뮤 연결 확인 중…")

    def launch_single(self,mode):
        if self.busy():return
        try:
            serial=self.chosen_serial()
            if not serial:raise Halt("뮤뮤 연결을 누르고 뮤뮤 창을 선택하세요.")
            selected=[k for k,v in self.selected.items() if v.get()]
            if mode!="inspect" and not selected:raise Halt("시설을 하나 이상 선택하세요.")
            minutes=float(self.minutes.get())
            if not 1<=minutes<=1440:raise Halt("반복 간격은 1~1440분입니다.")
            executable,restore=self.adb_path.get(),self.restore.get()
            self.save()
        except Exception as exc:
            messagebox.showerror("설정 확인",str(exc));return
        if mode=="inspect":self.clear_preview()
        initial_report=dict(self.device_reports.get(serial,{}))
        capture_mode=initial_report.get("capture_mode")
        def operation():
            adb=Adb(executable,self.stop)
            try:
                adb.ensure_connected(serial,self.log)
            except Halt:
                if not self.stop.is_set():self.events.put(("link_unavailable",serial))
                raise
            self.events.put(("link_available",serial))
            device=AdbDevice(adb,serial,log=self.log,capture_mode=capture_mode)
            vision=Vision()
            if mode=="inspect":
                report=inspect_device(adb,serial,vision,self.log,capture_mode)
                report["window_name"]=initial_report.get("window_name","")
                report["instance_id"]=initial_report.get("instance_id")
                self.events.put(("device_checked",(serial,report)))
                if report["error"]:raise Halt(report["error"])
                im=report["image"]
                cv2.imencode(".png",im)[1].tofile(DATA/"last_adb_check.png")
                self.log(f"{serial} / {report['model']} / {report['package']} / {im.shape[1]}×{im.shape[0]} / "+state_label(report["state"]))
                if report.get("package_error"):
                    self.log("이미지 캡처는 성공했지만 실행 앱을 확인하지 못했습니다. 위의 조회 결과를 확인하세요.")
                elif report["state"]=="unknown":
                    self.log("이미지 캡처는 성공했습니다. 일반 게임 화면이나 게임 절전 화면인지, 내부 해상도가 16:9인지 확인하세요.")
                self.log("터치 없이 확인했습니다. '최근 확인 화면'을 클릭하면 크게 볼 수 있습니다.")
                return
        self.run_worker(operation,"화면 확인 중" if mode=="inspect" else "수령 중")

    def preview(self):
        if self.preview_image is None:
            messagebox.showinfo("확인 화면","먼저 화면 확인을 누르세요.");return
        im=Image.fromarray(cv2.cvtColor(self.preview_image,cv2.COLOR_BGR2RGB))
        im.thumbnail((min(1100,self.root.winfo_screenwidth()-100),self.root.winfo_screenheight()-160))
        window=ctk.CTkToplevel(self.root);window.title("마지막 확인 화면 — 실시간 화면 아님");window.configure(fg_color=BG)
        photo=ctk.CTkImage(light_image=im,dark_image=im,size=im.size)
        label=ctk.CTkLabel(window,text="",image=photo);label.image=photo;label.pack(padx=12,pady=12)

    def refresh_history(self):
        self.refresh_details()

    def export_diagnostics(self):
        filename = filedialog.asksaveasfilename(parent=self.root, title="진단 파일 저장",
            initialfile="뮤뮤_진단_"+time.strftime("%Y%m%d_%H%M%S")+".zip",
            defaultextension=".zip", filetypes=[("진단 ZIP", "*.zip")])
        if not filename:return
        try:
            export_diagnostics(DATA, filename)
        except (OSError, ValueError) as exc:
            messagebox.showerror("진단 저장 실패", str(exc), parent=self.root)
        else:
            messagebox.showinfo("진단 저장 완료", "게임 확인 화면과 최근 기록을 저장했습니다.\n"+filename, parent=self.root)

    def poll(self):
        if os.name=="nt" and not self.hotkey_capture and self.hotkey_listener is None:
            if self.stop_hotkey.poll(lambda key:ctypes.windll.user32.GetAsyncKeyState(key)&0x8000) and self.busy():
                self.stop_run()
        try:
            while True:
                kind,value=self.events.get_nowait()
                if kind.startswith("update_"):
                    self.handle_update_event(kind,value)
                elif kind=="tray_ready":self.tray_ready=True
                elif kind=='hotkey_stop':
                    if value==self.stop.generation:self.stop_run()
                elif kind=="tray_open":self.root.deiconify();self.root.lift()
                elif kind=="tray_stop":self.stop_run()
                elif kind=="tray_pause":self.toggle_pause()
                elif kind=="tray_exit":self.close();return
                elif kind=="fleet_wait":self.next_at=value
                elif kind=="fleet_status":
                    ident,state=value;self.fleet_states.setdefault(ident,{}).update(state)
                    if state.get("status") in {"수령 중","재시도 중"}:
                        self.next_at=None;self.countdown.set("수령 중")
                elif kind=="fleet_result":
                    ident,room,result=value
                    self.fleet_states.setdefault(ident,{}).setdefault('results',{})[room]=result
                    self.session_count+=int(result=="collected")
                    self.count_label.configure(text=f"{self.session_count}건")
                    if ident==self.view_id and room in self.card_notes:
                        self.card_notes[room].configure(text=RESULTS[result])
                        self.card_history[room].configure(text=last_success(self.history.get(ident,room)))
                elif kind=="done":
                    if self.hotkey_listener:self.hotkey_listener.configure(self.stop_hotkey.value,False)
                    self.stop.resume()
                    for state in self.fleet_states.values():
                        state["next_at"]=None
                        if state.get("status") in {"수령 중","재시도 중"}:state["status"]="중지됨"
                    self.next_at=None;self.countdown.set("예약 없음");self.set_busy(False)
                    self.status.set("작업을 멈췄습니다. 기록 확인 후 다시 시작하세요." if self.failure else self.finish_text)
                elif kind=="cancelled":
                    self.finish_text="중지했습니다. 선택한 뮤뮤는 유지됩니다." if self.chosen_serial() else "중지했습니다."
                    self.on_device_changed()
                elif kind=="failed":
                    self.failure=True
                    # Task failure is not a disconnect. Keep selection, cached
                    # capture mode, and preview so the next start can reuse them.
                    self.on_device_changed()
                elif kind=="link_unavailable":
                    self.unavailable_devices.add(value)
                    self.on_device_changed()
                elif kind=="link_available":
                    self.unavailable_devices.discard(value)
                    self.on_device_changed()
                elif kind=='fleet_progress':
                    ident,phase=value
                    self.fleet_states.setdefault(ident,{})['phase']=phase
                    self.running_status=self.players.get(ident,{}).get('name','뮤뮤')+' / '+phase
                    if not self.stop.paused:self.status.set(self.running_status)
                elif kind=="progress":
                    self.running_status=value
                    if not self.stop.paused:self.status.set(value)
                elif kind=="image":
                    self.preview_image=value;self.render_thumbnail()
                elif kind=="recognized":
                    known=value!="unknown"
                    self.connection_text.set("화면 확인됨" if known else "화면 인식 확인 필요")
                    self.connection_badge.configure(text_color=MINT if known else GOLD)
                elif kind=="connected":
                    path,devices,reports,chosen=value;self.adb_path.set(path)
                    self.device_reports=reports
                    self.unavailable_devices.difference_update(devices)
                    self.device_options=name_options(devices,reports)
                    if chosen not in self.device_options.values():chosen=""
                    for message in name_issues(devices,reports):self.log(message)
                    self.serial.configure(values=list(self.device_options))
                    if chosen:
                        self.serial_value.set(next(label for label,serial in self.device_options.items() if serial==chosen))
                        self.log("화면 확인 후 선택한 주소: "+chosen)
                        if reports[chosen]["image"] is not None:
                            cv2.imencode(".png",reports[chosen]["image"])[1].tofile(DATA/"last_adb_check.png")
                    else:
                        self.serial_value.set("")
                        if self.device_options:self.log("목록에서 수령할 뮤뮤 창 이름을 선택하세요.")
                    self.sync_players(reports,chosen)
                    self.on_device_changed()
                    self.finish_text="기기별 확인을 마쳤습니다. 미리보기를 확인해 주세요."
                    if not self.device_options:
                        self.connection_text.set("뮤뮤 창 연결 확인 필요")
                        self.device_info.set("실행 기록을 확인하거나 진단 파일을 저장해 주세요.")
                        self.finish_text="뮤뮤 창 연결을 확인하지 못했습니다. 진단 파일에서 원인을 확인할 수 있습니다."
                    elif not any(report["image"] is not None for report in reports.values()):
                        self.connection_text.set("주소 연결됨 / 모든 캡처 실패")
                        self.connection_badge.configure(text_color=RED)
                        self.finish_text="캡처에 실패했습니다. 실행 기록을 확인해 주세요."
                    self.save()
                elif kind=="device_checked":
                    serial,report=value
                    ident=report.get("instance_id")
                    if ident:
                        for old in list(self.device_reports):
                            if old!=serial and self.device_reports[old].get("instance_id")==ident:
                                self.device_reports.pop(old)
                        if ident in self.players:self.players[ident].update(serial=serial,name=report["window_name"])
                    if report.get('image') is not None:report.setdefault('captured_at',datetime.now().astimezone().isoformat(timespec='seconds'))
                    self.device_reports[serial]=report
                    self.device_options=name_options(list(self.device_reports),self.device_reports)
                    label=next((name for name,address in self.device_options.items() if address==serial),"")
                    self.serial.configure(values=list(self.device_options))
                    if report.get("instance_id")==self.view_id or self.chosen_serial()==serial:
                        self.serial_value.set(label);self.on_device_changed()
                elif kind=="collecting":
                    self.next_at=None;self.countdown.set("수령 중")
                    self.status.set("선택한 시설을 확인하고 있습니다.")
                    for room in value:
                        if room in self.card_notes:self.card_notes[room].configure(text="확인 대기",text_color=GOLD)
                elif kind=="room_result":
                    room,result=value
                    self.session_count+=int(result=="collected")
                    self.count_label.configure(text=f"{self.session_count}건")
                    note,color={"collected":("수령 완료",MINT),"skipped":("수령할 자원 없음",MUTED),
                                "attempted":("수령 시도 · 완료 미확인",GOLD),
                                "unrecognized":("버튼 미인식 · 확인 필요",GOLD),
                                "failed":("진행 중단 · 확인 필요",RED),
                                "already_complete":("이미 완료",MINT),"already_claimed":("이미 수령",MINT),
                                "no_entries":("입장 횟수 없음",MINT)}[result]
                    if room in self.card_notes:self.card_notes[room].configure(text=note,text_color=color)
                    if room in self.card_history:self.card_history[room].configure(text=last_success(self.history.get(self.chosen_serial(),room)))
                elif kind=="waiting":
                    self.next_at,retry,rooms=value
                    self.status.set(("미확인 시설 재확인 대기: "+", ".join(LABELS[r] for r in rooms)) if retry else "다음 정기 수령을 기다리고 있습니다.")
                else:
                    line=time.strftime("%H:%M:%S")+"  "+str(value)+"\n"
                    self.log_summary.configure(text=short(value,57))
                    self.logbox.configure(state="normal")
                    if self.log_empty:self.logbox.delete("1.0","end");self.log_empty=False
                    self.logbox.insert("end",line)
                    if int(self.logbox.index("end-1c").split(".")[0])>400:self.logbox.delete("1.0","100.0")
                    self.logbox.see("end");self.logbox.configure(state="disabled")
                    try:append_log(DATA/"background_run.log",line)
                    except OSError:pass
        except queue.Empty:pass
        self.render_fleet_status()
        if self.stop.paused:
            self.countdown.set('일시중지')
            self.status.set('일시중지 중 / 재시작을 누르면 이어서 진행합니다.')
        elif self.next_at is not None:
            remaining=max(0,int(self.next_at-self.stop.clock()))
            hours,remainder=divmod(remaining,3600);minutes,seconds=divmod(remainder,60)
            self.countdown.set(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        elif self.busy() and self.pause_allowed:
            self.countdown.set('수령 중')
        if self.closing and not self.busy():self.root.destroy();return
        self.status_label.configure(wraplength=max(500,self.main_panel.winfo_width()-10))
        self.root.after(150,self.poll)

    def close(self):
        if self.closing:return
        self.save()
        if self.tray:self.tray.close()
        self.closing=True;self.stop.set()
        if self.hotkey_listener:self.hotkey_listener.close()
        self.update_stop.set()
        if not self.busy():self.root.destroy()


def main(held_lock=None):
    lock = held_lock or InstanceLock(DATA / "collector.lock")
    if held_lock is None and not lock.acquire():
        root = tk.Tk();root.withdraw()
        messagebox.showinfo("이미 실행 중", "수령 도우미가 이미 실행 중이거나 업데이트 중입니다.\n열려 있는 도우미 창을 사용해 주세요.")
        root.destroy();return
    try:
        from branding import prepare_desktop
        prepare_desktop(BASE, DATA)
        root=ctk.CTk();App(root);root.mainloop()
    finally:
        lock.release()


if __name__=="__main__":main()
