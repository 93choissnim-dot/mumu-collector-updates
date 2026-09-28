"""Read the fixed settlement label only after independent boss-page proof."""
import base64
import json
from pathlib import Path
import cv2
import numpy as np

class BossSeason:
    def __init__(self,assets):
        data=json.loads((Path(assets)/'boss_settlement.json').read_text(encoding='utf-8'))
        self.box=data['box']
        self.template=cv2.imdecode(np.frombuffer(base64.b64decode(data['png']),np.uint8),cv2.IMREAD_COLOR)
        self.shape=self.red_text(self.template)
        self.mask=self.shape>20

    @staticmethod
    def red_text(image):
        # Neutral weather/scenery changes cancel out; preserve the red glyphs.
        red=np.maximum(image[:,:,2].astype(float)-np.maximum(image[:,:,0],image[:,:,1]),0).astype(np.float32)
        return cv2.GaussianBlur(red,(7,7),1.3)
    def settling(self,image):
        x,y,r,b=self.box
        for dy in range(-2,3):
            for dx in range(-2,3):
                tile=image[y+dy:b+dy,x+dx:r+dx]
                shape=self.red_text(tile)
                score=float(cv2.matchTemplate(shape,self.shape,cv2.TM_CCOEFF_NORMED)[0,0])
                light=float(shape[self.mask].mean()/max(self.shape[self.mask].mean(),1.))
                if score>=.94 and .55<=light<=1.6:return True
        return False
