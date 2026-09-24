"""Foreground icon checks independent of moving combat backgrounds."""
from pathlib import Path
import cv2
import numpy as np


class TopBarVision:
    def __init__(self,assets,daily):
        assets=Path(assets)
        # Preserve existing event/boss references; the pass emblem was explicitly approved for publication.
        event=daily.templates['open_event'][0][5:35,4:31].copy()
        boss=cv2.imdecode(np.fromfile(assets/'x_menu_boss.png',np.uint8),1)[7:37,4:33].copy()
        atlas=cv2.imdecode(np.fromfile(assets/'top_bar_atlas.png',np.uint8),1)
        if atlas is None or atlas.shape!=(32,102,3):raise ValueError('상단 아이콘 기준 이미지를 확인해 주세요.')
        self.references={'pass':(atlas[:,:34].copy(),(582,12,616,44)),
                         'event':(event,(639,15,666,45)),
                         'worldboss':(boss,(692,15,721,45))}
    def recognize(self,image):
        from vision import Match
        found={};diagnostics={}
        for key,(ref,box) in self.references.items():
            hsv=cv2.cvtColor(ref,cv2.COLOR_BGR2HSV)
            mask=((hsv[:,:,2]>125)&(hsv[:,:,0]>8)&(hsv[:,:,0]<45)&(hsv[:,:,1]>15)&(hsv[:,:,1]<190)).astype(np.uint8)
            mask=cv2.dilate(mask,np.ones((3,3),np.uint8))
            if key=='event':mask[-8:]=0  # Moving combat overlaps the lower edge, outside the emblem.
            template=cv2.GaussianBlur(cv2.cvtColor(ref,cv2.COLOR_BGR2GRAY),(3,3),.7).astype(np.float32)
            x,y,r,b=box;roi=image[max(0,y-5):min(540,b+5),max(0,x-5):min(960,r+5)]
            gray=cv2.GaussianBlur(cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY),(3,3),.7).astype(np.float32)
            h,w=template.shape;best=None
            scores=cv2.matchTemplate(gray,template,cv2.TM_CCOEFF_NORMED,mask=mask)
            scores=np.nan_to_num(scores,nan=-1,posinf=-1,neginf=-1)
            _,score,_,(xx,yy)=cv2.minMaxLoc(scores)
            a=gray[yy:yy+h,xx:xx+w][mask>0];t=template[mask>0]
            if a.size>=25:
                best=(float(score),float(a.mean()/max(t.mean(),1)),float(a.std()/max(t.std(),1)),xx,yy)
            if best:
                score,light,contrast,xx,yy=best
                accepted=score>=(.88 if key=='worldboss' else .90) and .65<=light<=1.6 and .60<=contrast<=1.8
                diagnostics[key]={'score':score,'light':light,'contrast':contrast,'accepted':accepted}
                if accepted:found['top_'+key]=Match('top_'+key,score,0,(max(0,x-5)+xx+w/2,max(0,y-5)+yy+h/2))
        return found,diagnostics
