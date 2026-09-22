"""Foreground-only fallback for two static main navigation glyphs.

Whole crops include animated terrain. Never apply these identity checks to
claim/purchase controls; Vision still requires all three main-screen markers.
"""
import cv2
import numpy as np

class NavigationVision:
    def __init__(self,templates,specs):
        self.references={}
        for name in ('main_menu','main_character'):
            color,gray=templates[name]
            hsv=cv2.cvtColor(color,cv2.COLOR_BGR2HSV)
            mask=((hsv[:,:,2]>125)&(hsv[:,:,0]>8)&(hsv[:,:,0]<45)&
                  (hsv[:,:,1]>15)&(hsv[:,:,1]<190)).astype(np.uint8)
            if name=='main_character':mask=cv2.dilate(mask,np.ones((3,3),np.uint8))
            self.references[name]=(gray.astype(np.float32),mask,specs[name]['box'])

    def recognize(self,image,matches,diagnostics):
        from vision import Match
        gray=cv2.GaussianBlur(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),(3,3),.7).astype(np.float32)
        for name,(template,mask,box) in self.references.items():
            if name in matches or diagnostics[name]['score']<.75:continue
            x,y,r,b=box;x0=max(0,x-7);y0=max(0,y-7)
            roi=gray[y0:min(540,b+7),x0:min(960,r+7)]
            scores=cv2.matchTemplate(roi,template,cv2.TM_CCOEFF_NORMED,mask=mask)
            scores=np.nan_to_num(scores,nan=-1,posinf=-1,neginf=-1)
            _,score,_,(xx,yy)=cv2.minMaxLoc(scores);h,w=template.shape
            a=roi[yy:yy+h,xx:xx+w][mask>0];t=template[mask>0]
            contrast=float(a.std()/max(t.std(),1));light=float(a.mean()/max(t.mean(),1))
            accepted=score>=(.84 if name=='main_menu' else .88) and .60<=contrast<=1.80 and .65<=light<=1.6
            diagnostics[name]['foreground']={'score':float(score),'contrast':contrast,'light':light,'accepted':accepted}
            if accepted:
                diagnostics[name].update(accepted=True,rejection='',color_method='foreground_structure')
                matches[name]=Match(name,float(score),0,(x0+xx+w/2,y0+yy+h/2))
