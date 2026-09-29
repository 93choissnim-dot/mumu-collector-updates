"""Local-only, bounded diagnostic archive; no upload or credentials."""
import json
import hashlib
import platform
import shutil
import zipfile
import zlib
from datetime import datetime
from pathlib import Path
from version import VERSION
from diagnostic_retention import maintain_evidence, evidence_locked


def _pending_requests(data):
    """Index unresolved ledger slots without treating old requests as current."""
    from diagnostic_retention import _read
    pending={}
    def add(scope,task,step,request):
        request_id=request.get('id') if isinstance(request,dict) else None
        if not isinstance(request_id,str) or not request_id:request_id=None
        pending.setdefault((scope,task,step),set()).add(request_id)
    for name in ('action_state.json','daily_tasks.json','daily_manual.json'):
        try:root=_read(data/name)
        except (OSError,ValueError,TypeError):continue
        for scope,account in root.items():
            if not isinstance(account,dict):continue
            if name=='action_state.json':
                for task,entry in account.items():
                    slots=entry.get('pending',{}) if isinstance(entry,dict) else {}
                    if isinstance(slots,dict):
                        for step,request in slots.items():add(scope,task,step,request)
            else:
                for day in account.values():
                    if not isinstance(day,dict):continue
                    for task,entry in day.items():
                        steps=entry.get('_steps',{}) if isinstance(entry,dict) else {}
                        if not isinstance(steps,dict):continue
                        for step,detail in steps.items():
                            if isinstance(detail,dict) and (detail.get('pending') or detail.get('status')=='uncertain'):
                                add(scope,task,step,detail.get('input_request'))
    return pending


def _current_input(path,pending):
    """Require exact request linkage when the current ledger knows its ID."""
    try:
        if path.is_symlink() or path.stat().st_size>12_000_000:return False
        with zipfile.ZipFile(path) as archive:
            info=archive.getinfo('evidence.json')
            if info.file_size>2_000_000:return False
            meta=json.loads(archive.read(info))
        if not isinstance(meta,dict):return False
        scope,task,step,phase=(meta.get(key) for key in ('account_scope','task','step','phase'))
        if not all(isinstance(value,str) for value in (scope,task,step,phase)):return False
        if path.name!=f'last_{scope}_{task}_{step}_{phase}_input.zip':return False
        ids=pending.get((scope,task,step))
        detail=meta.get('detail',{})
        if not ids or not isinstance(detail,dict):return False
        if phase=='requested':
            slots=detail.get('pending')
            request=slots.get(step) if isinstance(slots,dict) else detail.get('input_request')
        else:request=detail.get('last_input')
        request_id=request.get('id') if isinstance(request,dict) else None
        # Legacy unknown-origin requests get only scope/task/step attribution.
        # A known but different ID must never acquire current-request priority.
        return ((isinstance(request_id,str) and request_id in ids) or
                (ids=={None} and phase=='requested'))
    except (OSError,ValueError,TypeError,KeyError,RuntimeError,EOFError,zipfile.BadZipFile,zlib.error):return False


@evidence_locked
def export_diagnostics(data, target):
    data, target = Path(data), Path(target)
    allowed = {"background_run.log", "background_run.log.1", "background_error.log",
               "launcher.log", "setup.log", "update.log", "update.log.1", "update_result.json", "collection_history.json",
               "update_failure_first.json", "update_failure_latest.json", "update_policy_block.json",
               "last_mumu_discovery.json", "run_progress.json", "daily_tasks.json", "daily_manual.json", "action_state.json"}
    allowed.update("last_" + prefix + suffix
                   for prefix in ("adb_check", "collection_error", "farm_check", "wood_check", "mine_check")
                   for suffix in (".png", ".json"))
    import re
    from task_catalog import TASK_LABELS
    task_pattern = "|".join(re.escape(task) for task in TASK_LABELS)
    pattern = rf"last_[0-9a-f]{{24}}(?:_(?:{task_pattern}))?_error\.(?:png|json)"
    allowed.update(p.name for p in data.glob("last_*_error.*") if re.fullmatch(pattern, p.name))
    allowed.update(p.name for p in data.glob('last_*') if re.fullmatch(
        rf'last_[0-9a-f]{{24}}(?:(?:_(?:{task_pattern})_[a-z]+_evidence\.zip)|(?:_run\.json))',p.name))
    allowed.update(p.name for p in data.glob('first_*') if re.fullmatch(
        rf'first_[0-9a-f]{{24}}_(?:{task_pattern})(?:_error\.(?:png|json)|_[a-z]{{1,32}}_initial\.zip)',p.name))
    from daily_state import DAILY_STEPS
    for task,steps in dict(DAILY_STEPS,training=('claim',)).items():
        step_pattern='|'.join(map(re.escape,steps))
        allowed.update(p.name for p in data.glob('last_*_input.zip') if re.fullmatch(
            rf'last_[0-9a-f]{{24}}_{task}_(?:{step_pattern})_(?:requested|resolved|completed)_input\.zip',p.name))
    # Transaction paths are text-only and bounded; never export downloaded binaries.
    transaction_names=('exe-job.json','job.json','health.json','health.progress.json','health.threads.log')
    transactions=[]
    updates=data/'updates'
    if not updates.is_symlink():
        jobs=[]
        for work in updates.glob('release-*'):
            if work.is_symlink() or not work.is_dir():continue
            try:jobs.append((work.stat().st_mtime,work))
            except OSError:continue
        for _,work in sorted(jobs,reverse=True)[:8]:
            for name in transaction_names:
                path=work/name
                if path.is_file() and not path.is_symlink():transactions.append(path)
    # Reserve metadata and ZIP headers inside the 32 MiB budget. Stored members
    # have exact sizes; PNG/JPEG and nested evidence ZIPs are already compressed.
    budget=32*1024*1024
    reserve=1024*1024
    critical={'action_state.json','daily_tasks.json','daily_manual.json','run_progress.json'}
    try:lifecycle=maintain_evidence(data)
    except Exception as exc:lifecycle={'files':{},'errors':[{'reason':type(exc).__name__}]}
    entries=[];snapshots=[]
    candidates=[]
    pending=_pending_requests(data)
    for name in allowed:
        path=data/name
        if not path.exists() and not path.is_symlink():continue
        try:stamp=path.stat().st_mtime
        except OSError:stamp=0
        current_input=name.endswith('_input.zip') and _current_input(path,pending)
        latest_failure=name.startswith('last_') and name.endswith(('_error.json','_error.png','_evidence.zip'))
        # Keep current proof and recent failure groups ahead of historical input
        # screenshots. A resolved ZIP for another request is not current proof.
        priority=(0 if name in critical else 1 if current_input else 2 if latest_failure else
                  3 if name.endswith('.json') else 4 if name.startswith('last_') and not name.endswith('_input.zip') else 5)
        if latest_failure and path.suffix in {'.json','.png'}:
            try:stamp=max(stamp,path.with_suffix('.json' if path.suffix=='.png' else '.png').stat().st_mtime)
            except OSError:pass
        candidates.append((priority,-stamp,name,path,None))
    from run_archive import diagnostic_summaries
    for name,raw in diagnostic_summaries(data):candidates.append((3,0,name,None,raw))
    for path in transactions:candidates.append((4,0,path.relative_to(data).as_posix(),path,None))
    seen={};used=22;counts={}
    temp=target.with_name(target.name+'.tmp')
    if temp.is_symlink():raise ValueError('Diagnostic target must be a local file')
    try:
        with zipfile.ZipFile(temp,'w',zipfile.ZIP_STORED) as archive:
            for _,_,name,path,raw in sorted(candidates):
                entry={'file':name,'status':'omitted'}
                state=lifecycle['files'].get(name,{})
                try:
                    if state.get('status') in {'resolved','deleted'}:
                        entry.update(state);entries.append(entry);continue
                    if path is not None:
                        if path.is_symlink() or not path.is_file():
                            entry['reason']='unsafe_file';entries.append(entry);continue
                        size=path.stat().st_size
                        limit=budget-reserve if name in critical else 12_000_000 if name.endswith(('.png','.zip')) else 2_000_000
                        if name.startswith('updates/'):limit=200_000
                        log=name.endswith(('.log','.log.1'))
                        if size>limit and not log:
                            if name in critical:raise ValueError('Current ledger exceeds diagnostic budget: '+name)
                            entry.update(reason='per_file_limit',bytes=size);entries.append(entry);continue
                        with path.open('rb') as stream:
                            if log and size>limit:stream.seek(size-limit)
                            raw=stream.read(limit+1)
                        if len(raw)>limit:
                            entry['reason']='file_changed';entries.append(entry);continue
                        if log and size>limit:entry.update(reason='log_tail',original_bytes=size)
                    digest=hashlib.sha256(raw).hexdigest()
                    # Identical ledgers still have distinct meaning. Preserve names.
                    if name not in critical and name.endswith(('.png','.zip')) and digest in seen:
                        entry.update(reason='duplicate',duplicate_of=seen[digest]);entries.append(entry);continue
                    cost=len(raw)+76+2*len(name.encode('utf-8'))
                    if used+cost>budget-reserve:
                        if name in critical:raise ValueError('Current ledgers exceed diagnostic budget')
                        entry.update(reason='total_budget',bytes=len(raw));entries.append(entry);continue
                    archive.writestr(name,raw);used+=cost
                    if name.endswith(('.png','.zip')):seen[digest]=name
                    entry.update(status='retained',bytes=len(raw))
                    if name.endswith('_error.json'):
                        try:
                            meta=json.loads(raw)
                            if isinstance(meta,dict):snapshots.append({'file':name,**{k:meta.get(k) for k in ('version','created_at','run_id','task','step','account_scope')}})
                        except (ValueError,TypeError):pass
                except OSError as exc:entry['reason']=type(exc).__name__
                entries.append(entry)
            for entry in entries:
                key=entry['status']+':'+entry.get('reason','included');counts[key]=counts.get(key,0)+1
            manifest={'version':VERSION,'created_at':datetime.now().astimezone().isoformat(),
                'platform':platform.platform(),'python':platform.python_version(),
                'budget_bytes':budget,'entries':entries,'entry_counts':counts,
                'snapshots':snapshots,'maintenance_errors':lifecycle['errors'],
                'contents':'현재 상태와 최근 미해결 증거 우선 / 해결된 증거 제외 / 생략 이유는 entries 확인'}
            def encode():return json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf-8')
            encoded=encode()
            # Extremely many allowed filenames must not defeat the total cap.
            # Report the exact number lacking individual detail, plus full counts.
            omitted=0
            while len(encoded)>reserve-4096 and manifest['entries']:
                manifest['entries']=manifest['entries'][:len(manifest['entries'])//2]
                omitted=len(entries)-len(manifest['entries'])
                manifest['entry_details_omitted']=omitted
                manifest['snapshots']=[];manifest['maintenance_errors']=lifecycle['errors'][:100]
                encoded=encode()
            if used+len(encoded)+108>budget:raise ValueError('Diagnostic metadata exceeds budget')
            archive.writestr('diagnostics.json',encoded)
        if temp.stat().st_size>budget:raise ValueError('Diagnostic archive exceeds budget')
        temp.replace(target)
    finally:temp.unlink(missing_ok=True)


def append_log(path, text):
    path = Path(path)
    if path.exists() and path.stat().st_size >= 2_000_000:
        path.replace(path.with_name(path.name + ".1"))
    with path.open("a", encoding="utf-8") as stream:
        stream.write(text)


@evidence_locked
def save_collection_failure(data, ident, image, screen, reason, task=None, *, trace=None, ledger=None):
    """Keep the latest image and one bounded snapshot per failed task/instance."""
    import re
    import cv2
    from task_catalog import TASK_LABELS
    if not re.fullmatch(r"[0-9a-f]{24}", ident):
        raise ValueError("뮤뮤 식별 정보가 올바르지 않습니다.")
    data = Path(data)
    ok, encoded = cv2.imencode('.png', image)
    if not ok:
        raise OSError("진단 캡처를 PNG로 저장하지 못했습니다.")
    stem = "last_"+ident
    stems = [stem+"_error"]
    step=(trace.step or 'task') if trace else None
    repeated=bool(trace and (task,step) in trace.failure_steps)
    if task in TASK_LABELS and not repeated:
        stems.append(stem+"_"+task+"_error")
    metadata = json.dumps({"version": VERSION,"run_id":trace.run_id if trace else None,"step":step,
        "created_at": datetime.now().astimezone().isoformat(), "task": task,
        "instance_id":ident,"account_scope":getattr(trace,"account_scope",None),
        "image_sha256":hashlib.sha256(encoded.tobytes()).hexdigest(),
        "reason": str(reason), "state": getattr(screen, "state", "unknown"),
        "recognition": getattr(screen, "diagnostics", {})}, ensure_ascii=False, indent=2)
    # A fixed first capture per instance/task survives later runs and recovery.
    if task in TASK_LABELS:
        first='first_'+ident+'_'+task+'_error'
        if not (data/(first+'.json')).exists():stems.append(first)
    for name in stems:
        encoded.tofile(data/(name+".png"))
        (data/(name+".json")).write_text(metadata, encoding="utf-8")
    if trace and not repeated and task in TASK_LABELS and isinstance(step,str) and re.fullmatch('[a-z]+',step):
        evidence=data/(stem+'_'+task+'_'+step+'_evidence.zip')
        temp=evidence.with_suffix('.tmp')
        try:
            with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('failure.json',metadata)
                archive.writestr('failure.png',encoded.tobytes())
                report=trace.snapshot();frames=[]
                for n,(details,raw) in enumerate(trace.frames):
                    filename=f'before_{n+1}.jpg';archive.writestr(filename,raw)
                    frames.append(dict(details,file=filename))
                report['frames']=frames
                archive.writestr('trace.json',json.dumps(report,ensure_ascii=False,indent=2))
                archive.writestr('daily_state.json',json.dumps(ledger or {},ensure_ascii=False,indent=2))
            temp.replace(evidence)
            first=data/('first_'+ident+'_'+task+'_'+step+'_initial.zip')
            # A finite retention budget also guards future dynamically named steps.
            if (len(step)<=32 and not first.exists()
                and len(list(data.glob('first_'+ident+'_'+task+'_*_initial.zip')))<16):
                shutil.copy2(evidence,first)
            trace.failure_steps.add((task,step))
        finally:temp.unlink(missing_ok=True)

@evidence_locked
def save_execution_trace(data,ident,trace,ledger=None):
    import re
    if not re.fullmatch('[0-9a-f]{24}',ident):raise ValueError('Invalid instance identity')
    report=trace.snapshot();report.update(version=VERSION,daily_state=ledger or {})
    path=Path(data)/('last_'+ident+'_run.json');temp=path.with_suffix('.tmp')
    try:
        temp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)
    finally:temp.unlink(missing_ok=True)
    # Optional date history must never turn a completed automation into failure.
    try:
        from run_archive import append_run
        append_run(data,ident,report)
    except Exception:
        pass

    try:maintain_evidence(data,success=(ident,report))
    except Exception:pass


@evidence_locked
def save_input_evidence(data,ident,scope,task,step,phase,detail,image,screen,*,run_id=None):
    """Three bounded local archives per account/step, linked by request id.

    A requested frame proves only the pre-input screen. Resolution metadata
    distinguishes game confirmation from permission to repeat an uncertain input.
    """
    import re
    import cv2
    import numpy as np
    from daily_state import DAILY_STEPS
    if (not re.fullmatch('[0-9a-f]{24}',str(ident)) or
        not re.fullmatch('[0-9a-f]{24}',str(scope)) or
        step not in dict(DAILY_STEPS,training=('claim',)).get(task,()) or phase not in {'requested','resolved','completed'}):
        raise ValueError('입력 증거 식별 정보가 올바르지 않습니다.')
    metadata={'version':VERSION,'created_at':datetime.now().astimezone().isoformat(),
              'instance_id':ident,'account_scope':scope,'task':task,'step':step,
              'phase':phase,'run_id':run_id,'state':getattr(screen,'state','unknown'),
              'detail':detail,'screen_available':False}
    raw=None
    if isinstance(image,np.ndarray) and image.size:
        ok,encoded=cv2.imencode('.jpg',cv2.resize(image,(960,540)),[cv2.IMWRITE_JPEG_QUALITY,80])
        if not ok:raise OSError('입력 확인 화면 저장 실패')
        raw=encoded.tobytes();metadata['screen_available']=True
    data=Path(data);data.mkdir(parents=True,exist_ok=True)
    target=data/('last_'+scope+'_'+task+'_'+step+'_'+phase+'_input.zip')
    temp=target.with_suffix('.tmp')
    try:
        with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('evidence.json',json.dumps(metadata,ensure_ascii=False,indent=2))
            if raw is not None:archive.writestr('screen.jpg',raw)
        temp.replace(target)
    finally:temp.unlink(missing_ok=True)
    return target


@evidence_locked
def failure_snapshot(data,ident,task,checked_at=None,run_id=None):
    """Return only the current task's locally owned diagnostic capture."""
    import re
    from task_catalog import TASK_LABELS
    if not re.fullmatch(r'[0-9a-f]{24}',str(ident)) or task not in TASK_LABELS:return None
    stem=Path(data)/('last_'+ident+'_'+task+'_error')
    meta=stem.with_suffix('.json');image=stem.with_suffix('.png')
    try:
        if meta.is_symlink() or image.is_symlink() or not image.is_file():return None
        value=json.loads(meta.read_text(encoding='utf-8'))
        if value.get('task')!=task:return None
        created=datetime.fromisoformat(value['created_at'])
        if run_id:
            if value.get('run_id')!=run_id:return None
        elif checked_at and created<datetime.fromisoformat(checked_at):return None
        return image,value
    except (OSError,ValueError,TypeError,KeyError):return None


def bind_input_evidence(collector,data,ident,scope,log):
    """Connect durable requests to bounded local screenshots, including training."""
    collector.trace.account_scope=scope
    def save(phase,task,step,detail):
        try:
            save_input_evidence(data,ident,scope,task,step,phase,detail,
                collector.last_image,collector.last_screen,run_id=collector.trace.run_id)
        except Exception as exc:log('입력 확인 증거 저장 실패: '+str(exc))
    if collector.daily_ledger is not None:
        collector.daily_ledger.on_input_evidence=save
    def training(phase,task,step,detail):
        if task=='training':save(phase,task,step,detail)
    collector.action_state.on_input_evidence=training
