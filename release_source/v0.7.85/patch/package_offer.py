"""Recognize the timed offer panel; expose only its explicit close control."""
import base64,json
from pathlib import Path
import cv2
import numpy as np


class PackageOfferVision:
    def __init__(self,assets):
        specs=json.loads((Path(assets)/'package_offer.json').read_text(encoding='utf-8'))
        self.templates={}
        for key,spec in specs.items():
            tile=cv2.imdecode(np.frombuffer(base64.b64decode(spec['png']),np.uint8),1)
            gray=cv2.GaussianBlur(cv2.cvtColor(tile,cv2.COLOR_BGR2GRAY),(3,3),.7).astype(np.float32)
            # Keep interpolation at the crop boundary out of the comparison.
            # The actual glyph remains intact, including all four X arms.
            x,y,r,b=spec['box']
            self.templates[key]=(gray[2:-2,2:-2],(x+2,y+2,r-2,b-2))

    def recognize(self,image):
        accepted={};diagnostics={}
        for key,(template,(x,y,r,b)) in self.templates.items():
            roi=image[y-3:b+3,x-3:r+3]
            gray=cv2.GaussianBlur(cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY),(3,3),.7).astype(np.float32)
            _,score,_,(xx,yy)=cv2.minMaxLoc(cv2.matchTemplate(gray,template,cv2.TM_CCOEFF_NORMED))
            h,w=template.shape;patch=gray[yy:yy+h,xx:xx+w]
            mae=float(np.abs(patch-template).mean())
            light=float(patch.mean()/max(template.mean(),1))
            ok=score>=.92 and mae<=18 and .80<=light<=1.25
            diagnostics[key]={'score':float(score),'mae':mae,'light':light,'accepted':ok}
            if ok:accepted[key]=(x-3+xx+w/2,y-3+yy+h/2)
        # The two labels establish panel identity even if its X is obscured.
        # Such a partial panel must block background navigation, without a tap.
        if not {'timer','limit'}<=accepted.keys():return None,{},diagnostics
        from vision import Match
        matches={}
        if 'close' in accepted:
            matches['package_offer_close']=Match('package_offer_close',diagnostics['close']['score'],0,accepted['close'])
        return 'package_offer',matches,diagnostics
