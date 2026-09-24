"""Bounded local evidence for one execution; never records the PC desktop."""
from collections import deque
from datetime import datetime
import time
import uuid

class ExecutionTrace:
    def __init__(self):
        self.run_id=uuid.uuid4().hex
        self.started_at=datetime.now().astimezone().isoformat()
        self.started=time.monotonic();self.events=deque(maxlen=200)
        self.frames=deque(maxlen=6);self.last_frame=-10
        self.task=None;self.step=None;self.expected=[]
        self.failure_steps=set()
        self.timing={'captures':0,'capture_seconds':0.,'recognition_seconds':0.}
    def event(self,kind,**fields):
        self.events.append({'at':round(time.monotonic()-self.started,3),'kind':kind,
                            'task':self.task,'step':self.step,**fields})
    def observe(self,image,screen,capture_time,recognition_time):
        self.timing['captures']+=1;self.timing['capture_seconds']+=capture_time
        self.timing['recognition_seconds']+=recognition_time
        self.event('screen',actual=screen.state,expected=list(self.expected))
        now=time.monotonic()
        if now-self.last_frame>=2:
            self.frame(image,screen);self.last_frame=now
    def frame(self,image,screen):
        import cv2
        import numpy as np
        if not isinstance(image,np.ndarray) or image.size==0:return
        small=cv2.resize(image,(960,540))
        ok,raw=cv2.imencode('.jpg',small,[cv2.IMWRITE_JPEG_QUALITY,75])
        if ok:self.frames.append(({'at':round(time.monotonic()-self.started,3),
            'state':screen.state,'task':self.task,'step':self.step},raw.tobytes()))
    def snapshot(self):
        return {'run_id':self.run_id,'started_at':self.started_at,'task':self.task,'step':self.step,
                'expected':list(self.expected),'timing':dict(self.timing),'events':list(self.events)}
