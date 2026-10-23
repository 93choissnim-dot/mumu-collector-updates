"""Connection settings and evidence-only diagnostics on the existing device lane."""
from pathlib import Path


def validate_connection(executable, address):
    """Accept a file path and a local endpoint, never a command line."""
    from adb_device import local_serial
    from collector import Halt
    executable=str(executable).strip()
    if executable:
        path=Path(executable).expanduser()
        if path.name.lower() not in {'adb.exe','adb_server.exe'} or not path.is_file():
            raise ValueError('뮤뮤 설치 폴더의 adb.exe 또는 adb_server.exe 파일을 선택하세요. 자동 탐색하려면 경로를 비우세요.')
        executable=str(path)
    address=str(address).strip()
    if address:
        if address.isascii() and address.isdecimal():address='127.0.0.1:'+address
        try:address=local_serial(address)
        except Halt as exc:raise ValueError(str(exc)) from exc
    return executable,address


def connection_block_reason(app):
    if getattr(app,'closing',False):return '프로그램 종료 중에는 연결 설정을 변경할 수 없습니다.'
    pending=getattr(app,'update_pending',None)
    thread=getattr(app,'update_thread',None)
    if (getattr(app,'update_applying',False) or (pending is not None and pending.is_set())
            or (thread is not None and thread.is_alive())):
        return '업데이트가 끝난 뒤 연결 설정을 변경하세요.'
    worker=getattr(app,'worker',None)
    if app.busy() or getattr(app,'worker_pending',None) is not None or (worker is not None and worker.is_alive()):
        return '현재 작업을 중지하고 완전히 끝난 뒤 연결 설정을 변경하세요.'
    watch=getattr(app,'watch_thread',None)
    if watch is not None and watch.is_alive():
        return '게임 자동 복구가 진행 중입니다. 자동 복구를 끄고 종료될 때까지 기다리세요.'
    return ''


def apply_connection(app, executable, address, reconnect=False):
    """Commit on the Tk thread, after excluding any in-flight device operation."""
    reason=connection_block_reason(app)
    if reason:raise RuntimeError(reason)
    executable,address=validate_connection(executable,address)
    lane=app.device_lane
    if not lane.acquire(blocking=False):raise RuntimeError('뮤뮤 작업이 끝난 뒤 다시 시도하세요.')
    try:
        reason=connection_block_reason(app)
        if reason:raise RuntimeError(reason)
        old_values=(app.adb_path.get(),app.address.get())
        missing=object()
        old_config={key:app.config.get(key,missing) for key in ('adb_path','address')}
        app.adb_path.set(executable);app.address.set(address)
        try:app.save()
        except Exception:
            app.adb_path.set(old_values[0]);app.address.set(old_values[1])
            # Preserve save()'s safety stop and other non-connection state.
            for key,value in old_config.items():
                if value is missing:app.config.pop(key,None)
                else:app.config[key]=value
            raise
        if reconnect:app.connect()
    finally:lane.release()


def connection_stages(reports, selected):
    """Describe only completed connect reports; this function performs no I/O."""
    from game_recovery import GAME_PACKAGES
    from vision import state_label
    report=reports.get(selected)
    if report is None and len(reports)==1:report=next(iter(reports.values()))
    identified=sum(bool(r.get('instance_id') or r.get('window_name')) for r in reports.values())
    discovery=(f'뮤뮤 식별 정보 확인: {identified}개' if identified else
               '미확인 / 뮤뮤를 실행하고 연결 진단을 눌러 주세요.')
    devices=(f'로컬 ADB 기기 {len(reports)}개 응답 / 최근 연결 확인 결과' if reports else
             '미확인 / 자동 탐색 실패 시 ADB 파일과 로컬 포트를 확인하세요.')
    if report is None:
        detail='목록에서 진단할 뮤뮤를 선택하세요.' if reports else '미확인 / 먼저 연결 진단을 실행하세요.'
        return [('1. 뮤뮤 탐색',discovery),('2. ADB · 기기 연결',devices),('3. 실행 중인 게임',detail),('4. 화면 캡처 · 인식',detail)]
    package=report.get('package','')
    if report.get('package_error'):foreground='현재 앱 미확인 / '+str(report['package_error'])[:220]
    elif package in GAME_PACKAGES:foreground='게임 실행 확인 / '+package
    else:foreground='게임 화면을 열어 주세요. 현재 앱: '+(package or '미확인')
    image=report.get('image')
    if image is None:screen='캡처 미확인 / '+(str(report.get('error',''))[:220] or '뮤뮤 연결과 게임 화면을 확인하세요.')
    else:
        height,width=image.shape[:2]
        if height<=0 or abs(width/height-16/9)>.055:
            screen=f'캡처 {width}×{height} / 뮤뮤 해상도를 가로 16:9로 설정하세요.'
        else:
            state=report.get('state','unknown')
            result='화면 미인식 / 게임 메인 화면을 열고 다시 확인하세요.' if state=='unknown' else state_label(state)
            screen=f'캡처 {width}×{height} · 16:9 확인 / '+result
    return [('1. 뮤뮤 탐색',discovery),('2. ADB · 기기 연결',devices),('3. 실행 중인 게임',foreground),('4. 화면 캡처 · 인식',screen)]


class ConnectionUI:
    def connection_dialog(self):
        import tkinter as tk
        from tkinter import filedialog,messagebox
        import customtkinter as ctk
        from ui_theme import BG,INSET,RULE,MUTED,GOLD,font,label,heading,button
        from ui_layout import fit_window
        previous=getattr(self,'connection_window',None)
        if previous is not None and previous.winfo_exists():previous.lift();return
        window=ctk.CTkToplevel(self.root);self.connection_window=window
        window.title('뮤뮤 연결 설정 · 진단');window.configure(fg_color=BG)
        window.transient(self.root);fit_window(window,(650,730),(480,480))
        window.grid_columnconfigure(0,weight=1);window.grid_rowconfigure(0,weight=1)
        body=ctk.CTkScrollableFrame(window,fg_color='transparent')
        body.grid(row=0,column=0,sticky='nsew',padx=18,pady=(18,8));body.grid_columnconfigure(0,weight=1)
        heading(body,'뮤뮤 연결 설정',size=22).grid(row=0,column=0,sticky='w')
        label(body,'경로와 포트를 비우면 실행 중인 뮤뮤를 자동으로 찾습니다.',size=12,color=MUTED,
              wraplength=540,justify='left').grid(row=1,column=0,sticky='w',pady=(5,15))
        path_value=tk.StringVar(master=window,value=self.adb_path.get())
        address_value=tk.StringVar(master=window,value=self.address.get())
        label(body,'ADB 실행 파일',size=13,bold=True).grid(row=2,column=0,sticky='w')
        path_row=ctk.CTkFrame(body,fg_color='transparent');path_row.grid(row=3,column=0,sticky='ew',pady=(5,6));path_row.grid_columnconfigure(0,weight=1)
        path_entry=ctk.CTkEntry(path_row,textvariable=path_value,height=34,font=font(12),fg_color=INSET,border_color=RULE)
        path_entry.grid(row=0,column=0,sticky='ew',padx=(0,8))
        def browse():
            if connection_block_reason(self):return
            chosen=filedialog.askopenfilename(parent=window,title='뮤뮤 ADB 실행 파일 선택',
                filetypes=[('ADB 실행 파일','adb.exe adb_server.exe'),('실행 파일','*.exe')])
            if chosen:path_value.set(chosen)
        browse_button=button(path_row,'찾아보기',browse,width=80,height=34,font=font(12));browse_button.grid(row=0,column=1)
        label(body,'adb.exe / adb_server.exe · 비워 두면 자동 탐색',size=11,color=MUTED).grid(row=4,column=0,sticky='w')
        label(body,'로컬 주소 또는 포트 (선택)',size=13,bold=True).grid(row=5,column=0,sticky='w',pady=(14,5))
        address_entry=ctk.CTkEntry(body,textvariable=address_value,height=34,font=font(12),fg_color=INSET,border_color=RULE,
                                 placeholder_text='예: 7555 또는 127.0.0.1:7555')
        address_entry.grid(row=6,column=0,sticky='ew')
        label(body,'뮤뮤 설정의 ADB 포트를 입력하세요. 인스턴스가 자동으로 식별되면 해당 주소를 우선합니다.',size=11,color=MUTED,
              wraplength=540,justify='left').grid(row=7,column=0,sticky='w',pady=(5,15))
        heading(body,'연결 진단',size=18).grid(row=8,column=0,sticky='w')
        label(body,'최근 완료된 연결 확인 결과입니다. 진단은 기기 정보와 화면만 읽습니다.',size=12,color=MUTED,
              wraplength=540,justify='left').grid(row=9,column=0,sticky='w',pady=(4,8))
        stage_labels=[]
        for row in range(4):
            item=label(body,'',size=12,anchor='w',justify='left',wraplength=540)
            item.grid(row=10+row,column=0,sticky='ew',pady=5);stage_labels.append(item)
        status_label=label(body,'',size=12,color=GOLD,anchor='w',justify='left',wraplength=540)
        status_label.grid(row=14,column=0,sticky='ew',pady=(12,8))
        actions=ctk.CTkFrame(window,fg_color='transparent');actions.grid(row=1,column=0,sticky='ew',padx=18,pady=(0,18))
        actions.grid_columnconfigure((0,1,2),weight=1)
        def apply(reconnect=False,automatic=False):
            try:apply_connection(self,'' if automatic else path_value.get(),'' if automatic else address_value.get(),reconnect)
            except Exception as exc:messagebox.showerror('연결 설정 확인',str(exc),parent=window);return
            path_value.set(self.adb_path.get());address_value.set(self.address.get())
            if not reconnect:self.status.set('연결 설정을 저장했습니다. 연결 진단으로 확인해 주세요.')
            refresh()
        auto=button(actions,'자동 탐색',lambda:apply(True,True),width=100,height=35,font=font(12))
        auto.grid(row=0,column=0,sticky='ew',padx=(0,5))
        save=button(actions,'설정 저장',apply,width=100,height=35,font=font(12));save.grid(row=0,column=1,sticky='ew',padx=5)
        diagnose=button(actions,'저장 후 연결 진단',lambda:apply(True),primary=True,width=140,height=35,font=font(12))
        diagnose.grid(row=0,column=2,sticky='ew',padx=(5,0))
        controls=[path_entry,address_entry,browse_button,auto,save,diagnose]
        last=[None]
        def refresh():
            if self.closing or not window.winfo_exists() or getattr(self,'connection_window',None) is not window:return
            reason=connection_block_reason(self)
            stages=connection_stages(self.device_reports,self.chosen_serial())
            status=reason or str(self.status.get())[:320]
            signature=(reason,stages,status)
            if signature!=last[0]:
                last[0]=signature
                for widget in controls:widget.configure(state='disabled' if reason else 'normal')
                for widget,(title,detail) in zip(stage_labels,stages):widget.configure(text=title+'\n'+detail)
                status_label.configure(text=status)
        def poll():
            if self.closing or not window.winfo_exists() or getattr(self,'connection_window',None) is not window:return
            refresh();self.root.after(400,poll)
        poll()
