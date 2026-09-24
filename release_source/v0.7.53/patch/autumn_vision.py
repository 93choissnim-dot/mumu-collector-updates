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
        # Native ADB renders the numeric outline differently from video.
        # Keep a separate calibrated reference instead of blurring digits.
        self.native_zero=cv2.imdecode(np.fromfile(assets/'autumn_zero_native.png',np.uint8),cv2.IMREAD_COLOR)
        if self.native_zero is None:raise ValueError('가을맞이 숫자 인식 이미지가 없습니다.')
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
        # The animated title background is identity evidence, not an exposure
        # reference. Rank text and the home icon are independent of the claim.
        anchors=('autumn_title','autumn_rank')
        if all(located[n][3] for n in anchors):
            references=('autumn_rank','autumn_home')
            from recognition_common import fit_exposure
            gain,offset,error,_=fit_exposure([self.templates[n][0] for n in references],
                                            [located[n][0] for n in references])
            calibrated=all(located[n][3] for n in references) and np.all((gain>=.85)&(gain<=1.4)) and np.all(np.abs(offset)<=45) and error<=8
            self.diagnostics['_exposure']={'accepted':bool(calibrated),'error':error,'anchors':list(references)}
            for name in ('autumn_active','autumn_empty','autumn_zero'):
                patch,score,center,visible=located[name];ref=self.templates[name][0]
                normalized=np.clip((patch.astype(np.float32)-offset)/gain,0,255) if calibrated else patch.astype(np.float32)
                mae=float(np.abs(normalized-ref).mean())
                # ADB can render dark glyph outlines more sharply than video.
                # Compare smoothed lettering only after independent calibration;
                # keep the original color gate and leave numeric matching strict.
                outline=False;smoothed_score=None
                if calibrated and name in {'autumn_active','autumn_empty'} and score>=.85:
                    a=cv2.GaussianBlur(cv2.cvtColor(normalized.astype(np.uint8),cv2.COLOR_BGR2GRAY),(5,5),1.3)
                    b=cv2.GaussianBlur(self.templates[name][1],(5,5),1.3)
                    smoothed_score=float(cv2.matchTemplate(a,b,cv2.TM_CCOEFF_NORMED)[0,0])
                    d=self.diagnostics[name]
                    outline=smoothed_score>=.94 and .80<=d['light']<=1.65 and .65<=d['contrast']<=1.65
                good=(visible or outline) and mae<=12
                native_zero=False
                if name=='autumn_zero' and calibrated and not good:
                    d=self.diagnostics[name]
                    native_gray=cv2.cvtColor(self.native_zero,cv2.COLOR_BGR2GRAY)
                    normalized_gray=cv2.cvtColor(normalized.astype(np.uint8),cv2.COLOR_BGR2GRAY)
                    native_score=float(cv2.matchTemplate(normalized_gray,native_gray,cv2.TM_CCOEFF_NORMED)[0,0])
                    native_mae=float(np.abs(normalized-self.native_zero).mean())
                    # The first digit must independently be zero. Shared '/10'
                    # lettering must never hide a changed or unreadable count.
                    digit_score=float(cv2.matchTemplate(normalized_gray[2:15,7:17],native_gray[2:15,7:17],cv2.TM_CCOEFF_NORMED)[0,0])
                    native_zero=native_score>=.98 and digit_score>=.98 and native_mae<=8 and .80<=d['light']<=1.65 and .65<=d['contrast']<=1.65
                    good=bool(native_zero)
                    self.diagnostics[name].update(native_score=native_score,native_mae=native_mae,digit_score=digit_score)
                self.diagnostics[name].update(accepted=bool(good),mae=mae,smoothed_score=smoothed_score,outline_fallback=bool(outline and not visible))
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
