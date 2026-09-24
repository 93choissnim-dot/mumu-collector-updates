"""Local-only, bounded diagnostic archive; no upload or credentials."""
import json
import platform
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from version import VERSION


def export_diagnostics(data, target):
    data, target = Path(data), Path(target)
    allowed = {"background_run.log", "background_run.log.1", "background_error.log",
               "launcher.log", "setup.log", "update.log", "update.log.1", "update_result.json", "collection_history.json",
               "update_failure_first.json", "update_failure_latest.json", "update_policy_block.json",
               "last_mumu_discovery.json", "daily_tasks.json", "daily_manual.json", "action_state.json"}
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
    temp = target.with_name(target.name + ".tmp")
    try:
        with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as archive:
            snapshots=[]
            for path in list(data.glob('last_*_error.json'))+list(data.glob('first_*_error.json')):
                if path.name not in allowed or path.is_symlink() or path.stat().st_size>2_000_000:continue
                try:
                    meta=json.loads(path.read_text(encoding='utf-8'))
                    snapshots.append({'file':path.name,**{k:meta.get(k) for k in ('version','created_at','run_id','task','step')}})
                except (OSError,ValueError):continue
            archive.writestr("diagnostics.json", json.dumps({"version": VERSION,
                "created_at": datetime.now().astimezone().isoformat(), "platform": platform.platform(),
                "python": platform.python_version(), "snapshots":snapshots,
                "contents": "최초 보존/최근 실패 화면과 실행 번호, 세부 완료 기록, 업데이트 오류 및 복구 기록"},
                ensure_ascii=False, indent=2))
            for name in sorted(allowed):
                path = data / name
                if not path.is_file() or path.is_symlink():
                    continue
                limit = 12_000_000 if name.endswith((".png",".zip")) else 2_000_000
                with path.open("rb") as stream:
                    if name.endswith((".log", ".log.1")):
                        stream.seek(max(0, path.stat().st_size - limit))
                    elif path.stat().st_size > limit:
                        continue
                    archive.writestr(name, stream.read(limit))
            for path in transactions:
                try:
                    with path.open('rb') as stream:
                        size=path.stat().st_size
                        if path.suffix=='.log':stream.seek(max(0,size-200_000))
                        elif size>200_000:continue
                        archive.writestr(path.relative_to(data).as_posix(),stream.read(200_000))
                except OSError:continue
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)


def append_log(path, text):
    path = Path(path)
    if path.exists() and path.stat().st_size >= 2_000_000:
        path.replace(path.with_name(path.name + ".1"))
    with path.open("a", encoding="utf-8") as stream:
        stream.write(text)


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

def save_execution_trace(data,ident,trace,ledger=None):
    import re
    if not re.fullmatch('[0-9a-f]{24}',ident):raise ValueError('Invalid instance identity')
    report=trace.snapshot();report.update(version=VERSION,daily_state=ledger or {})
    path=Path(data)/('last_'+ident+'_run.json');temp=path.with_suffix('.tmp')
    try:
        temp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)
    finally:temp.unlink(missing_ok=True)


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
