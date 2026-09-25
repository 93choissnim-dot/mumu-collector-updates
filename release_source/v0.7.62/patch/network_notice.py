"""Recognize the supplied connection-lost text and its two-button layout."""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import cv2
import numpy as np

@dataclass(frozen=True)
class NetworkNotice:
    confirm: tuple | None

@lru_cache(maxsize=1)
def controls():
    atlas=cv2.imdecode(np.fromfile(Path(__file__).parent/'assets/network_disconnect_controls.png',np.uint8),cv2.IMREAD_COLOR)
    return atlas[:48],atlas[48:108,:160],atlas[108:168,:160]

def match(panel,template,x,y):
    h,w=template.shape[:2];roi=panel[y-4:y+h+4,x-4:x+w+4]
    _,score,_,where=cv2.minMaxLoc(cv2.matchTemplate(roi,template,cv2.TM_CCOEFF_NORMED))
    px,py=where;patch=roi[py:py+h,px:px+w]
    if score<.93 or np.abs(patch.astype(float)-template.astype(float)).mean()>15:return None
    return x-4+px+w/2,y-4+py+h/2

def detect_network_notice(image):
    if image is None or image.ndim!=3 or min(image.shape[:2])<200:return None
    # Locate the beige dialog independently of crop position or emulator scale.
    h,w=image.shape[:2];factor=min(1,960/w)
    im=cv2.resize(image,None,fx=factor,fy=factor,interpolation=cv2.INTER_AREA) if factor<1 else image
    mask=cv2.inRange(im,np.array([130,155,175]),np.array([175,200,220]))
    candidates=[]
    for contour in cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)[0]:
        x,y,cw,ch=cv2.boundingRect(contour)
        if cw<200 or ch<120 or not 1.55<cw/ch<1.80 or cv2.contourArea(contour)<cw*ch*.85:continue
        text,cancel,confirm=controls()
        # Resampling can move a color-mask edge inward by one or two pixels.
        for pad in range(3):
            left,top=max(0,x-pad),max(0,y-pad);right,bottom=min(im.shape[1],x+cw+pad),min(im.shape[0],y+ch+pad)
            panel=cv2.resize(im[top:bottom,left:right],(460,276),interpolation=cv2.INTER_AREA)
            if match(panel,text,65,67) is None or match(panel,cancel,55,195) is None:continue
            point=match(panel,confirm,245,195)
            # AdbDevice expects 960x540 coordinates, even for high-resolution frames.
            if point is not None:point=(round((left+point[0]*(right-left)/460)/factor*960/w),round((top+point[1]*(bottom-top)/276)/factor*540/h))
            candidates.append(NetworkNotice(point));break
    return candidates[0] if len(candidates)==1 else None

def network_confirm(image):
    notice=detect_network_notice(image)
    return notice.confirm if notice else None
