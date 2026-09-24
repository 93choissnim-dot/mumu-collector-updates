"""Observe a changed donation counter; this does not infer a numeric balance."""
import cv2
import numpy as np

def counter_frame(image):
    if not isinstance(image,np.ndarray) or image.size==0:return None
    return cv2.cvtColor(cv2.resize(image,(960,540)),cv2.COLOR_BGR2GRAY)

def correlation(a,b):
    if a is None or b is None or a.shape!=b.shape or min(float(a.std()),float(b.std()))<12:return 0.
    return float(cv2.matchTemplate(a,b,cv2.TM_CCOEFF_NORMED)[0,0])

def changed_counter(before,after):
    """Require stable label/denominator and visible, different numerator glyphs."""
    if before is None or after is None:return None
    label=before[410:429,411:513]
    if float(label.std())<12:return None
    _,score,_,loc=cv2.minMaxLoc(cv2.matchTemplate(after[407:432,408:516],label,cv2.TM_CCOEFF_NORMED))
    if score<.96:return None
    dx,dy=loc[0]-3,loc[1]-3
    old=before[410:429,515:529];new=after[410+dy:429+dy,515+dx:529+dx]
    # Centered text moves on either side when the numerator becomes narrower.
    denominator=before[410:429,529:548]
    if float(denominator.std())<12:return None
    _,den_score,_,_=cv2.minMaxLoc(cv2.matchTemplate(after[407:432,526:551],denominator,cv2.TM_CCOEFF_NORMED))
    if den_score<.96:return None
    if min(float(old.std()),float(new.std()))<12:return None
    score=correlation(old,new)
    if not .2<score<.92:return None
    return new.copy()
