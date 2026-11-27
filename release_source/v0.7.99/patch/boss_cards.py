"""Independent lower-card identities when notification banners hide boss names."""
import base64
import json
from pathlib import Path
import cv2
import numpy as np

class BossCards:
    def __init__(self,assets):
        self.specs=json.loads((Path(assets)/'boss_cards.json').read_text(encoding='utf-8'))
        self.refs={k:cv2.imdecode(np.frombuffer(base64.b64decode(v['png']),np.uint8),0)
                   for k,v in self.specs.items()}

    def recognize(self,image,matches):
        from vision import Match
        from world_boss import BOSSES
        if 'x_boss_select_title' not in matches:return {}
        names_visible=all(b[2] in matches for b in BOSSES)
        gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
        found={}
        for key,spec in self.specs.items():
            x,y,r,b=spec['box'];ref=self.refs[key];h,w=ref.shape
            area=gray[y-3:b+3,x-3:r+3]
            _,score,_,(xx,yy)=cv2.minMaxLoc(cv2.matchTemplate(area,ref,cv2.TM_CCOEFF_NORMED))
            crop=area[yy:yy+h,xx:xx+w].astype(float);template=ref.astype(float)
            error=float(np.abs((crop-crop.mean())-(template-template.mean())).mean())
            light=float(crop.mean()/max(1,template.mean()))
            if score<.93 or error>16 or not .75<light<1.3:return {}
            found[key]=(score,error,(x-3+xx+w/2,y-3+yy+h/2))
        # Navigation only: these matches never imply that a reward is available.
        result={card:Match(card,*found[key]) for key,_,card,_ in BOSSES}
        if not names_visible:
            result['x_boss_notices_unreadable']=Match('x_boss_notices_unreadable',1,0,(0,0))
        return result
