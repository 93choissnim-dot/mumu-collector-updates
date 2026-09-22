"""Shared exposure fitting; callers keep their own acceptance thresholds."""
import cv2
import numpy as np


def fit_exposure(references, observed):
    def samples(images):
        return np.concatenate([cv2.GaussianBlur(im,(3,3),.7)[2:-2,2:-2].reshape(-1,3) for im in images]).astype(np.float32)
    a,b=samples(references),samples(observed)
    gain=np.mean((a-a.mean(0))*(b-b.mean(0)),0)/np.maximum(a.var(0),1)
    offset=b.mean(0)-gain*a.mean(0)
    error=float(np.abs(b-(gain*a+offset)).mean())
    return gain,offset,error,a.var(0)


class TransitionWatch:
    """Bounded wait: stable unknown target regions stop earlier than changing ones."""
    def __init__(self,start,timeout,stall=8):
        self.end=start+timeout;self.last_change=start;self.stall=stall;self.previous=None
    def observe(self,image,now,box=None):
        if not isinstance(image,np.ndarray) or image.size==0:return
        im=cv2.resize(image,(960,540))
        if box:
            x,y,r,b=box;im=im[y:b,x:r]
        sample=cv2.resize(cv2.cvtColor(im,cv2.COLOR_BGR2GRAY),(64,36))
        if self.previous is None or float(np.abs(sample.astype(float)-self.previous).mean())>2:
            self.last_change=now
        self.previous=sample
    def expired(self,now):return now>=self.end or now-self.last_change>=self.stall
