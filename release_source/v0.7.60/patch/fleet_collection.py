"""Collection worker; immutable job settings, no Tk access from worker threads."""
import copy
import time
from tkinter import messagebox
from adb_device import Adb, AdbDevice, inspect_device
from collector import Halt
from diagnostics import save_collection_failure,save_execution_trace,bind_input_evidence
from extra_collector import ExtraCollector
from task_catalog import TASK_LABELS,REGULAR_LABELS
from vision import Vision
from mumu_names import CatalogLookup
from run_support import cycle_with_recovery
from fleet_runner import run_fleet
from daily_state import ManualQuestLedger,DAILY_TASKS,DAILY_ALREADY
from history import RESULTS
from daily_state import korea_day
from session_workflow import task_scope,continuation

class FleetCollection:
    def launch(self,mode,targets=None):
        if mode=='inspect':return self.launch_single(mode)
        if self.busy():return
        if mode=='verify_daily' and (self.update_pending.is_set() or getattr(self,'update_applying',False)):return
        try:
            self.capture_profile()
            jobs=[]
            scope_mode='daily' if mode=='daily' else getattr(self,'config',{}).get('run_scope','regular')
            for ident,p in self.players.items():
                if mode in {'retry','verify_daily','resume'}:
                    if not targets or ident not in targets:continue
                elif not p.get('enabled'):continue
                job=copy.deepcopy(p);job['id']=ident;job['restore_sleep']=True
                job['rooms']=task_scope(p,scope_mode,repeat=mode=='repeat')
                if mode=='retry':
                    from ui_state import retry_tasks
                    entries={r:self.history.get(ident,r) or self.history.get(p.get('serial',''),r) for r in TASK_LABELS}
                    job['rooms']=retry_tasks(p,entries,targets[ident])
                    if not job['rooms']:continue
                if mode=='resume':
                    from ui_state import selected_tasks
                    allowed=set(task_scope(p,'all'))
                    job['rooms']=[r for r in targets[ident] if r in allowed]
                    if not job['rooms']:continue
                if mode=='verify_daily':
                    if 'daily_dungeons' not in targets[ident]:continue
                    job['rooms']=['daily_dungeons']
                if not job['rooms']:continue
                job['minutes']=60 if mode in {'daily','verify_daily','resume'} else float(p['minutes'])
                if not job['rooms'] or not 1<=job['minutes']<=1440:raise Halt('시설과 수령 간격을 확인하세요.')
                jobs.append(job)
            if not jobs:raise Halt('재시도할 실패 작업이 없습니다.' if mode=='retry' else '작업 설정에서 실행할 뮤뮤를 선택해 주세요.')
            self.save()
        except Exception as exc:
            messagebox.showerror('설정 확인',str(exc));return
        from action_state import account_scope
        session_day=korea_day()
        self.run_mode=mode;self.session_count=0;self.count_label.configure(text='0건')
        for job in jobs:
            self.fleet_states[job['id']]={'status':'대기','rooms':job['rooms'],'results':{},'run_entries':{},'session_day':session_day,'scope':account_scope(job['id'],job.get('daily_profile','')),'next_at':None,'phase':''}
        executable=self.adb_path.get()
        lookup=CatalogLookup();shared_vision=None
        capture_modes={r.get('instance_id'):r.get('capture_mode') for r in self.device_reports.values()}
        emit=lambda kind,value:self.events.put((kind,value))
        journal=None;run_results={job['id']:{'rooms':list(job['rooms']),'results':{}} for job in jobs}
        def execute(job,rooms):
            nonlocal shared_vision
            from app import DATA
            from action_state import ActionState,account_scope
            ident=job['id'];scope=account_scope(ident,job.get('daily_profile',''));serial=None;collector=None;device=None;results={};ledger=None
            log=lambda text:self.log(job['name']+' / '+text)
            if mode=='resume' and korea_day()!=session_day:raise Halt('날짜가 바뀌어 이어하기를 중지했습니다. 새 실행을 시작해 주세요.')
            def recorded(room,result,reason=None):
                results[room]=result
                run_results[ident]['results'][room]=result
                from run_review import progress_snapshot
                progress=progress_snapshot(collector,room) if collector is not None else {}
                if not reason and collector is not None and room in DAILY_TASKS:
                    reason=getattr(collector,'daily_summary','')
                if not reason and collector is not None and room!='training' and result=='deferred' and collector.action_state.get(room).get('pending'):
                    reason='이전 입력 결과 미확인 / 중복 입력 보류. 완료 상태를 확인하기 전에는 같은 작업을 다시 누르지 않습니다.'
                if not reason:
                    reason={'skipped':'현재 화면에서 수령 조건 또는 받을 보상 없음 확인',
                            'unavailable':'이벤트 화면에서 대상 이벤트 없음 확인',
                            'no_entries':'던전별 입장 횟수 소진 확인',
                            'already_complete':'완료 또는 유료 제외 기록 확인',
                            'already_claimed':'이전 완료 기록 확인'}.get(result,'')
                from datetime import datetime,timezone
                entry={'result':result,'reason':reason or '', 'progress':progress,'checked_at':datetime.now(timezone.utc).isoformat()}
                if journal is not None:journal.result(scope,room,result,entry=entry)
                emit('fleet_entry',(ident,room,entry))
                if collector is not None:collector.trace.event('task_outcome',task=room,result=result,reason=reason or '',progress=progress)
                try:self.history.record(ident,room,result,reason=reason,run_id=collector.trace.run_id if collector else None,progress=progress)
                except OSError as exc:log('이력 저장 실패: '+str(exc))
                emit('fleet_result',(ident,room,result))
            def capture(reason,task=None):
                if task:
                    try:self.history.issue(ident,task,reason)
                    except OSError as exc:log('실패 원인 저장 실패: '+str(exc))
                if collector is None or collector.last_image is None or self.stop.is_set():return
                try:save_collection_failure(DATA,ident,collector.last_image,collector.last_screen,reason,task,
                    trace=collector.trace,ledger=ledger.snapshot(scope,getattr(collector,'daily_day',None)) if ledger else None)
                except Exception as exc:log('진단 저장 실패: '+str(exc))
                log(reason)
            try:
                action_state=ActionState(DATA/'action_state.json',scope)
                if mode=='retry':
                    for room in rooms:action_state.reset(room)
                ledger=ManualQuestLedger(DATA/'daily_manual.json') if any(t in DAILY_TASKS for t in rooms) else None
                if mode=='retry':
                    from retry_resolution import retry_ledger
                    ledger=retry_ledger(DATA,scope,rooms)
                if mode in {'verify_daily','resume'}:
                    from retry_resolution import _ledger
                    ledger=_ledger(DATA,scope)
                for room in list(rooms):
                    if room not in DAILY_TASKS and action_state.blocked(room):
                        recorded(room,'deferred','같은 오류 반복 / 수동 재시도 전까지 보류')
                        log(TASK_LABELS[room]+': 같은 오류 반복으로 보류')
                rooms=[r for r in rooms if r not in results]
                if not rooms:return results
                emit('fleet_progress',(ident,'실행 전 점검 / 뮤뮤 연결과 대상 확인'))
                catalog=lookup.read(executable,self.stop,log,ident)
                matches=[(s,p) for s,p in catalog.items() if p['instance_id']==ident]
                if len(matches)!=1:raise Halt('이 뮤뮤를 확인하지 못했습니다. 다음 창으로 넘어갑니다.')
                serial,meta=matches[0]
                def verify():
                    if mode=='resume' and korea_day()!=session_day:raise Halt('날짜가 바뀌어 이어하기를 중지했습니다.')
                    current=lookup.read(executable,self.stop,log,ident)
                    if current.get(serial,{}).get('instance_id')!=ident:raise Halt('뮤뮤 식별 정보가 바뀌었습니다. 다음 차례에 다시 연결합니다.')
                adb=Adb(executable,self.stop)
                for attempt in range(3):
                    try:verify();adb.ensure_connected(serial,log);break
                    except Halt:
                        if attempt==2 or self.stop.wait(2):raise
                emit('link_available',serial)
                device=AdbDevice(adb,serial,log=log,capture_mode=capture_modes.get(ident))
                if shared_vision is None:shared_vision=Vision()
                vision=shared_vision
                emit('fleet_progress',(ident,'실행 전 점검 / 게임 앱과 화면 크기 확인'))
                from game_recovery import GameRecovery
                recovery=GameRecovery(device,vision,self.stop,verify,log,lambda text:emit('fleet_progress',(ident,text))) if mode!='verify_daily' else None
                if recovery is not None:recovery.recover()
                device.bind_game(vision)
                log('실행 전 점검 통과 / 게임 앱과 캡처 크기 확인')
                def observed(image,screen):
                    emit('device_checked',(serial,{'instance_id':ident,'window_name':meta['name'],
                        'model':'뮤뮤','package':device.package,'image':image,'state':screen.state,
                        'capture_mode':device.capture_mode,'error':'','package_error':''}))
                def progress(text):
                    emit('fleet_active',(ident,collector.trace.task if collector is not None else None))
                    emit('fleet_progress',(ident,text))
                collector=ExtraCollector(device,vision,self.stop,log,on_frame=observed,
                    on_progress=progress,
                    on_result=recorded,on_issue=lambda room,reason:capture(reason,room))
                if mode=='retry':
                    collector.manual_retry_rooms=set(rooms) & {'farm','wood','mine'}
                    collector.manual_retry_tasks=set(rooms)
                if mode=='verify_daily':
                    collector.daily_verification_only=True
                    collector.manual_retry_tasks={'daily_dungeons'}
                collector.daily_ledger=ledger;collector.daily_ident=scope;collector.action_state=action_state
                bind_input_evidence(collector,DATA,ident,scope,log)
                if mode not in {'verify_daily','resume'} and 'daily_dungeons' in rooms:collector.arm_dungeon_resume()
                if mode not in {'verify_daily','resume'} and 'daily_guild' in rooms:collector.arm_guild_resume()
                def run_cycle(selected):
                    return cycle_with_recovery(collector,selected,True,adb,device,vision,
                        self.stop,log,verify_identity=verify,on_error=lambda exc:capture(str(exc)),
                        on_link=lambda ok:emit('link_available' if ok else 'link_unavailable',serial),game_recovery=recovery)
                results.update(run_cycle(rooms))
                if mode!='verify_daily':
                    from run_review import final_review
                    results.update(final_review(collector,rooms,dict(results),run_cycle,log,self.stop))
                return results
            except Exception as exc:
                if self.stop.is_set():raise
                capture(str(exc));log('확인 필요: '+str(exc))
                for room in rooms:
                    if room not in results:recorded(room,'failed',str(exc))
                return results
            finally:
                if device is not None and device.capture_mode:capture_modes[ident]=device.capture_mode
                if collector is not None:
                    try:save_execution_trace(DATA,ident,collector.trace,
                        ledger.snapshot(scope,getattr(collector,'daily_day',None)) if ledger else None)
                    except (OSError,ValueError) as exc:log('실행 진단 저장 실패: '+str(exc))
        def operation():
            nonlocal journal
            from app import DATA
            from run_journal import RunJournal
            from action_state import account_scope
            if mode!='verify_daily':
                journal=RunJournal(DATA/'run_progress.json')
                if mode=='resume':
                    current_plan=continuation(DATA,{j['id']:j for j in jobs})
                    for job in jobs:
                        scope=account_scope(job['id'],job.get('daily_profile',''))
                        current=set(current_plan['targets'].get(job['id'],[]))
                        job['rooms']=[r for r in job['rooms'] if r in current]
                    jobs[:]=[job for job in jobs if job['rooms']]
                for job in jobs:
                    scope=account_scope(job['id'],job.get('daily_profile',''))
                    if mode=='resume':journal.continue_run(scope,job['rooms'])
                    else:
                        daily=[t for t in job['rooms'] if t in DAILY_TASKS]
                        if daily and mode!='retry':ManualQuestLedger(DATA/'daily_manual.json').begin_run(scope,legacy_path=DATA/'daily_tasks.json',tasks=daily)
                        journal.begin(scope,job['rooms'])
            def execute_tracked(job,rooms):
                if journal is not None and mode=='repeat' and rooms==job['rooms']:
                    journal.begin(account_scope(job['id'],job.get('daily_profile','')),rooms)
                    run_results[job['id']]['results']={}
                return execute(job,rooms)
            try:run_fleet(jobs,mode=='repeat',self.stop,self.update_pending,execute_tracked,emit)
            finally:emit('fleet_summary',run_results)
        self.run_worker(operation,f'{len(jobs)}개 뮤뮤 순차 수령 중',pausable=True)
