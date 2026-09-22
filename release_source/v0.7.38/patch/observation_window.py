"""Reuse consecutive observations only until input, pause, or a short expiry."""
from run_control import checkpoint


class ObservationWindow:
    def forget_observations(self):
        self._observations=[]

    def remember_observation(self,screen,generation):
        observations=getattr(self,'_observations',[])
        observations.append((self.now(),generation,screen))
        self._observations=observations[-2:]

    def confirmation_seed(self,key):
        from collector import Halt
        checkpoint(self.stop)
        if self.stop.is_set():raise Halt('사용자가 중지했습니다.')
        observations=getattr(self,'_observations',[])
        if not observations or observations[-1][2] is not self.last_screen:return None,0,None
        generation=getattr(self.stop,'generation',None);now=self.now()
        prior=None;count=0;last=None
        for at,seen_generation,screen in observations:
            if seen_generation!=generation or not 0<=now-at<=.75:
                prior=None;count=0;continue
            current=key(screen)
            count=count+1 if current is not None and current==prior else int(current is not None)
            prior=current;last=screen
        return prior,count,last

    def post_input(self,before,name=None,delay=.65):
        """Observe early; shorten only a confirmed page/control transition.

        An unchanged or unreadable screen retains the full original delay.
        Observations are shared with the following page/button waiter. Every
        actual touch still takes a separate fresh capture in verified_tap.
        """
        end=self.now()+delay
        self.pause(min(.12,delay))
        previous=None
        while self.now()<end:
            current=self.screen()
            opposite=None
            if name and name.endswith('_active'):
                opposite=next((n for n in (name[:-7]+'_empty',name[:-7]+'_done') if n in current.matches),None)
            elif name and name.startswith('ready_'):
                opposite='empty_'+name[6:] if 'empty_'+name[6:] in current.matches else None
            changed=current.state not in {'unknown','reward','equipment','offline_reward'} and (
                current.state!=before.state or (opposite and name not in current.matches))
            key=(current.state,opposite) if changed else None
            if key is not None and key==previous:return
            if key is None:
                self.pause(max(0,end-self.now()));return
            previous=key
            self.pause(min(.15,max(0,end-self.now())))
