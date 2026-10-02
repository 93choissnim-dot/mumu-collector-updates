"""Recognize the normal/integrated boss chooser by its paired labels."""
import base64
import json
from pathlib import Path
import cv2
import numpy as np

class BossModeVision:
    def __init__(self,assets):
        self.specs=json.loads((Path(assets)/'boss_mode_controls.json').read_text())
        self.refs={k:cv2.imdecode(np.frombuffer(base64.b64decode(v['png']),np.uint8),0)
                   for k,v in self.specs.items()}

    def recognize(self,image):
        from vision import Match
        gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
        def find(key,roi):
            x,y,r,b=map(int,roi);x=max(0,x);y=max(0,y);r=min(960,r);b=min(540,b)
            area=gray[y:b,x:r];ref=self.refs[key];h,w=ref.shape
            if area.shape[0]<h or area.shape[1]<w:return None
            _,score,_,(xx,yy)=cv2.minMaxLoc(cv2.matchTemplate(area,ref,cv2.TM_CCOEFF_NORMED))
            crop=area[yy:yy+h,xx:xx+w].astype(float);t=ref.astype(float)
            error=float(np.abs((crop-crop.mean())-(t-t.mean())).mean())
            light=float(crop.mean()/max(1,t.mean()))
            if score<.90 or error>19 or not .75<light<1.3:return None
            return score,error,(x+xx+w/2,y+yy+h/2)
        title=find('title',(35,35,380,155))
        if not title:return None,{}
        box=self.specs['title']['box'];dx=title[2][0]-(box[0]+box[2])/2;dy=title[2][1]-(box[1]+box[3])/2
        values={'title':title}
        for key in ('close','normal','integrated'):
            x,y,r,b=self.specs[key]['box']
            values[key]=find(key,(x+dx-8,y+dy-8,r+dx+8,b+dy+8))
        # Generic world-boss title alone also appears on the legacy card page.
        if not (values['normal'] or values['integrated']):return None,{}
        found={}
        for key,value in values.items():
            if value is None:continue
            if key=='normal' and not all(values.values()):continue
            name='x_boss_mode_'+('integrated_label' if key=='integrated' else key)
            found[name]=Match(name,*value)
        return 'boss_mode',found
