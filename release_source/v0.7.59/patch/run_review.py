"""A single bounded final pass; never rearm an uncertain resource action."""
from daily_state import DAILY_STEPS


def review_candidates(tasks,results,action_state,daily_records=None):
    records=daily_records or {};selected=[]
    for task in tasks:
        if results.get(task) not in {'failed','unrecognized'}:continue
        if task in DAILY_STEPS:
            record=records.get(task,{})
            details=record.get('_steps',{})
            if any(d.get('pending') or d.get('status') in {'uncertain','blocked'} for d in details.values()):continue
            if record.get('_complete')=='done':continue
        elif action_state.get(task).get('pending') or action_state.blocked(task):continue
        selected.append(task)
    return selected


def progress_snapshot(collector,task):
    from daily_state import step_label
    if task not in DAILY_STEPS or getattr(collector,'daily_ledger',None) is None:return {}
    record=collector.daily_ledger.snapshot(collector.daily_ident,getattr(collector,'daily_day',None)).get(task,{})
    details=record.get('_steps',{});steps={}
    for step in DAILY_STEPS[task]:
        detail=details.get(step,{})
        done=record.get(step)=='done' or record.get('_complete')=='done'
        excluded=bool(detail.get('excluded'))
        state='excluded' if excluded else 'done' if done else detail.get('status','not_started')
        steps[step]={'label':step_label(task,step),'status':state,'reason':detail.get('reason',''),'pending':bool(detail.get('pending'))}
    return {'complete':sum(s['status'] in {'done','excluded'} for s in steps.values()),'total':len(steps),
            'excluded':sum(s['status']=='excluded' for s in steps.values()),'steps':steps}


def final_review(collector,tasks,results,execute,log,stop):
    records=collector.daily_ledger.snapshot(collector.daily_ident,getattr(collector,'daily_day',None)) if getattr(collector,'daily_ledger',None) else {}
    remaining=review_candidates(tasks,results,collector.action_state,records)
    if stop.is_set():return results
    unresolved=[t for t in tasks if results.get(t) in {'attempted','deferred'} or
                (results.get(t) in {'failed','unrecognized'} and t not in remaining)]
    if unresolved:
        collector.trace.event('final_review_held',tasks=unresolved,reason='결과 미확인 또는 반복 실패 / 입력 없는 상태 확인')
        log('결과 미확인 또는 보류 항목 '+str(len(unresolved))+'개 / 중복 실행하지 않고 기록을 유지합니다.')
    if not remaining:return results
    from run_control import checkpoint
    checkpoint(stop)
    if stop.is_set():return results
    collector.forget_observations()
    collector.trace.event('final_review',tasks=remaining)
    log('마지막 누락 재점검 / 결과 미확인 입력은 반복하지 않습니다.')
    # Retain the same collector, pending records and consumed retry permissions.
    permissions=getattr(collector,'manual_retry_tasks',set())
    permissions.difference_update(remaining)
    checked=execute(remaining)
    return {**results,**checked}
