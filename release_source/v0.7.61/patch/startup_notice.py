"""Exact non-personal download notice controls, not a generic Confirm detector."""
from functools import lru_cache
from pathlib import Path
import cv2
import numpy as np

@lru_cache(maxsize=1)
def controls():
    im=cv2.imdecode(np.fromfile(Path(__file__).parent/'assets/start_download_controls.png',np.uint8),cv2.IMREAD_COLOR)
    return im[:27],im[27:88,:160]

def download_confirm(image):
    if image is None or min(image.shape[:2])<200 or abs(image.shape[1]/image.shape[0]-16/9)>.055:return None
    im=cv2.resize(image,(960,540),interpolation=cv2.INTER_AREA)
    for template,(x,y,w,h) in zip(controls(),[(378,200,205,47),(389,317,180,81)]):
        crop=im[y:y+h,x:x+w]
        score=cv2.matchTemplate(crop,template,cv2.TM_CCOEFF_NORMED)
        _,best,_,where=cv2.minMaxLoc(score)
        px,py=where;patch=crop[py:py+template.shape[0],px:px+template.shape[1]]
        if best<.94 or np.abs(patch.astype(float)-template.astype(float)).mean()>15:return None
        center=(x+px+template.shape[1]//2,y+py+template.shape[0]//2)
    return center
