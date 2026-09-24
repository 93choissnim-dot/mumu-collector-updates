"""Warm charcoal, antique brass and a restrained heraldic game surface."""
import math
import os
import tkinter as tk
from PIL import Image, ImageDraw, ImageTk
from functools import lru_cache
import customtkinter as ctk

BG = '#1D1A15'
SIDE = '#211E18'
PANEL = '#211E18'
INSET = '#252119'
LINE = '#796441'
RULE = '#493D2B'
TEXT = '#EADDC0'
MUTED = '#B9AA8C'
GOLD = '#C4A367'
MINT = '#AFBE8B'
RED = '#E59C8B'
BLUE = '#E1BE77'
ACCENT = '#B08A4E'
ACCENT_HOVER = '#C09A5E'
CREAM = '#EADDC0'
HEADER = '#191711'
HEADER_MUTED = '#C7BFAE'
HEADER_GOLD = '#E1BA70'
HEADER_SUCCESS = '#91C4A4'
HEADER_ERROR = '#F09A8F'
HOVER = '#383023'
SELECTED = '#3D3220'
DISABLED = '#312C23'
TONES = {'muted': MUTED, 'success': MINT, 'warning': GOLD, 'error': RED, 'active': BLUE}
TINTS = {'muted':'#252119','success':'#262B20','warning':'#3A3020','error':'#392420','active':'#362D1F'}
FONT = "맑은 고딕" if os.name == "nt" else "Noto Sans CJK KR"
TITLE_FONT = '바탕' if os.name == 'nt' else 'Noto Serif CJK KR'


def install_theme():
    ctk.set_appearance_mode('light')
    # Windows Tk crashed while resizing the font glyphs used for rounded corners.
    # Use the bundled vector backend for shapes, checkmarks and dropdown arrows.
    from customtkinter.windows.widgets.core_rendering import DrawEngine
    DrawEngine.preferred_drawing_method='polygon_shapes'
    styles={
        'CTkCheckBox':dict(corner_radius=6,border_width=1,border_color=LINE,fg_color=ACCENT,hover_color=ACCENT_HOVER,checkmark_color=HEADER,text_color=TEXT,text_color_disabled=MUTED),
        'CTkSwitch':dict(fg_color=LINE,progress_color=ACCENT,button_color=CREAM,button_hover_color='#EADDC0',text_color=TEXT,text_color_disabled=MUTED),
        'CTkEntry':dict(corner_radius=6,border_width=1,fg_color=PANEL,border_color=LINE,text_color=TEXT,placeholder_text_color=MUTED),
        'CTkOptionMenu':dict(corner_radius=6,fg_color=ACCENT,button_color=ACCENT,button_hover_color=ACCENT_HOVER,text_color=HEADER,text_color_disabled=MUTED),
        'DropdownMenu':dict(fg_color=PANEL,hover_color=HOVER,text_color=TEXT),
        'CTkScrollbar':dict(button_color=LINE,button_hover_color=GOLD),
        'CTkTextbox':dict(fg_color=PANEL,border_color=LINE,text_color=TEXT),
    }
    for name,values in styles.items():ctk.ThemeManager.theme[name].update(values)


def _blend(a,b,t):
    aa=tuple(int(a[i:i+2],16) for i in (1,3,5));bb=tuple(int(b[i:i+2],16) for i in (1,3,5))
    return tuple(round(x+(y-x)*t) for x,y in zip(aa,bb))


def _crest(draw,cx,cy,r,color,width=1):
    for factor in (1.,.94,.77):
        rr=r*factor
        draw.line([(cx,cy-rr),(cx+rr,cy),(cx,cy+rr),(cx-rr,cy),(cx,cy-rr)],fill=color,width=width)
    ring=[]
    for n in range(64):
        a=math.tau*n/64;rr=r*(.66 if n%4 in (1,2) else .73)
        ring.append((cx+math.cos(a)*rr,cy+math.sin(a)*rr))
    draw.line(ring+[ring[0]],fill=color,width=width)
    for n in range(8):
        a=math.tau*n/8
        pts=[(cx+math.cos(a)*r*.64,cy+math.sin(a)*r*.64),
             (cx+math.cos(a+.32)*r*.15,cy+math.sin(a+.32)*r*.15),
             (cx,cy),(cx+math.cos(a-.32)*r*.15,cy+math.sin(a-.32)*r*.15)]
        draw.polygon(pts,outline=color,width=width)
    draw.ellipse((cx-r*.08,cy-r*.08,cx+r*.08,cy+r*.08),outline=color,width=width)


@lru_cache(maxsize=16)
def _surface(width,height,base,ornament,index):
    # One cached, static bitmap; no animation or layout-size feedback.
    im=Image.new('RGB',(width,height),base);d=ImageDraw.Draw(im)
    grain=_blend(base,GOLD,.026)
    for y in range(5,height,13):
        for x in range((y*17)%23,width,29):d.point((x,y),fill=grain)
    if ornament:
        row=index>=0
        cy=(190-index*42)*height/42 if row else height*.52
        radius=min(width*.36,340*height/42) if row else min(width*.39,height*.72)
        _crest(d,width*.55,cy,radius,_blend(base,GOLD,.075 if row else .09),max(1,round(width/1200)))
    if index>=0:
        d.line((10,height-1,width-10,height-1),fill=RULE)
    elif width>90 and height>50:
        for x,y,sx,sy in ((2,2,1,1),(width-3,2,-1,1),(2,height-3,1,-1),(width-3,height-3,-1,-1)):
            d.line([(x,y+sy*18),(x,y+sy*7),(x+sx*7,y),(x+sx*18,y)],fill=LINE,width=1)
            d.line([(x+sx*4,y+sy*13),(x+sx*4,y+sy*4),(x+sx*13,y+sy*4)],fill=_blend(base,GOLD,.4),width=1)
    return im


class GamePanel(ctk.CTkFrame):
    """Static engraved artwork beneath native widgets, with bounded image caching."""
    def __init__(self,parent,ornament=False,art_index=-1,**kwargs):
        self._art_ready=False;self._art_pending=None;self._art_key=None
        self._ornament=ornament;self._art_index=art_index
        super().__init__(parent,**kwargs)
        self._art_ready=True;self._queue_art()
    def _draw(self,no_color_updates=False):
        super()._draw(no_color_updates)
        if getattr(self,'_art_ready',False):self._queue_art()
    def _queue_art(self):
        if self._art_pending is None:self._art_pending=self.after_idle(self._paint_art)
    def _paint_art(self):
        self._art_pending=None
        if not self.winfo_exists():return
        w=max(1,self._canvas.winfo_width());h=max(1,self._canvas.winfo_height())
        if w<20 or h<10:return
        base=self._apply_appearance_mode(self._fg_color)
        if base=='transparent':return
        key=(w,h,base,self._ornament,self._art_index)
        if key!=self._art_key:
            self._art_key=key
            self._art_image=ImageTk.PhotoImage(_surface(*key),master=self._canvas)
            self._canvas.delete('theme_art')
            self._canvas.create_image(0,0,image=self._art_image,anchor='nw',tags='theme_art')
        self._canvas.tag_raise('theme_art')
        self._canvas.delete('theme_active')
        if self._border_width>1:
            self._canvas.create_rectangle(0,0,3,h,fill=self._apply_appearance_mode(self._border_color),outline='',tags='theme_active')
    def destroy(self):
        if self._art_pending is not None:self.after_cancel(self._art_pending);self._art_pending=None
        super().destroy()


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
                 hover_color=ACCENT_HOVER if primary else HOVER,text_color=HEADER if primary else TEXT,text_color_disabled='#8A806A')
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
            b=button(self,value,lambda v=value:self._choose(v),width=width//len(values),height=height,font=font(12),border_width=0)
            b.grid(row=0,column=i,sticky='ew',padx=(0,3 if i<len(values)-1 else 0));self.buttons[value]=b
            line=ctk.CTkFrame(self,height=2,fg_color=RULE,corner_radius=0);line.grid(row=1,column=i,sticky='ew',padx=2);b._tab_line=line
        self._trace=self.variable.trace_add('write',lambda *_:self._refresh());self._refresh()
    def _refresh(self):
        for value,b in self.buttons.items():
            selected=value==self.variable.get()
            b._tab_line.configure(fg_color=GOLD if selected else RULE)
            b.configure(fg_color=SELECTED if selected else 'transparent',text_color=CREAM if selected else MUTED,hover_color=ACCENT_HOVER if selected else HOVER)
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
        _crest(d,48,48,46,color,2)
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
        for x,y in ((28,30),(48,12),(68,30)):
            d.polygon([(x,y),(x+7,y+14),(x+3,y+14),(x+3,70),(x-3,70),(x-3,y+14),(x-7,y+14)],fill=color)
            d.line((x-11,57,x+11,57),fill=color,width=4)
        d.line([(17,41),(24,73),(48,87),(72,73),(79,41)],fill=color,width=3)
        for x,sgn in ((23,-1),(73,1)):
            for y in (48,60,72):d.polygon([(x,y+7),(x+sgn*12,y-7),(x+sgn*9,y+6),(x,y+12)],fill=color)
    elif kind=='autumn':
        d.polygon([(48,12),(58,34),(78,23),(70,45),(88,49),(62,67),(51,67),(44,86),(38,83),(44,64),(22,57),(8,40),(32,44),(23,23),(42,33)],outline=color,width=4)
        d.line([(44,65),(49,30)],fill=color,width=4)
    elif kind=='excavation':
        d.polygon([(24,22),(63,12),(76,71),(37,82)],outline=color,width=4)
        d.ellipse((15,13,37,34),outline=color,width=4)
        d.arc((30,64,57,89),0,300,fill=color,width=4)
        d.line([(26,23),(65,16),(73,29),(36,38)],fill=color,width=3)
        d.ellipse((41,38,71,68),outline=color,width=4)
        d.ellipse((48,45,64,61),outline=color,width=3)
        for a in range(0,360,60):
            x=56+math.cos(math.radians(a))*19;y=53+math.sin(math.radians(a))*19
            d.line([(56,53),(x,y)],fill=color,width=2)
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
    elif kind in {'daily_pass','daily_guild','daily_dungeons'}:
        if kind=='daily_pass':
            d.polygon([(22,18),(73,18),(68,78),(17,78)],outline=color,width=4)
            d.ellipse((17,10,77,27),outline=color,width=4)
            d.line([(31,40),(59,40),(30,53),(54,53),(29,66),(47,66)],fill=color,width=3)
        elif kind=='daily_guild':
            d.polygon([(20,16),(76,16),(70,65),(48,86),(26,65)],outline=color,width=4)
            _crest(d,48,45,25,color,3)
        else:
            for flip in (-1,1):
                d.line([(48-flip*24,77),(48+flip*23,21)],fill=color,width=7)
                d.polygon([(48+flip*23,21),(48+flip*30,10),(48+flip*29,29)],fill=color)
                d.line([(48-flip*35,56),(48-flip*9,79)],fill=color,width=5)
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
