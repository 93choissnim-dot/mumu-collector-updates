"""Local-only, bounded diagnostic archive; no upload or credentials."""
import json
import platform
import zipfile
from datetime import datetime
from pathlib import Path
from version import VERSION


def export_diagnostics(data, target):
    data, target = Path(data), Path(target)
    allowed = {"background_run.log", "background_run.log.1", "background_error.log",
               "launcher.log", "setup.log", "update.log", "update_result.json", "collection_history.json",
               "last_mumu_discovery.json"}
    allowed.update("last_" + prefix + suffix
                   for prefix in ("adb_check", "collection_error", "farm_check", "wood_check", "mine_check")
                   for suffix in (".png", ".json"))
    import re
    from task_catalog import TASK_LABELS
    task_pattern = "|".join(re.escape(task) for task in TASK_LABELS)
    pattern = rf"last_[0-9a-f]{{24}}(?:_(?:{task_pattern}))?_error\.(?:png|json)"
    allowed.update(p.name for p in data.glob("last_*_error.*") if re.fullmatch(pattern, p.name))
    temp = target.with_name(target.name + ".tmp")
    try:
        with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("diagnostics.json", json.dumps({"version": VERSION,
                "created_at": datetime.now().astimezone().isoformat(), "platform": platform.platform(),
                "python": platform.python_version(), "contents": "선택된 게임 캡처, 진단 및 최근 실행 기록"},
                ensure_ascii=False, indent=2))
            for name in sorted(allowed):
                path = data / name
                if not path.is_file() or path.is_symlink():
                    continue
                limit = 12_000_000 if name.endswith(".png") else 2_000_000
                with path.open("rb") as stream:
                    if name.endswith((".log", ".log.1")):
                        stream.seek(max(0, path.stat().st_size - limit))
                    elif path.stat().st_size > limit:
                        continue
                    archive.writestr(name, stream.read(limit))
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)


def append_log(path, text):
    path = Path(path)
    if path.exists() and path.stat().st_size >= 2_000_000:
        path.replace(path.with_name(path.name + ".1"))
    with path.open("a", encoding="utf-8") as stream:
        stream.write(text)


def save_collection_failure(data, ident, image, screen, reason, task=None):
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
    if task in TASK_LABELS:
        stems.append(stem+"_"+task+"_error")
    metadata = json.dumps({"version": VERSION,
        "created_at": datetime.now().astimezone().isoformat(), "task": task,
        "reason": str(reason), "state": getattr(screen, "state", "unknown"),
        "recognition": getattr(screen, "diagnostics", {})}, ensure_ascii=False, indent=2)
    for name in stems:
        encoded.tofile(data/(name+".png"))
        (data/(name+".json")).write_text(metadata, encoding="utf-8")


def failure_snapshot(data,ident,task,checked_at=None):
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
        if checked_at and created<datetime.fromisoformat(checked_at):return None
        return image,value
    except (OSError,ValueError,TypeError,KeyError):return None
