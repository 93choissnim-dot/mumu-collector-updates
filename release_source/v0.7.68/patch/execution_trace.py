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
        self._task=None;self.task_started=self.started;self.step=None;self.expected=[]
        self.task_outcomes={};self.failed_steps={}
        self.failure_steps=set()
        self.timing={'captures':0,'capture_seconds':0.,'recognition_seconds':0.}
    @property
    def task(self):return self._task
    @task.setter
    def task(self,value):
        if value!=self._task:self.task_started=time.monotonic()
        self._task=value
    def event(self,kind,**fields):
        now=time.monotonic()
        event={'at':round(now-self.started,3),'kind':kind,
               'task':self.task,'step':self.step,**fields}
        self.events.append(event)
        # Outcomes must survive screen-event eviction during long fleet runs.
        task=event.get('task')
        if kind=='task_outcome' and task:
            self.task_outcomes[task]={'task':task,'result':str(event.get('result',''))[:64],
                'reason':str(event.get('reason',''))[:300],
                'duration_seconds':round(now-self.task_started,3) if task==self.task else None}
            if len(self.task_outcomes)>32:self.task_outcomes.pop(next(iter(self.task_outcomes)))
        # 'uncertain' also reserves an input before dispatch; only an actual
        # unresolved outcome has a reason. Keep genuine failures after recovery.
        failed_checkpoint=(event.get('status') in {'failed','blocked'} or
            (event.get('status')=='uncertain' and bool(str(event.get('reason') or '').strip())))
        if kind=='checkpoint' and failed_checkpoint:
            key=(task,event.get('step'))
            self.failed_steps[key]={'task':task,'step':event.get('step'),
                'reason':str(event.get('reason',''))[:300]}
            if len(self.failed_steps)>32:self.failed_steps.pop(next(iter(self.failed_steps)))
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
        failures=dict(self.failed_steps)
        for task,step in sorted(self.failure_steps):
            failures.setdefault((task,step),{'task':task,'step':step,'reason':''})
        return {'run_id':self.run_id,'started_at':self.started_at,
                'finished_at':datetime.now().astimezone().isoformat(),
                'duration_seconds':round(time.monotonic()-self.started,3),
                'task_outcomes':list(self.task_outcomes.values()),'failure_steps':list(failures.values())[:32],
                'task':self.task,'step':self.step,
                'expected':list(self.expected),'timing':dict(self.timing),'events':list(self.events)}
