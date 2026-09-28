"""Advisory evidence lifecycle. Never writes input or completion ledgers."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import threading
import zipfile

KST=timezone(timedelta(hours=9))
_LOCK=threading.RLock()
MAX_METADATA=2_000_000
MAX_EVIDENCE=12_000_000
_ID=re.compile(r'[0-9a-f]{24}')


def _read(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size>MAX_METADATA:
        raise ValueError('unreadable metadata')
    value=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value,dict):raise ValueError('metadata is not an object')
    return value


def _time(value):
    result=datetime.fromisoformat(value)
    if result.tzinfo is None:raise ValueError('ambiguous timestamp')
    return result.astimezone(KST)


def _digest(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size>MAX_EVIDENCE:
        raise ValueError('unsafe or oversized evidence')
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for raw in iter(lambda:stream.read(128*1024),b''):digest.update(raw)
    return digest.hexdigest()


def _guarded(data,scope,ident,task):
    def pending(value):
        if not isinstance(value,dict):return True
        if value.get('pending') or value.get('status')=='uncertain':return True
        steps=value.get('_steps',{})
        return not isinstance(steps,dict) or any(pending(v) for v in steps.values())
    for name in ('action_state.json','daily_tasks.json','daily_manual.json'):
        path=data/name
        if not path.exists() and not path.is_symlink():continue
        try:
            root=_read(path)
            for key in {scope,ident}:
                account=root.get(key,{})
                if not isinstance(account,dict):return True
                if name=='action_state.json':
                    entry=account.get(task,{})
                    if (not isinstance(entry,dict) or not isinstance(entry.get('pending',{}),dict) or
                        any(not isinstance(v,dict) for v in entry.get('pending',{}).values()) or pending(entry)):return True
                else:
                    for day in account.values():
                        if not isinstance(day,dict) or pending(day.get(task,{})):return True
        except (OSError,ValueError,TypeError):return True
    return False


def _matches(meta,ident,report,now):
    try:
        scope=meta.get('account_scope');task=meta.get('task')
        from task_catalog import TASK_LABELS
        if not isinstance(task,str) or task not in TASK_LABELS:return False
        if not isinstance(scope,str) or not _ID.fullmatch(scope):return False
        if meta.get('instance_id')!=ident or report.get('account_scope')!=scope:return False
        if any(not isinstance(value,str) or not value or len(value)>128 for value in
               (meta.get('run_id'),report.get('run_id'))):return False
        if meta['run_id']==report['run_id']:return False
        if not _time(meta['created_at']) < _time(report['started_at']) <= _time(report['finished_at']) <= now:return False
        if not isinstance(report.get('failure_steps'),list) or any(not isinstance(v,dict) or v.get('task')==task for v in report['failure_steps']):return False
        outcomes=report.get('task_outcomes',[])
        if not isinstance(outcomes,list) or any(not isinstance(v,dict) for v in outcomes):return False
        matched=[v for v in outcomes if v.get('task')==task]
        return len(matched)==1 and matched[0].get('result')=='collected'
    except (ValueError,TypeError,KeyError):return False


def maintain_evidence(data,*,success=None,now=None):
    """Classify evidence, recording proven resolutions and expiring only those.

    The receipt binds a verified later run to exact file hashes. Unknown identity,
    changed bytes, malformed metadata and unresolved input guards fail closed.
    """
    data=Path(data);now=(now or datetime.now(KST)).astimezone(KST)
    files={};errors=[]
    with _LOCK:
        state=data/'diagnostic_retention.json'
        state_valid=True;old={}
        try:
            if state.exists() or state.is_symlink():
                stored=_read(state)
                if stored.get('schema')!=1 or not isinstance(stored.get('receipts'),dict):
                    raise ValueError('invalid retention state')
                old=stored['receipts']
                if any(not isinstance(record,dict) or not isinstance(record.get('hashes'),dict) or
                       not isinstance(record.get('proof'),dict) for record in old.values()):
                    raise ValueError('invalid receipt record')
        except (OSError,ValueError,TypeError) as exc:
            state_valid=False;errors.append({'file':state.name,'reason':type(exc).__name__})
        # Retain invalidations through temporary guard/read failures.
        receipts={name:value for name,value in old.items() if isinstance(name,str) and
                  Path(name).name==name and (data/name).exists() and not (data/name).is_symlink()}
        from task_catalog import TASK_LABELS
        tasks='|'.join(map(re.escape,TASK_LABELS))
        pattern=re.compile(rf'(?:last|first)_([0-9a-f]{{24}})(?:_({tasks}))?(?:_error\.json|_[a-z]{{1,32}}_(?:evidence|initial)\.zip)')
        reports=[]
        if success is not None:reports.append(success)
        for path in data.glob('last_*_run.json'):
            match=re.fullmatch(r'last_([0-9a-f]{24})_run\.json',path.name)
            if match:
                try:reports.append((match[1],_read(path)))
                except (OSError,ValueError,TypeError):pass
        for path in sorted(data.iterdir()):
            match=pattern.fullmatch(path.name)
            if not match:continue
            group=[path]
            if path.suffix=='.json':group.append(path.with_suffix('.png'))
            for member in group:
                if member.exists() or member.is_symlink():files[member.name]={'status':'retained','reason':'unverified_resolution'}
            if not state_valid:continue
            try:
                if path.is_symlink():raise ValueError('symlink')
                initial_digest=_digest(path)
                if path.suffix=='.json':
                    meta=_read(path);image_digest=_digest(path.with_suffix('.png'))
                else:
                    if path.stat().st_size>MAX_EVIDENCE:raise ValueError('oversized evidence')
                    with zipfile.ZipFile(path) as archive:
                        item=archive.getinfo('failure.json')
                        if item.file_size>MAX_METADATA:raise ValueError('oversized metadata')
                        meta=json.loads(archive.read(item))
                        picture=archive.getinfo('failure.png')
                        if picture.file_size>MAX_EVIDENCE:raise ValueError('oversized failure image')
                        image_digest=hashlib.sha256(archive.read(picture)).hexdigest()
                if not isinstance(meta,dict):raise ValueError('invalid metadata')
                # Only new captures bind identity/time metadata to the exact image.
                # This remains safe even if the receipt file was removed or lost.
                if meta.get('image_sha256')!=image_digest:continue
                if meta.get('instance_id')!=match[1] or (match[2] and meta.get('task')!=match[2]):continue
                if _guarded(data,meta.get('account_scope'),match[1],meta.get('task')):continue
                hashes={member.name:_digest(member) for member in group if member.exists() or member.is_symlink()}
                if hashes.get(path.name)!=initial_digest:raise ValueError('metadata changed')
                if path.suffix=='.json' and hashes.get(path.with_suffix('.png').name)!=image_digest:
                    raise ValueError('failure image changed')
                receipt=old.get(path.name,{})
                receipt=dict(receipt) if isinstance(receipt,dict) else {}
                proof=receipt.get('proof',{})
                if receipt and (receipt.get('invalidated') or receipt.get('hashes')!=hashes):
                    # A replacement frame is not the frame described by old metadata.
                    # Keep the invalidation across exports so old runs cannot re-prove it.
                    fresh_metadata=(isinstance(receipt.get('hashes'),dict) and
                        receipt['hashes'].get(path.name)!=hashes.get(path.name) and
                        isinstance(proof,dict) and _time(meta['created_at'])>_time(proof['finished_at']))
                    if not fresh_metadata:
                        receipt['invalidated']=True;receipts[path.name]=receipt;continue
                    receipt={};proof={}
                if (receipt.get('hashes')!=hashes or not isinstance(proof,dict) or not _matches(meta,match[1],proof,now)):
                    receipt={}
                    for ident,report in reports:
                        if _matches(meta,ident,report,now):
                            proof={key:report[key] for key in ('account_scope','run_id','started_at','finished_at','failure_steps')}
                            proof['task_outcomes']=[dict(task=meta['task'],result='collected')]
                            receipt={'hashes':hashes,'proof':proof};break
                if not receipt:continue
                resolved=_time(receipt['proof']['finished_at'])
                expired=(now.date()-resolved.date()).days>=5
                if expired and any(_digest(member)!=hashes[member.name] for member in group if member.name in hashes):
                    raise ValueError('evidence changed')
                for member in group:
                    if member.name not in hashes:continue
                    if expired:
                        # Recheck immediately before unlinking; never follow a link.
                        if _digest(member)!=hashes[member.name]:raise ValueError('evidence changed')
                        member.unlink()
                    files[member.name]={'status':'deleted' if expired else 'resolved','reason':'later_scoped_success','resolved_at':resolved.isoformat()}
                if not expired:receipts[path.name]=receipt
                else:receipts.pop(path.name,None)
            except (OSError,ValueError,TypeError,KeyError,zipfile.BadZipFile) as exc:
                errors.append({'file':path.name,'reason':type(exc).__name__})
        if receipts!=old:
            temp=state.with_suffix('.tmp')
            try:
                if state.is_symlink() or temp.is_symlink():raise ValueError('unsafe retention state')
                raw=json.dumps({'schema':1,'receipts':receipts},ensure_ascii=False)
                if len(raw.encode('utf-8'))>MAX_METADATA:raise ValueError('retention state full')
                temp.write_text(raw,encoding='utf-8');temp.replace(state)
            except (OSError,ValueError) as exc:errors.append({'file':state.name,'reason':type(exc).__name__})
            finally:
                if not temp.is_symlink():temp.unlink(missing_ok=True)
    return {'files':files,'errors':errors}
