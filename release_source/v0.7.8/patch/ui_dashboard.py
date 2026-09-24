"""Dark dashboard layout. Game/ADB behavior lives in app.py and existing backends."""
import tkinter as tk
import os
from pathlib import Path
import customtkinter as ctk
import cv2
from PIL import Image
from ui_theme import BG,SIDE,PANEL,INSET,LINE,TEXT,MUTED,GOLD,MINT,RED,font,label,button,panel,icon
from vision import LABELS
from version import VERSION


class Dashboard:
    def build(self):
        ctk.set_appearance_mode("dark")
        self.root.title("창키 도우미 " + VERSION)
        if os.name == "nt":
            self.root.iconbitmap(str(Path(__file__).resolve().parent / "assets" / "chanki.ico"))
        self.root.geometry("1140x820")
        self.root.minsize(1040,740)
        self.root.configure(fg_color=BG)
        self.root.grid_columnconfigure(1,weight=1)
        self.root.grid_rowconfigure(0,weight=1)
        self.controls=[]
        self.next_at=None
        self.session_count=0
        self.log_empty=True
        self.adb_path=tk.StringVar(value=self.config.get("adb_path",""))
        self.address=tk.StringVar(value=self.config.get("address",""))
        self.minutes=tk.StringVar(value=str(self.config.get("minutes",60)))
        self.restore=tk.BooleanVar(value=self.config.get("restore_sleep",True))
        self.selected={k:tk.BooleanVar(value=self.config.get("selected",{}).get(k,True)) for k in LABELS}
        self.status=tk.StringVar(value="게임 화면이나 절전 화면에서 연결해 주세요.")
        self.countdown=tk.StringVar(value="예약 없음")
        self.connection_text=tk.StringVar(value="연결 미확인")
        self.device_info=tk.StringVar(value="뮤뮤에서 게임을 실행해 주세요.")

        side=ctk.CTkFrame(self.root,width=170,corner_radius=0,fg_color=SIDE)
        side.grid(row=0,column=0,sticky="nsew");side.grid_propagate(False)
        side.grid_columnconfigure(0,weight=1);side.grid_rowconfigure(8,weight=1)
        label(side,"",image=icon("brand",size=36),height=44).grid(row=0,column=0,sticky="w",padx=23,pady=(27,9))
        label(side,"창키 도우미",size=20,bold=True).grid(row=1,column=0,sticky="w",padx=23)
        label(side,"창세기전 키우기",size=11,color=MUTED).grid(row=2,column=0,sticky="w",padx=23,pady=(2,30))
        nav=button(side,"리스트",lambda:self.root.focus_set(),width=138)
        nav.configure(fg_color="#293040",text_color=GOLD,anchor="w")
        nav.grid(row=3,column=0,padx=16,pady=5)
        self.fleet_button=button(side,"세팅 설정",self.fleet_dialog,width=138)
        self.fleet_button.grid(row=4,column=0,padx=16,pady=5)
        guide=button(side,"사용 가이드",self.guide_dialog,width=138)
        guide.configure(fg_color="transparent",anchor="w",text_color=MUTED)
        guide.grid(row=5,column=0,padx=16,pady=5)
        diagnostics=button(side,"진단 파일 저장",self.export_diagnostics,width=138)
        diagnostics.configure(fg_color="transparent",anchor="w",text_color=MUTED)
        diagnostics.grid(row=6,column=0,padx=16,pady=5)
        self.update_button=button(side,"업데이트",self.updates_dialog,width=138)
        self.update_button.configure(fg_color="transparent",anchor="w",text_color=MUTED)
        self.update_button.grid(row=7,column=0,padx=16,pady=5)
        label(side,"CHANKI HELPER",size=10,color=MUTED).grid(row=10,column=0,sticky="w",padx=21)
        label(side,"v"+VERSION,size=10,color="#5E6C80").grid(row=11,column=0,sticky="w",padx=21,pady=(0,21))

        main=ctk.CTkFrame(self.root,fg_color="transparent")
        main.grid(row=0,column=1,sticky="nsew",padx=26,pady=18)
        main.grid_columnconfigure(0,weight=1);main.grid_rowconfigure(5,weight=1,minsize=170)
        header=ctk.CTkFrame(main,fg_color="transparent",height=70)
        header.grid(row=0,column=0,sticky="ew",pady=(0,14));header.grid_propagate(False)
        header.grid_columnconfigure(0,weight=1)
        label(header,"리스트",size=27,bold=True).grid(row=0,column=0,sticky="w",pady=(0,3))
        label(header,"반복 수령은 맡겨 두고, 하던 작업을 계속하세요.",size=12,color=MUTED).grid(row=1,column=0,sticky="w")
        metrics=ctk.CTkFrame(header,fg_color="transparent")
        metrics.grid(row=0,column=1,rowspan=2,sticky="e",padx=(10,0))
        label(metrics,"이번 세션 수령",size=10,color=MUTED).grid(row=0,column=0,sticky="w",padx=(0,26))
        self.count_label=label(metrics,"0건",size=21,bold=True)
        self.count_label.grid(row=1,column=0,sticky="w")
        label(metrics,"다음 수령",size=10,color=MUTED).grid(row=0,column=1,sticky="w")
        label(metrics,textvariable=self.countdown,size=17,color=GOLD,width=100,anchor="w").grid(row=1,column=1,sticky="w")

        connection=panel(main,height=86)
        connection.grid(row=1,column=0,sticky="ew",pady=(0,13));connection.grid_propagate(False)
        connection.grid_columnconfigure(0,weight=1)
        details=ctk.CTkFrame(connection,fg_color="transparent")
        details.grid(row=0,column=0,sticky="w",padx=19,pady=15)
        self.connection_badge=label(details,textvariable=self.connection_text,size=13,bold=True,color=MUTED)
        self.connection_badge.pack(anchor="w")
        label(details,textvariable=self.device_info,size=10,color=MUTED,height=20,wraplength=300,justify="left").pack(anchor="w",pady=(3,0))
        # StringVar updates remain valid while the entry is disabled during work.
        # CTkComboBox.set() writes into its Entry and is ignored in that state.
        self.serial_value=tk.StringVar(value="")
        self.serial=ctk.CTkComboBox(connection,values=[],state="readonly",variable=self.serial_value,width=300,height=34,
                                  fg_color=INSET,border_color=LINE,button_color=LINE,
                                  button_hover_color="#3D4D62",font=font(11),dropdown_font=font(11),
                                  dropdown_fg_color=PANEL,dropdown_hover_color=LINE,text_color=TEXT,
                                  command=self.on_device_changed)
        self.serial.grid(row=0,column=1,padx=10)
        self.connect_button=button(connection,"뮤뮤 연결",self.connect,width=106)
        self.connect_button.grid(row=0,column=2,padx=(0,17));self.controls.append(self.connect_button)

        self.fleet_summary=tk.StringVar(value="")
        label(main,textvariable=self.fleet_summary,size=11,color=MUTED).grid(row=2,column=0,sticky="w",pady=(0,12))
        self.cards={};self.card_notes={};self.card_history={};self.switches={}

        settings=panel(main,height=66)
        settings.grid(row=4,column=0,sticky="ew",pady=(0,15));settings.grid_propagate(False)
        settings.grid_columnconfigure(3,weight=1)
        label(settings,"수령 간격",size=12,bold=True).grid(row=0,column=0,padx=(20,12),pady=16)
        entry=ctk.CTkEntry(settings,textvariable=self.minutes,width=65,height=32,justify="center",
                           fg_color=INSET,border_color=LINE,font=font(13),text_color=TEXT)
        entry.grid(row=0,column=1);self.controls.append(entry)
        label(settings,"분마다",size=12,color=MUTED).grid(row=0,column=2,padx=(8,0))
        restore=ctk.CTkSwitch(settings,text="수령 후 절전 모드",variable=self.restore,font=font(12),
                              progress_color=GOLD,fg_color="#3A4657",button_color=TEXT,
                              switch_width=36,switch_height=20)
        restore.grid(row=0,column=4,padx=20);self.controls.append(restore)

        bottom=ctk.CTkFrame(main,fg_color="transparent")
        bottom.grid(row=5,column=0,sticky="nsew",pady=(0,15))
        bottom.grid_columnconfigure(0,weight=1);bottom.grid_columnconfigure(1,weight=0,minsize=300)
        bottom.grid_rowconfigure(0,weight=1)
        activity=panel(bottom)
        activity.grid(row=0,column=0,sticky="nsew",padx=(0,13))
        activity.grid_rowconfigure(1,weight=1);activity.grid_columnconfigure(0,weight=1)
        label(activity,"실행 기록",size=13,bold=True).grid(row=0,column=0,sticky="w",padx=18,pady=(13,5))
        self.logbox=ctk.CTkTextbox(activity,fg_color="transparent",text_color=MUTED,
                                  font=font(11),corner_radius=0,wrap="word",height=100,
                                  scrollbar_button_color=LINE,scrollbar_button_hover_color="#43546B")
        self.logbox.grid(row=1,column=0,sticky="nsew",padx=(12,8),pady=(0,12))
        self.logbox.insert("end","첫 수령을 시작하면\n진행 상황이 여기에 표시됩니다.")
        self.logbox.configure(state="disabled")
        preview=panel(bottom,width=300)
        preview.grid(row=0,column=1,sticky="nsew");preview.grid_columnconfigure(0,weight=1);preview.grid_rowconfigure(1,weight=1)
        row=ctk.CTkFrame(preview,fg_color="transparent")
        row.grid(row=0,column=0,sticky="ew",padx=15,pady=(12,8));row.grid_columnconfigure(0,weight=1)
        label(row,"최근 확인 화면",size=13,bold=True).grid(row=0,column=0,sticky="w")
        inspect=button(row,"화면 확인",lambda:self.launch("inspect"),width=82)
        inspect.configure(height=29,font=font(10))
        inspect.grid(row=0,column=1);self.controls.append(inspect)
        self.preview_frame=ctk.CTkFrame(preview,fg_color=INSET,corner_radius=8)
        self.preview_frame.grid(row=1,column=0,sticky="nsew",padx=15,pady=(0,7))
        self.preview_placeholder=icon("screen",color="#566A84",size=30)
        self.preview_label=label(self.preview_frame,"연결 후 화면을 확인해 주세요.",size=11,color=MUTED,
                                 image=self.preview_placeholder,compound="top",padx=10,pady=8)
        self.preview_label.place(relx=.5,rely=.5,anchor="center")
        self.preview_label.bind("<Button-1>",lambda event:self.preview())
        self.preview_frame.bind("<Configure>",lambda event:self.render_thumbnail())
        label(preview,"확인 당시의 화면 / 클릭하면 크게 보기",size=9,color="#65768D").grid(row=2,column=0,pady=(0,10))

        footer=ctk.CTkFrame(main,fg_color="transparent",height=52)
        footer.grid(row=6,column=0,sticky="ew");footer.grid_columnconfigure(0,weight=1)
        label(footer,textvariable=self.status,size=11,color=MUTED,anchor="w",wraplength=180,justify="left").grid(row=0,column=0,sticky="w",padx=(0,10))
        self.stop_button=button(footer,"중지\n"+self.stop_hotkey.value,self.stop_run,width=145)
        self.stop_button.configure(fg_color="#34242E",hover_color="#4A3038",text_color=RED,state="disabled",height=44,font=font(10))
        self.stop_button.grid(row=0,column=2,padx=(0,8))
        self.pause_button=button(footer,"일시중지",self.toggle_pause,width=90)
        self.pause_button.configure(state="disabled")
        self.pause_button.grid(row=0,column=1,padx=(0,8))
        once=button(footer,"한 번 수령",lambda:self.launch("once"),width=107)
        once.grid(row=0,column=3,padx=(0,8));self.controls.append(once)
        start=button(footer,"자동 수령 시작",lambda:self.launch("repeat"),primary=True,width=144)
        start.grid(row=0,column=4);self.controls.append(start)
        self.update_cards()

    def update_cards(self):
        self.refresh_history()

    def set_busy(self,value):
        for control in self.controls:control.configure(state="disabled" if value else "normal")
        self.serial.configure(state="readonly")
        self.stop_button.configure(state="normal" if value else "disabled")
        self.pause_button.configure(state="normal" if value and self.pause_allowed else "disabled",
                                    text="재시작" if self.stop.paused else "일시중지")
        if not value:self.pause_allowed=False

    def stop_run(self):
        self.stop.set()
        self.pause_button.configure(text="일시중지",state="disabled")
        if self.busy():self.status.set("중지하고 있습니다…")

    def render_thumbnail(self):
        if self.preview_image is None:return
        w=max(30,self.preview_frame.winfo_width()-12);h=max(30,self.preview_frame.winfo_height()-12)
        im=Image.fromarray(cv2.cvtColor(self.preview_image,cv2.COLOR_BGR2RGB))
        im.thumbnail((w,h))
        self.thumbnail=ctk.CTkImage(light_image=im,dark_image=im,size=im.size)
        self.preview_label.configure(text="",image=self.thumbnail)

    def guide_dialog(self):
        window=ctk.CTkToplevel(self.root);window.title("시작 가이드");window.geometry("535x350")
        window.configure(fg_color=BG);window.transient(self.root)
        label(window,"세 단계면 준비 끝",size=23,bold=True).pack(anchor="w",padx=27,pady=(24,18))
        steps=[("01","뮤뮤 연결","게임 실행 후 도우미를 열면 자동으로 연결합니다."),
               ("02","세팅 설정","수령할 창을 체크하고 창마다 시설과 간격을 저장하세요."),
               ("03","한 번 수령","절전 해제와 메뉴 열기는 자동으로 진행됩니다.")]
        for number,title,body in steps:
            row=ctk.CTkFrame(window,fg_color="transparent");row.pack(fill="x",padx=27,pady=8)
            label(row,number,size=16,color=GOLD,width=34).pack(side="left",anchor="n",padx=(0,8))
            col=ctk.CTkFrame(row,fg_color="transparent");col.pack(side="left")
            label(col,title,size=13,bold=True).pack(anchor="w")
            label(col,body,size=11,color=MUTED).pack(anchor="w",pady=(2,0))
        label(window,"중지 키는 세팅 설정에서 변경 / 일시중지 후 재시작으로 이어서 수령",size=11,color=MUTED).pack(anchor="w",padx=27,pady=(15,0))
