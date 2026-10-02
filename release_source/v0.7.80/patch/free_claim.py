"""Shared free-claim reservation and receipt lifecycle; no paid actions."""
from contextlib import contextmanager

class FreeClaimActions:
    @contextmanager
    def free_claim_context(self,task):
        self.trace.task=task
        self.free_reward_request=None
        try:yield
        finally:self.free_reward_request=None

    def free_claim_tap(self,screen,name,task,slot='claim',*,attempt=1,repeat_source='manual_free_claim_retry'):
        from collector import Halt,ScreenChanged
        from adb_device import InputNotSent
        from legacy_free_recovery import FREE_SLOTS
        if slot not in FREE_SLOTS.get(task,()):raise Halt('무료 수령 작업 확인 실패')
        ledger=self.action_state;scope=ledger.scope;reserved=None
        previous=self.claim_counts.get(task,0)
        def same_account():
            if self.action_state is not ledger or ledger.scope!=scope:
                raise ScreenChanged('계정이 바뀌어 수령 입력을 보류합니다.')
        def reserve():
            nonlocal reserved
            same_account()
            with ledger.lock:
                ledger.reserve(task,slot,repeat_authorized=bool(ledger.pending(task,slot)),repeat_source=repeat_source)
                reserved=ledger.pending(task,slot)
            self.claim_counts[task]=attempt
        try:
            fresh=self.tap(screen,name,before_input=reserve,validate=same_account)
        except (ScreenChanged,InputNotSent):
            if reserved:
                with ledger.lock:
                    current=ledger.pending(task,slot)
                    if ledger.scope==scope and current and current.get('id')==reserved.get('id'):
                        ledger.confirm(task,slot,status='uncertain',source='input_not_sent')
                self.claim_counts[task]=previous
            raise
        if reserved and reserved.get('action')==slot:
            self.free_reward_request=(scope,task,slot,reserved['id'])
        return fresh

    def before_free_reward_dismiss(self,screen):
        armed=getattr(self,'free_reward_request',None)
        if not armed or screen.state!='reward' or 'reward_close' not in screen.matches:return
        scope,task,slot,request_id=armed
        if self.action_state.scope!=scope or self.trace.task!=task:return
        if task=='worldboss' and getattr(self,'boss_slot',None)!=slot:return
        with self.action_state.lock:
            request=self.action_state.pending(task,slot)
            if request and request.get('id')==request_id and request.get('action')==slot:
                self.action_state.confirm(task,slot,source='free_reward_confirmed')

    def free_reward_confirmed(self,task,slot='claim'):
        armed=getattr(self,'free_reward_request',None)
        if not armed or armed[:3]!=(self.action_state.scope,task,slot):return False
        entry=self.action_state.get(task)
        return (entry.get('last_input',{}).get('id')==armed[3]
                and entry.get('input_resolution',{}).get('source')=='free_reward_confirmed'
                and entry.get('input_resolution',{}).get('confirmed') is True)
