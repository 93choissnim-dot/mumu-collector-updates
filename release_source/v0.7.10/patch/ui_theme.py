"""Scalable parchment, brass and teal controls for the game's menu style."""
import math
import os
import tkinter as tk
from PIL import Image, ImageDraw
import customtkinter as ctk

BG = '#EAE4D8'
SIDE = '#E4DCCB'
PANEL = '#F3EFE5'
INSET = '#EDE7DA'
LINE = '#AEA18A'
RULE = '#D5CABB'
TEXT = '#342F27'
MUTED = '#6C655B'
GOLD = '#956D2C'
MINT = '#246859'
RED = '#9F4930'
BLUE = '#315F81'
ACCENT = '#39677A'
ACCENT_HOVER = '#487E90'
CREAM = '#FFF8E8'
HEADER = '#3C3930'
HOVER = '#DFD4C0'
SELECTED = '#F7E8C6'
DISABLED = '#D5CEBF'
TONES = {'muted': MUTED, 'success': MINT, 'warning': GOLD, 'error': RED, 'active': BLUE}
TINTS = {'muted':'#E2DDD2','success':'#DCE6D6','warning':'#F3DEAF','error':'#EFDFD1','active':'#DCE7ED'}
FONT = "맑은 고딕" if os.name == "nt" else "Noto Sans CJK KR"
TITLE_FONT = '바탕' if os.name == 'nt' else 'Noto Serif CJK KR'


def install_theme():
    ctk.set_appearance_mode('light')
    styles={
        'CTkCheckBox':dict(corner_radius=2,border_width=1,border_color=LINE,fg_color=ACCENT,hover_color=ACCENT_HOVER,checkmark_color=CREAM,text_color=TEXT,text_color_disabled=MUTED),
        'CTkSwitch':dict(fg_color='#C4BBAA',progress_color=ACCENT,button_color=CREAM,button_hover_color='#FFFFFF',text_color=TEXT,text_color_disabled=MUTED),
        'CTkEntry':dict(corner_radius=2,border_width=1,fg_color=PANEL,border_color=LINE,text_color=TEXT,placeholder_text_color=MUTED),
        'CTkOptionMenu':dict(corner_radius=2,fg_color=ACCENT,button_color=ACCENT,button_hover_color=ACCENT_HOVER,text_color=CREAM,text_color_disabled='#D3CBBE'),
        'DropdownMenu':dict(fg_color=PANEL,hover_color=HOVER,text_color=TEXT),
        'CTkScrollbar':dict(button_color='#B7AA94',button_hover_color=GOLD),
        'CTkTextbox':dict(fg_color=PANEL,border_color=LINE,text_color=TEXT),
    }
    for name,values in styles.items():ctk.ThemeManager.theme[name].update(values)


def _outline(w,h,inset,cut):
    l=t=inset;r=w-inset;b=h-inset;c=cut
    return [l+c,t,r-c,t,r,t+c,r,b-c,r-c,b,l+c,b,l,b-c,l,t+c]


class GamePanel(ctk.CTkFrame):
    def _draw(self,no_color_updates=False):
        super()._draw(no_color_updates)
        self._canvas.delete('game_trim')
        if self._border_width<=0:return
        w=self._apply_widget_scaling(self._current_width);h=self._apply_widget_scaling(self._current_height)
        if min(w,h)<16:return
        s=self._get_widget_scaling()
        for inset,color in [(1,self._border_color),(4,self._border_color),(5,CREAM)]:
            self._canvas.create_polygon(_outline(w,h,inset*s,4*s),fill='',outline=self._apply_appearance_mode(color),width=max(1,s),tags='game_trim')


class PaperFrame(ctk.CTkFrame):
    """Original engraved contour lines; no private game screenshots are embedded."""
    def _draw(self,no_color_updates=False):
        super()._draw(no_color_updates)
        self._canvas.delete('paper')
        w=self._apply_widget_scaling(self._current_width);h=self._apply_widget_scaling(self._current_height)
        if min(w,h)<30:return
        for band in range(10):
            points=[]
            for step in range(24):
                points.extend((w*step/23,h*(.24+.073*band)+math.sin(step*.44+band*.3)*h*.038))
            self._canvas.create_line(*points,fill='#DCD2BF',width=1,smooth=True,tags='paper')
        cx=w*.5;cy=h*.57;r=min(w*.31,h*.13)
        for radius in (r,r*.79):
            self._canvas.create_oval(cx-radius,cy-radius,cx+radius,cy+radius,outline='#CFC1A8',width=1,tags='paper')
        for angle in range(0,360,45):
            a=math.radians(angle);b=a+math.pi/2
            pts=[cx+math.sin(a)*r*1.3,cy+math.cos(a)*r*1.3,cx+math.sin(b)*r*.16,cy+math.cos(b)*r*.16,cx-math.sin(a)*r*.25,cy-math.cos(a)*r*.25]
            self._canvas.create_polygon(pts,fill='',outline='#CFC1A8',tags='paper')


class GameButton(ctk.CTkButton):
    """Native button events with an angular, DPI-aware metal rim."""
    def __init__(self,*args,**kwargs):
        self._game_hover=False
        super().__init__(*args,**kwargs)
    def _draw(self,no_color_updates=False):
        super()._draw(no_color_updates);self._trim()
    def _trim(self):
        self._canvas.delete('game_button')
        if self._fg_color=='transparent':return
        s=self._get_widget_scaling();w=self._apply_widget_scaling(self._current_width);h=self._apply_widget_scaling(self._current_height)
        if min(w,h)<12:return
        disabled=self._state==tk.DISABLED
        fill=DISABLED if disabled else self._hover_color if self._game_hover else self._fg_color
        fill=self._apply_appearance_mode(fill)
        self._canvas.create_rectangle(0,0,w,h,fill=self._apply_appearance_mode(self._bg_color),outline='',tags='game_button')
        self._canvas.create_polygon(_outline(w,h,s,5*s),fill=fill,outline=LINE,width=max(1,s),tags='game_button')
        self._canvas.create_polygon(_outline(w,h,4*s,3*s),fill='',outline=CREAM if not disabled else '#E5DED0',width=max(1,s),tags='game_button')
        for child in (self._text_label,self._image_label):
            if child is not None:child.configure(bg=fill)
    def _on_enter(self,event=None):
        self._game_hover=self._state!=tk.DISABLED
        super()._on_enter(event);self._trim()
    def _on_leave(self,event=None):
        self._game_hover=False
        super()._on_leave(event);self._trim()


def font(size=13, bold=False):
    return ctk.CTkFont(family=FONT, size=size, weight="bold" if bold else "normal")


def label(parent, text="", size=13, color=TEXT, bold=False, **kwargs):
    kwargs.setdefault('height',size+8)
    return ctk.CTkLabel(parent, text=text, text_color=color, font=font(size,bold), **kwargs)


def heading(parent,text,size=24,color=TEXT,**kwargs):
    return ctk.CTkLabel(parent,text=text,text_color=color,height=size+10,font=ctk.CTkFont(family=TITLE_FONT,size=size,weight='bold'),**kwargs)


def button(parent,text,command,primary=False,**kwargs):
    options=dict(height=38,corner_radius=0,border_spacing=6,font=font(13,primary),fg_color=ACCENT if primary else INSET,
                 hover_color=ACCENT_HOVER if primary else HOVER,text_color=CREAM if primary else TEXT,text_color_disabled='#777064')
    options.update(kwargs)
    return GameButton(parent,text=text,command=command,**options)


def panel(parent,**kwargs):
    options=dict(fg_color=PANEL,corner_radius=0,border_width=1,border_color=LINE)
    options.update(kwargs)
    return GamePanel(parent,**options)


class GameTabs(ctk.CTkFrame):
    def __init__(self,parent,values,variable=None,command=None,width=240,height=32):
        super().__init__(parent,fg_color='transparent',width=width,height=height,corner_radius=0)
        self.variable=variable or tk.StringVar(value=values[0]);self.command=command;self.buttons={}
        self.grid_columnconfigure(tuple(range(len(values))),weight=1,uniform='tabs')
        for i,value in enumerate(values):
            b=button(self,value,lambda v=value:self._choose(v),width=width//len(values),height=height,font=font(11))
            b.grid(row=0,column=i,sticky='ew',padx=(0,3 if i<len(values)-1 else 0));self.buttons[value]=b
        self._trace=self.variable.trace_add('write',lambda *_:self._refresh());self._refresh()
    def _refresh(self):
        for value,b in self.buttons.items():
            selected=value==self.variable.get()
            b.configure(fg_color=ACCENT if selected else INSET,text_color=CREAM if selected else TEXT,hover_color=ACCENT_HOVER if selected else HOVER)
    def _choose(self,value):
        self.set(value)
        if self.command:self.command(value)
    def set(self,value):self.variable.set(value)
    def get(self):return self.variable.get()
    def destroy(self):
        self.variable.trace_remove('write',self._trace)
        super().destroy()


def icon(kind,color=GOLD,size=32):
    im=Image.new("RGBA",(96,96))
    d=ImageDraw.Draw(im)
    if kind in {'brand','compass'}:
        d.ellipse((17,17,79,79),outline=color,width=3)
        for angle in range(0,360,45):
            a=math.radians(angle);b=a+math.pi/2
            d.polygon([(48+math.sin(a)*43,48+math.cos(a)*43),(48+math.sin(b)*7,48+math.cos(b)*7),(48-math.sin(a)*12,48-math.cos(a)*12)],outline=color,width=2)
        d.ellipse((42,42,54,54),fill=color)
    elif kind=='settings':
        d.ellipse((26,26,70,70),outline=color,width=9);d.ellipse((41,41,55,55),fill=color)
        for a in range(0,360,45):
            x=math.cos(math.radians(a));y=math.sin(math.radians(a))
            d.line([(48+x*28,48+y*28),(48+x*41,48+y*41)],fill=color,width=10)
    elif kind=='list':
        for y in (24,48,72):
            d.polygon([(14,y-5),(19,y),(14,y+5),(9,y)],fill=color);d.line([(30,y),(83,y)],fill=color,width=5)
    elif kind=='guide':
        d.line([(48,79),(14,69),(14,17),(48,27),(82,17),(82,69),(48,79),(48,27)],fill=color,width=4)
    elif kind=='update':
        d.arc((17,17,79,79),30,305,fill=color,width=6);d.polygon([(65,7),(88,28),(63,31)],fill=color)
    elif kind=='ranking':
        d.polygon([(26,14),(70,14),(65,46),(55,60),(41,60),(31,46)],outline=color,width=4)
        d.arc((9,17,40,55),70,280,fill=color,width=4);d.arc((57,17,88,55),260,110,fill=color,width=4)
        d.line([(48,59),(48,79),(28,79),(68,79)],fill=color,width=5)
    elif kind=="farm":
        for x,y in [(28,23),(48,13),(68,29)]:
            d.line([(x,79),(x,y)],fill=color,width=4)
            for dy in (0,14,28):
                d.ellipse((x-14,y+dy,x-2,y+dy+14),fill=color)
                d.ellipse((x+2,y+dy+5,x+14,y+dy+19),fill=color)
        d.line([(22,79),(74,79)],fill=color,width=4)
    elif kind=="wood":
        for x,y in [(23,25),(18,52)]:
            d.rounded_rectangle((x,y,x+57,y+25),radius=10,outline=color,width=4)
            d.ellipse((x,y,x+23,y+25),outline=color,width=4)
            d.ellipse((x+8,y+8,x+16,y+17),outline=color,width=2)
            d.line([(x+32,y+8),(x+49,y+8)],fill=color,width=2)
    elif kind=="mine":
        pts=[(48,10),(72,27),(79,58),(48,84),(17,58),(24,27),(48,10)]
        d.line(pts,fill=color,width=4,joint="curve")
        for points in [[(24,27),(48,34),(72,27)],[(17,58),(48,52),(79,58)],[(48,10),(48,84)],[(24,27),(48,84),(72,27)]]:
            d.line(points,fill=color,width=3)
    elif kind=="screen":
        d.rounded_rectangle((12,18,84,68),radius=7,outline=color,width=4)
        d.line([(48,68),(48,81),(30,81),(66,81)],fill=color,width=4)
        d.line([(30,43),(42,54),(66,33)],fill=color,width=4)
    else:
        d.polygon([(48,7),(88,48),(48,89),(8,48)],outline=color,width=4)
        d.polygon([(48,25),(71,48),(48,71),(25,48)],outline=color,width=3)
        d.line([(48,7),(48,89)],fill=color,width=2)
        d.line([(8,48),(88,48)],fill=color,width=2)
    im=im.resize((size*2,size*2),Image.Resampling.LANCZOS)
    return ctk.CTkImage(light_image=im,dark_image=im,size=(size,size))
