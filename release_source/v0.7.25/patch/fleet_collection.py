"""Collection worker; immutable job settings, no Tk access from worker threads."""
import copy
import time
from tkinter import messagebox
from adb_device import Adb, AdbDevice, inspect_device
from collector import Halt
from diagnostics import save_collection_failure,save_execution_trace
from extra_collector import ExtraCollector
from task_catalog import TASK_LABELS
from vision import Vision
from mumu_names import read_catalog
from run_support import cycle_with_recovery
from fleet_runner import run_fleet
from daily_state import DailyLedger,DAILY_TASKS,DAILY_ALREADY
from history import RESULTS

class FleetCollection:
    def launch(self,mode,targets=None):
        if mode=='inspect':return self.launch_single(mode)
        if self.busy():return
        try:
            self.capture_profile()
            jobs=[]
            for ident,p in self.players.items():
                if mode=='retry':
                    if not targets or ident not in targets:continue
                elif not p.get('enabled'):continue
                job=copy.deepcopy(p);job['id']=ident;job['restore_sleep']=True
                job['rooms']=[r for r in TASK_LABELS if p['selected'].get(r,False)]
                if mode=='retry':
                    from ui_state import retry_tasks
                    entries={r:self.history.get(ident,r) or self.history.get(p.get('serial',''),r) for r in TASK_LABELS}
                    job['rooms']=retry_tasks(p,entries,targets[ident])
                    if not job['rooms']:continue
                job['minutes']=float(p['minutes'])
                if not job['rooms'] or not 1<=job['minutes']<=1440:raise Halt('시설과 수령 간격을 확인하세요.')
                jobs.append(job)
            if not jobs:raise Halt('재시도할 실패 작업이 없습니다.' if mode=='retry' else '세팅 설정에서 수령할 창을 체크해 주세요.')
            self.save()
        except Exception as exc:
            messagebox.showerror('설정 확인',str(exc));return
        self.run_mode=mode;self.session_count=0;self.count_label.configure(text='0건')
        for job in jobs:
            self.fleet_states[job['id']]={'status':'대기','rooms':job['rooms'],'results':{},'next_at':None,'phase':''}
        executable=self.adb_path.get()
        emit=lambda kind,value:self.events.put((kind,value))
        def execute(job,rooms):
            from app import DATA
            ident=job['id'];serial=None;collector=None;results={}
            log=lambda text:self.log(job['name']+' / '+text)
            def recorded(room,result,reason=None):
                results[room]=result
                if not reason and collector is not None and room in DAILY_TASKS:
                    reason=getattr(collector,'daily_summary','')
                try:self.history.record(ident,room,result,reason=reason,run_id=collector.trace.run_id if collector else None)
                except OSError as exc:log('이력 저장 실패: '+str(exc))
                emit('fleet_result',(ident,room,result))
            def capture(reason,task=None):
                if task:
                    try:self.history.issue(ident,task,reason)
                    except OSError as exc:log('실패 원인 저장 실패: '+str(exc))
                if collector is None or collector.last_image is None or self.stop.is_set():return
                try:save_collection_failure(DATA,ident,collector.last_image,collector.last_screen,reason,task,
                    trace=collector.trace,ledger=ledger.snapshot(ident,getattr(collector,'daily_day',None)) if ledger else None)
                except Exception as exc:log('진단 저장 실패: '+str(exc))
                log(reason)
            try:
                ledger=DailyLedger(DATA/'daily_tasks.json') if any(r in DAILY_TASKS for r in rooms) else None
                if ledger and mode=='retry':
                    for room in rooms:
                        if room in DAILY_TASKS:ledger.reset_blocked(ident,room)
                for room in list(rooms):
                    if room in DAILY_TASKS and ledger.done(ident,room):
                        recorded(room,DAILY_ALREADY[room])
                        log(TASK_LABELS[room]+': '+RESULTS[DAILY_ALREADY[room]]+' / KST 00:00 이후 다시 실행')
                rooms=[r for r in rooms if r not in results]
                if not rooms:return results
                catalog=read_catalog(executable,self.stop,log,target_id=ident)
                matches=[(s,p) for s,p in catalog.items() if p['instance_id']==ident]
                if len(matches)!=1:raise Halt('이 뮤뮤를 확인하지 못했습니다. 다음 창으로 넘어갑니다.')
                serial,meta=matches[0]
                def verify():
                    current=read_catalog(executable,self.stop,log,target_id=ident)
                    if current.get(serial,{}).get('instance_id')!=ident:raise Halt('뮤뮤 식별 정보가 바뀌었습니다. 다음 차례에 다시 연결합니다.')
                adb=Adb(executable,self.stop)
                for attempt in range(3):
                    try:verify();adb.ensure_connected(serial,log);break
                    except Halt:
                        if attempt==2 or self.stop.wait(2):raise
                emit('link_available',serial)
                device=AdbDevice(adb,serial,log=log);vision=Vision()
                device.bind_game(vision)
                def observed(image,screen):
                    emit('device_checked',(serial,{'instance_id':ident,'window_name':meta['name'],
                        'model':'뮤뮤','package':device.package,'image':image,'state':screen.state,
                        'capture_mode':device.capture_mode,'error':'','package_error':''}))
                collector=ExtraCollector(device,vision,self.stop,log,on_frame=observed,
                    on_progress=lambda text:emit('fleet_progress',(ident,text)),
                    on_result=recorded,on_issue=lambda room,reason:capture(reason,room))
                collector.daily_ledger=ledger;collector.daily_ident=ident
                results.update(cycle_with_recovery(collector,rooms,True,adb,device,vision,
                    self.stop,log,verify_identity=verify,on_error=lambda exc:capture(str(exc)),
                    on_link=lambda ok:emit('link_available' if ok else 'link_unavailable',serial)))
                return results
            except Exception as exc:
                if self.stop.is_set():raise
                capture(str(exc));log('확인 필요: '+str(exc))
                for room in rooms:
                    if room not in results:recorded(room,'failed',str(exc))
                return results
            finally:
                if collector is not None:
                    try:save_execution_trace(DATA,ident,collector.trace,
                        ledger.snapshot(ident,getattr(collector,'daily_day',None)) if ledger else None)
                    except (OSError,ValueError) as exc:log('실행 진단 저장 실패: '+str(exc))
        self.run_worker(lambda:run_fleet(jobs,mode=='repeat',self.stop,self.update_pending,execute,emit),
                        f'{len(jobs)}개 뮤뮤 순차 수령 중',pausable=True)
