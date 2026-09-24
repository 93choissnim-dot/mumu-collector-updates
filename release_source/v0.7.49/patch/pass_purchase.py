"""Read-only recognition of a won price on the three daily membership pages."""
from pathlib import Path
import cv2
import numpy as np


class PassPurchaseVision:
    def __init__(self, assets):
        atlas=cv2.imdecode(np.fromfile(Path(assets)/'pass_purchase.png',np.uint8),cv2.IMREAD_COLOR)
        if atlas is None:raise ValueError('패스 가격 인식 이미지가 없습니다.')
        self.currency=atlas[:23,:23]
        self.heading=atlas[24:60,:248]
        self.tab=atlas[61:84,:86]

    @staticmethod
    def locate(im,template,box,threshold=.90):
        x,y,r,b=box;roi=cv2.cvtColor(im[y:b,x:r],cv2.COLOR_BGR2GRAY)
        reference=cv2.cvtColor(template,cv2.COLOR_BGR2GRAY);best=None
        for scale in (.94,1.,1.06):
            t=cv2.resize(reference,None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA)
            h,w=t.shape
            if h>roi.shape[0] or w>roi.shape[1]:continue
            _,score,_,pos=cv2.minMaxLoc(cv2.matchTemplate(roi,t,cv2.TM_CCOEFF_NORMED))
            xx,yy=pos;patch=roi[yy:yy+h,xx:xx+w]
            # Dimmed purchase dialogs cannot complete the underlying page.
            good=(score>=threshold and patch.mean()>=reference.mean()*.78
                  and .65<=patch.std()/max(1,reference.std())<=1.65)
            if good and (best is None or score>best[0]):best=(float(score),x+xx,y+yy,w,h)
        return best

    def recognize(self,im,found):
        from vision import Match
        # The user's cropped screenshot has a clipped page title. A separate
        # heading + selected-tab pair identifies only this purchase-only page.
        gear_context=(self.locate(im,self.heading,(125,50,425,120),.93)
                      and self.locate(im,self.tab,(0,165,130,225),.93))
        for key,box in (('ad',(600,465,855,530)),('keys',(600,465,855,530)),
                        ('gear',(425,465,690,530))):
            context='pass_title' in found and 'pass_'+key in found
            if not context and not (key=='gear' and gear_context):continue
            price=self.locate(im,self.currency,box,.92)
            if not price:continue
            score,x,y,w,h=price
            # A currency glyph alone is insufficient: require at least three
            # numeral-sized strokes immediately to its right on the same row.
            gray=cv2.cvtColor(im[y:y+h,x+w:min(box[2],x+w+125)],cv2.COLOR_BGR2GRAY)
            if not gray.size:continue
            mask=(gray>float(np.median(gray))+28).astype(np.uint8)
            _,_,stats,_=cv2.connectedComponentsWithStats(mask)
            digits=[s for s in stats[1:] if .4*h<=s[3]<=h and 2<=s[2]<=.8*h and s[4]>=.9*h]
            digits.sort(key=lambda s:s[0])
            if len(digits)<3 or digits[0][0]>.7*h:continue
            if any(b[0]-(a[0]+a[2])>h for a,b in zip(digits,digits[1:])):continue
            if key=='gear' and not context:
                found['pass_purchase_gear_context']=Match('daily_pass_purchase_gear_context',1,0,(0,0))
            name='pass_'+key+'_purchase'
            found[name]=Match('daily_'+name,score,0,(x+w/2,y+h/2))
            # Purchase evidence must never expose an actionable claim marker.
            found.pop('pass_'+key+'_active',None)
