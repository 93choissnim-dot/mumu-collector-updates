"""Fail-closed recognition of the training-level header, never pixel-change proof."""
import json
from functools import lru_cache
from pathlib import Path
import cv2
import numpy as np


@lru_cache(maxsize=1)
def _glyphs():
    values=json.loads((Path(__file__).parent/'assets/training_glyphs.json').read_text(encoding='utf-8'))
    return {key:np.array(value,np.uint8) for key,value in values.items()}


def _normalized(mask):
    return cv2.resize(mask.astype(np.float32),(8,14),interpolation=cv2.INTER_AREA)


def read_training_level(image):
    """Read only the anchored level label; unknown/ambiguous glyphs return None."""
    if not isinstance(image,np.ndarray) or image.ndim!=3 or image.size==0:return None
    gray=cv2.cvtColor(cv2.resize(image,(960,540)),cv2.COLOR_BGR2GRAY)
    mask=(gray[84:110,625:795]>150).astype(np.uint8)
    glyphs=_glyphs();label=glyphs['label']
    _,score,_,location=cv2.minMaxLoc(cv2.matchTemplate(mask,label,cv2.TM_CCOEFF_NORMED))
    if score<.86:return None
    x,y=location;start=x+label.shape[1]
    digits=mask[y:y+label.shape[0],start:]
    # Connected columns retain disconnected anti-alias pixels within each glyph.
    occupied=np.any(digits,axis=0);spans=[];left=None
    for i,ink in enumerate(list(occupied)+[False]):
        if ink and left is None:left=i
        elif not ink and left is not None:spans.append((left,i));left=None
    if not 1<=len(spans)<=6 or spans[0][0]>7:return None
    # The complete label plus value is centered in the header. Truncated trailing
    # digits must not turn a larger baseline into a smaller valid number.
    if abs((625+x+625+start+spans[-1][1])/2-704)>3:return None
    result='';end=0
    for left,right in spans:
        if left-end>7:return None
        part=digits[:,left:right];rows=np.flatnonzero(np.any(part,axis=1))
        if not len(rows) or not 10<=len(rows)<=15 or not 3<=right-left<=10:return None
        part=part[rows[0]:rows[-1]+1];sample=_normalized(part)
        scores=sorted((float(np.mean(np.abs(sample-_normalized(template)))),key)
                      for key,template in glyphs.items() if key!='label')
        if scores[0][0]>.23 or scores[1][0]-scores[0][0]<.035:return None
        result+=scores[0][1];end=right
    if len(result)>1 and result[0]=='0':return None
    return int(result)
