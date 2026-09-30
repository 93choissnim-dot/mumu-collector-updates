"""Publish task causes consistently without replaying or changing input ledgers."""
from datetime import datetime,timezone
from daily_state import DAILY_TASKS
from history import ISSUES,RESULTS
from run_review import progress_snapshot
from today_overview import pending_reason


class RunOutcomes:
    """One collector execution only; late issues amend causes, never result counts."""
    def __init__(self,ident,scope,history,journal,emit,log):
        self.ident=ident;self.scope=scope;self.history=history;self.journal=journal
        self.emit=emit;self.log=log;self.entries={};self.pending_issues={}

    def _pending(self,task,collector):
        if collector is None:return ''
        if task in DAILY_TASKS:
            ledger=getattr(collector,'daily_ledger',None)
            if ledger is None:return ''
            record=ledger.snapshot(collector.daily_ident,getattr(collector,'daily_day',None)).get(task,{})
            pending={s:d for s,d in record.get('_steps',{}).items() if isinstance(d,dict) and d.get('pending')}
        else:pending=collector.action_state.get(task).get('pending',{})
        return pending_reason(task,pending)

    def _reason(self,task,result,collector,reason):
        if not reason and result=='waiting' and collector is not None:
            reason=getattr(collector,'wait_reasons',{}).get(task,'시즌 정산 대기')
        if not reason and result in ISSUES and collector is not None and task in DAILY_TASKS:
            if getattr(collector,'daily_task',None)==task and collector.trace.task==task:
                reason=getattr(collector,'daily_summary','')
        guidance=self._pending(task,collector) if result in ISSUES else ''
        if guidance and guidance not in (reason or ''):reason='\n'.join(filter(None,(reason,guidance)))
        if not reason:
            reason={'skipped':'현재 화면에서 수령 조건 또는 받을 보상 없음 확인',
                    'unavailable':'이벤트 화면에서 대상 이벤트 없음 확인',
                    'no_entries':'던전별 입장 횟수 소진 확인',
                    'already_complete':'완료 또는 유료 제외 기록 확인',
                    'already_claimed':'이전 완료 기록 확인'}.get(result,RESULTS.get(result,'') if result in ISSUES else '')
        return str(reason or '')[:2000]

    def record(self,task,result,collector=None,reason=None):
        issue=self.pending_issues.pop(task,None)
        if not reason and result in ISSUES:reason=issue
        reason=self._reason(task,result,collector,reason)
        progress=progress_snapshot(collector,task) if collector is not None else {}
        run_id=collector.trace.run_id if collector is not None else None
        entry={'result':result,'reason':reason,'progress':progress,'run_id':run_id,
               'checked_at':datetime.now(timezone.utc).isoformat()}
        self.entries[task]=entry
        if self.journal is not None:self.journal.result(self.scope,task,result,entry=entry)
        self.emit('fleet_entry',(self.ident,task,entry))
        if collector is not None:collector.trace.event('task_outcome',task=task,result=result,reason=reason,progress=progress)
        try:self.history.record(self.scope,task,result,reason=reason,run_id=run_id,progress=progress)
        except OSError as exc:self.log('이력 저장 실패: '+str(exc))
        self.emit('fleet_result',(self.ident,task,result))
        return entry

    def issue(self,task,reason,collector=None):
        if not task or not str(reason or '').strip():return
        reason=str(reason)
        trace=collector.trace if collector is not None else None
        if trace is not None:
            trace.event('task_issue',task=task,step=(trace.step or 'task') if trace.task==task else 'task',reason=reason)
        entry=self.entries.get(task)
        if entry is None:
            self.pending_issues[task]=reason
            return
        if entry['result'] not in ISSUES or trace is None or entry['run_id']!=trace.run_id:return
        updated={**entry,'reason':self._reason(task,entry['result'],collector,reason)}
        current=self.history.get(self.scope,task)
        owned=current.get('run_id')==trace.run_id and current.get('result')==entry['result']
        if owned:
            try:self.history.issue(self.scope,task,updated['reason'])
            except OSError as exc:self.log('실패 원인 저장 실패: '+str(exc))
        if self.journal is not None:
            current=self.journal.data.get(self.scope,{}).get('entries',{}).get(task,{})
            if current.get('run_id')==trace.run_id and current.get('result')==entry['result']:
                self.journal.result(self.scope,task,entry['result'],entry=updated);owned=True
        self.entries[task]=updated
        # Re-publish the same outcome with its cause; no additional result event.
        if owned:self.emit('fleet_entry',(self.ident,task,updated))
        trace.event('task_outcome',task=task,result=entry['result'],reason=updated['reason'],progress=entry['progress'])
