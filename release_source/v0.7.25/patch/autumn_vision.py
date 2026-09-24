"""Autumn event identity and independent free-claim state recognition."""
import json
from pathlib import Path
import cv2
import numpy as np


class AutumnVision:
    def __init__(self,assets):
        assets=Path(assets)
        self.specs=json.loads((assets/'autumn_templates.json').read_text(encoding='utf-8'))
        atlas=cv2.imdecode(np.fromfile(assets/'autumn_atlas.png',np.uint8),cv2.IMREAD_COLOR)
        if atlas is None:raise ValueError('가을맞이 인식 이미지가 없습니다.')
        self.templates={}
        for name,spec in self.specs.items():
            x,y,r,b=spec['tile'];color=atlas[y:b,x:r].copy()
            self.templates[name]=(color,cv2.cvtColor(color,cv2.COLOR_BGR2GRAY))
        self.diagnostics={}

    def recognize(self,im):
        from vision import Match
        gray=cv2.cvtColor(im,cv2.COLOR_BGR2GRAY);located={};found={};self.diagnostics={}
        for name,spec in self.specs.items():
            color,template=self.templates[name];h,w=template.shape
            x,y,r,b=spec.get('search',spec['box']);x=max(0,x-4);y=max(0,y-4);r=min(960,r+4);b=min(540,b+4)
            _,score,_,loc=cv2.minMaxLoc(cv2.matchTemplate(gray[y:b,x:r],template,cv2.TM_CCOEFF_NORMED))
            xx,yy=x+loc[0],y+loc[1];patch=im[yy:yy+h,xx:xx+w]
            gp=gray[yy:yy+h,xx:xx+w]
            light=float(gp.mean()/max(1,template.mean()));contrast=float(gp.std()/max(1,template.std()))
            # Fixed text can become darker under gamma/contrast changes. Claim
            # controls retain a separate, stricter visibility and color gate.
            minimum_light=.80 if name in {'autumn_active','autumn_empty','autumn_zero'} else .60
            visible=score>=spec['threshold'] and minimum_light<=light<=1.65 and .65<=contrast<=1.65
            located[name]=(patch,float(score),(xx+w/2,yy+h/2),visible)
            self.diagnostics[name]={'score':float(score),'light':light,'contrast':contrast,'accepted':bool(visible)}
            if visible:found[name]=Match(name,float(score),0,(xx+w/2,yy+h/2))
        # Calibrate from fixed event labels, never from a claim button or count.
        anchors=('autumn_title','autumn_rank')
        if all(located[n][3] for n in anchors):
            refs=np.concatenate([self.templates[n][0].reshape(-1,3) for n in anchors]).astype(np.float32)
            observed=np.concatenate([located[n][0].reshape(-1,3) for n in anchors]).astype(np.float32)
            gain=np.mean((refs-refs.mean(0))*(observed-observed.mean(0)),0)/np.maximum(refs.var(0),1)
            offset=observed.mean(0)-gain*refs.mean(0)
            error=float(np.abs(observed-(refs*gain+offset)).mean())
            calibrated=np.all((gain>=.85)&(gain<=1.4)) and np.all(np.abs(offset)<=45) and error<=8
            self.diagnostics['_exposure']={'accepted':bool(calibrated),'error':error}
            for name in ('autumn_active','autumn_empty','autumn_zero'):
                patch,score,center,visible=located[name];ref=self.templates[name][0]
                normalized=np.clip((patch.astype(np.float32)-offset)/gain,0,255) if calibrated else patch.astype(np.float32)
                mae=float(np.abs(normalized-ref).mean())
                good=visible and mae<=12
                self.diagnostics[name].update(accepted=bool(good),mae=mae)
                found.pop(name,None)
                if good:found[name]=Match(name,score,mae,center)
            page=all(n in found for n in (*anchors,'autumn_reward_label','autumn_home'))
            if page:
                # An inactive control alone is insufficient to claim completion.
                hsv=cv2.cvtColor(im[470:489,919:938],cv2.COLOR_BGR2HSV)
                notice=((hsv[:,:,0]<12)|(hsv[:,:,0]>170))&(hsv[:,:,1]>100)&(hsv[:,:,2]>95)
                notice_present=int(notice.sum())>=16
                active='autumn_active' in found and 'autumn_empty' not in found and 'autumn_zero' not in found and notice_present
                empty='autumn_empty' in found and 'autumn_active' not in found and 'autumn_zero' in found and not notice_present
                if not active:found.pop('autumn_active',None)
                if not empty:found.pop('autumn_empty',None)
                found['event_home']=found['autumn_home']
                self.diagnostics['_claim']={'active':active,'empty':empty,'notice':notice_present}
                return 'autumn',found
        # Prevent partially visible page controls from authorizing any claim.
        for name in ('autumn_active','autumn_empty','autumn_zero'):found.pop(name,None)
        if all(n in found for n in ('event_title','event_home')):return 'event_menu',found
        return None,{}
