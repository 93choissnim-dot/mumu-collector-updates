"""Presentation-only theme and vector-derived icons for the desktop dashboard."""
import os
from pathlib import Path
from PIL import Image, ImageDraw
import customtkinter as ctk

BG = "#0D1118"
SIDE = "#101620"
PANEL = "#161E2A"
INSET = "#101722"
LINE = "#2B3647"
TEXT = "#EEF2F7"
MUTED = "#A1AEC0"
GOLD = "#DAB77B"
MINT = "#80C9B4"
RED = "#E09A9E"
BLUE = "#93B8F4"
TONES = {'muted': MUTED, 'success': MINT, 'warning': GOLD, 'error': RED, 'active': BLUE}
FONT = "맑은 고딕" if os.name == "nt" else "Noto Sans CJK KR"


def font(size=13, bold=False):
    return ctk.CTkFont(family=FONT, size=size, weight="bold" if bold else "normal")


def label(parent, text="", size=13, color=TEXT, bold=False, **kwargs):
    return ctk.CTkLabel(parent, text=text, text_color=color, font=font(size,bold), **kwargs)


def button(parent,text,command,primary=False,**kwargs):
    options=dict(height=38,corner_radius=8,font=font(13,primary),fg_color=GOLD if primary else '#243146',
                 hover_color='#E6C996' if primary else '#304159',text_color=BG if primary else TEXT,
                 text_color_disabled='#738198')
    options.update(kwargs)
    return ctk.CTkButton(parent,text=text,command=command,**options)


def panel(parent,**kwargs):
    options=dict(fg_color=PANEL,corner_radius=12,border_width=1,border_color=LINE)
    options.update(kwargs)
    return ctk.CTkFrame(parent,**options)


def icon(kind,color=GOLD,size=32):
    if kind == "brand":
        with Image.open(Path(__file__).resolve().parent/"assets"/"chanki.png") as source:
            im=source.convert("RGBA")
        return ctk.CTkImage(light_image=im,dark_image=im,size=(size,size))
    im=Image.new("RGBA",(96,96))
    d=ImageDraw.Draw(im)
    if kind=="farm":
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
