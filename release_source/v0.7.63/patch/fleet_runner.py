"""One worker, independent per-instance schedules, bounded failed-room retries."""
import time
from run_support import Schedule
from collector import Halt
from history import TERMINAL_RESULTS
from run_control import RunControl, checkpoint


def run_fleet(jobs, repeat, stop, update_pending, execute, event, clock=time.monotonic, idle=None):
    if isinstance(stop, RunControl):
        clock = stop.clock
    schedules={j['id']:Schedule(j['rooms'],j['minutes']*60) for j in jobs}
    unfinished={j['id'] for j in jobs};announced_due=None
    while unfinished and not stop.is_set() and not update_pending.is_set():
        checkpoint(stop)
        if update_pending.is_set():break
        choices=[(schedules[j['id']].next()[0],n,j) for n,j in enumerate(jobs) if j['id'] in unfinished]
        due,_,job=min(choices,key=lambda item:(item[0],item[1]))
        if due>clock():
            if announced_due is None or abs(due-announced_due)>.1:
                event('fleet_wait',due);announced_due=due
            if idle is not None:idle()
            if stop.wait(min(1.,max(0,due-clock()))):break
            continue
        announced_due=None
        _,rooms,retry=schedules[job['id']].next()
        event('fleet_status',(job['id'],{'status':'재시도 중' if retry else '수령 중','next_at':None,'rooms':list(rooms),'results':{},'phase':'게임 화면 확인 중'}))
        try:results=execute(job,rooms)
        except Exception as exc:
            if stop.is_set():break
            results={r:'failed' for r in rooms}
            event('log',job['name']+': '+str(exc)+' / 다음 뮤뮤로 진행')
        if stop.is_set():break
        schedules[job['id']].complete(rooms,results,retry,clock())
        unresolved=any(results.get(r) not in TERMINAL_RESULTS for r in rooms)
        event('fleet_status',(job['id'],{'status':'확인 필요' if unresolved else '확인 완료',
              'checked_at':time.strftime('%H:%M:%S'),'next_at':schedules[job['id']].next()[0] if repeat else None}))
        if not repeat:unfinished.remove(job['id'])
