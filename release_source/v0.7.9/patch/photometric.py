"""Screen-local brightness calibration for active/disabled reward buttons."""
import json
from pathlib import Path
import cv2
import numpy as np


def gray_image(image):
    return cv2.GaussianBlur(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),(3,3),.7)


def locate(gray,template,box):
    x1,y1,x2,y2=box
    x0,y0=max(0,x1-7),max(0,y1-7)
    roi=gray[y0:min(540,y2+7),x0:min(960,x2+7)]
    _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(roi,template,cv2.TM_CCOEFF_NORMED))
    x,y=x0+point[0],y0+point[1];h,w=template.shape
    return float(score),(x,y),gray[y:y+h,x:x+w]


class ButtonProfiles:
    def __init__(self,assets):
        assets=Path(assets);path=assets/'button_profiles.json'
        self.profiles={}
        if not path.exists():return
        for key,spec in json.loads(path.read_text(encoding='utf-8')).items():
            def read(name):
                image=cv2.imdecode(np.fromfile(assets/name,np.uint8),cv2.IMREAD_COLOR)
                if image is None:raise ValueError('버튼 기준 이미지가 없습니다: '+name)
                return gray_image(image)
            self.profiles[key]={**spec,'references':{state:read(spec[state+'_file']) for state in ('active','empty')},
                                'contexts':[(a['box'],read(a['file'])) for a in spec['anchors']]}
            # Alternative native renderings share this profile's exposure basis.
            # Their gain/offset were measured from the independent page labels
            # in the same capture, never fitted to the reward button itself.
            variants={}
            for state in ('active','empty'):
                variants[state]=[]
                for item in spec.get(state+'_variants',[]):
                    gain=float(item.get('gain',1));offset=float(item.get('offset',0))
                    if not (.60<=gain<=1.80 and -80<=offset<=80):
                        raise ValueError('버튼 기준 이미지의 밝기 보정값이 올바르지 않습니다.')
                    template=read(item['file'])
                    if template.shape!=self.profiles[key]['references'][state].shape:
                        raise ValueError('버튼 기준 이미지의 크기가 일치하지 않습니다.')
                    normalized=np.clip((template.astype(np.float32)-offset)/gain,0,255).astype(np.uint8)
                    variants[state].append((item['file'],normalized))
            self.profiles[key]['variants']=variants

    def recognize(self,gray):
        results={};diagnostics={}
        for key,p in self.profiles.items():
            reference=[];observed=[];anchors=[]
            for box,template in p['contexts']:
                score,_,patch=locate(gray,template,box)
                anchors.append(score)
                if score<.90:break
                # Crop boundaries and resize interpolation are not exposure
                # evidence; fit the same interior glyph/background pixels.
                reference.append(template[2:-2,2:-2].reshape(-1))
                observed.append(patch[2:-2,2:-2].reshape(-1))
            d={'anchor_scores':anchors};diagnostics[key]=d
            if len(reference)!=len(p['contexts']):
                d['status']='context_missing';continue
            a=np.concatenate(reference).astype(np.float32)
            b=np.concatenate(observed).astype(np.float32)
            variance=float(a.var())
            if variance<9:d['status']='context_flat';continue
            gain=float(np.mean((a-a.mean())*(b-b.mean()))/variance)
            offset=float(b.mean()-gain*a.mean())
            fit=float(np.abs(b-(gain*a+offset)).mean())
            d.update(gain=gain,offset=offset,context_error=fit)
            # Do not calibrate through heavily dimmed or unrelated dialogs.
            if not (.60<=gain<=1.80 and -80<=offset<=80 and fit<=10):
                d['status']='context_unreliable'
                results[key]={'names':(p['active'],p['empty']),'match':None,'required':p['markers']}
                continue
            uncertainty=fit/gain
            error_limit=10+uncertainty;decision_margin=4+uncertainty
            d.update(error_limit=error_limit,decision_margin=decision_margin)
            candidates=[];all_errors=[];shape_seen=False
            for state,template in p['references'].items():
                evidence=[]
                references=[(p[state+'_file'],template)]+p['variants'][state]
                for filename,reference in references:
                    score,point,patch=locate(gray,reference,p['box'])
                    normalized=(patch.astype(np.float32)-offset)/gain
                    error=float(np.abs(normalized-reference.astype(np.float32)).mean())
                    contrast=float(normalized.std()/max(float(reference.std()),1))
                    evidence.append({'score':score,'error':error,'contrast':contrast,
                                     'position':list(point),'reference':filename})
                    shape_seen=shape_seen or score>=.88
                    if score>=.88 and error<=error_limit and .65<=contrast<=1.60:
                        candidates.append((error,state,score,point,reference.shape))
                best=min(evidence,key=lambda e:e['error'])
                d[state]={**best,'variants':evidence}
                # Compare the closest evidence for each state, including
                # rejected references, so adding a variant cannot hide a tie.
                all_errors.append((best['error'],state))
            if not shape_seen:d['status']='button_missing';continue
            candidates.sort();all_errors.sort()
            result=None
            if (candidates and candidates[0][1]==all_errors[0][1]
                    and all_errors[1][0]-all_errors[0][0]>=decision_margin):
                error,state,score,(x,y),(h,w)=candidates[0]
                result=(p[state],score,error,(x+w/2,y+h/2))
                d['status']=state
            else:d['status']='ambiguous'
            # With a confirmed context and button, calibrated evidence replaces
            # raw-color candidates. Ambiguous appearance must never become a tap.
            results[key]={'names':(p['active'],p['empty']),'match':result,'required':p['markers']}
        return results,diagnostics
