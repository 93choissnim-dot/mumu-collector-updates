"""Parchment, midnight blue and brass surfaces with native scalable controls."""
import math
import os
import tkinter as tk
from PIL import Image, ImageDraw
import customtkinter as ctk

BG = '#E4DDCD'
SIDE = '#D9CFBA'
PANEL = '#F5EFDF'
INSET = '#EBE2D0'
LINE = '#AB9772'
RULE = '#CDBD9D'
TEXT = '#292C32'
MUTED = '#716653'
GOLD = '#A37B38'
MINT = '#32634F'
RED = '#A13F36'
BLUE = '#365C7A'
ACCENT = '#263C50'
ACCENT_HOVER = '#38556C'
CREAM = '#F5EFDF'
HEADER = '#172635'
HEADER_MUTED = '#C7BFAE'
HEADER_GOLD = '#E1BA70'
HEADER_SUCCESS = '#91C4A4'
HEADER_ERROR = '#F09A8F'
HOVER = '#DED1B7'
SELECTED = '#EEE0BB'
DISABLED = '#D9D2C4'
TONES = {'muted': MUTED, 'success': MINT, 'warning': GOLD, 'error': RED, 'active': BLUE}
TINTS = {'muted':'#EDF1EE','success':'#E7F3EB','warning':'#FBF1D9','error':'#FBECE8','active':'#E7F1F7'}
FONT = "맑은 고딕" if os.name == "nt" else "Noto Sans CJK KR"
TITLE_FONT = '바탕' if os.name == 'nt' else 'Noto Serif CJK KR'


def install_theme():
    ctk.set_appearance_mode('light')
    # Windows Tk crashed while resizing the font glyphs used for rounded corners.
    # Use the bundled vector backend for shapes, checkmarks and dropdown arrows.
    from customtkinter.windows.widgets.core_rendering import DrawEngine
    DrawEngine.preferred_drawing_method='polygon_shapes'
    styles={
        'CTkCheckBox':dict(corner_radius=6,border_width=1,border_color=LINE,fg_color=ACCENT,hover_color=ACCENT_HOVER,checkmark_color=CREAM,text_color=TEXT,text_color_disabled=MUTED),
        'CTkSwitch':dict(fg_color=LINE,progress_color=ACCENT,button_color=CREAM,button_hover_color='#F5EFDF',text_color=TEXT,text_color_disabled=MUTED),
        'CTkEntry':dict(corner_radius=6,border_width=1,fg_color=PANEL,border_color=LINE,text_color=TEXT,placeholder_text_color=MUTED),
        'CTkOptionMenu':dict(corner_radius=6,fg_color=ACCENT,button_color=ACCENT,button_hover_color=ACCENT_HOVER,text_color=CREAM,text_color_disabled='#D3CBBE'),
        'DropdownMenu':dict(fg_color=PANEL,hover_color=HOVER,text_color=TEXT),
        'CTkScrollbar':dict(button_color=LINE,button_hover_color=GOLD),
        'CTkTextbox':dict(fg_color=PANEL,border_color=LINE,text_color=TEXT),
    }
    for name,values in styles.items():ctk.ThemeManager.theme[name].update(values)


class GamePanel(ctk.CTkFrame):
    """Native, DPI-aware surfaces without decorative canvas overlays."""


class PaperFrame(ctk.CTkFrame):
    """Quiet navigation surface; brand artwork stays in the header."""


class GameButton(ctk.CTkButton):
    """Keep native hover, focus and disabled behavior at every display scale."""


def font(size=13, bold=False):
    return ctk.CTkFont(family=FONT, size=size, weight="bold" if bold else "normal")


def label(parent, text="", size=13, color=TEXT, bold=False, **kwargs):
    kwargs.setdefault('height',size+8)
    return ctk.CTkLabel(parent, text=text, text_color=color, font=font(size,bold), **kwargs)


def heading(parent,text,size=24,color=TEXT,**kwargs):
    return ctk.CTkLabel(parent,text=text,text_color=color,height=size+10,font=ctk.CTkFont(family=TITLE_FONT,size=size,weight='bold'),**kwargs)


def button(parent,text,command,primary=False,**kwargs):
    options=dict(height=38,corner_radius=3,border_width=1,border_color=GOLD if primary else LINE,border_spacing=9,font=font(13,primary),fg_color=ACCENT if primary else INSET,
                 hover_color=ACCENT_HOVER if primary else HOVER,text_color=CREAM if primary else TEXT,text_color_disabled='#8A8170')
    options.update(kwargs)
    if options['fg_color']=='transparent' and 'border_width' not in kwargs:options['border_width']=0
    return GameButton(parent,text=text,command=command,**options)


def panel(parent,**kwargs):
    options=dict(fg_color=PANEL,corner_radius=3,border_width=1,border_color=RULE)
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
    elif kind=='worldboss':
        d.polygon([(16,10),(33,27),(48,20),(63,27),(80,10),(73,45),(66,69),(48,84),(30,69),(23,45)],outline=color,width=4)
        d.polygon([(29,43),(42,49),(37,56)],fill=color)
        d.polygon([(67,43),(54,49),(59,56)],fill=color)
        d.line([(39,68),(48,63),(57,68)],fill=color,width=4)
    elif kind=='training':
        d.ellipse((21,21,75,75),outline=color,width=4)
        for a in range(0,360,45):
            x=math.cos(math.radians(a));y=math.sin(math.radians(a))
            d.line([(48+x*21,48+y*21),(48+x*40,48+y*40)],fill=color,width=4)
        d.polygon([(48,32),(62,48),(48,64),(34,48)],outline=color,width=4)
    elif kind=='autumn':
        d.polygon([(48,12),(58,34),(78,23),(70,45),(88,49),(62,67),(51,67),(44,86),(38,83),(44,64),(22,57),(8,40),(32,44),(23,23),(42,33)],outline=color,width=4)
        d.line([(44,65),(49,30)],fill=color,width=4)
    elif kind=='excavation':
        d.polygon([(53,8),(74,32),(65,71),(40,88),(22,61),(29,24)],outline=color,width=4)
        d.line([(53,8),(44,36),(40,88),(60,55),(74,32),(44,36),(22,61)],fill=color,width=3)
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
