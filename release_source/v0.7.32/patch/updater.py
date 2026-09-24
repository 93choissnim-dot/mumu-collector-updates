"""HTTPS update feed, verified staging and rollback. Standard library only."""
import hashlib
from http.client import IncompleteRead
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import ssl
import stat
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler
import zipfile

APP_ID = "MumuCollector"
MAX_DOWNLOAD = 25_000_000
MAX_EXPANDED = 80_000_000
NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class UpdateError(Exception):
    pass


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{1,4}\.\d{1,4}\.\d{1,4}", value):
        raise UpdateError("지원하지 않는 버전 형식입니다.")
    return tuple(map(int, value.split(".")))


def https_url(value):
    if not isinstance(value, str):
        raise UpdateError("업데이트 주소를 확인하세요.")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise UpdateError("업데이트에는 로그인 정보가 없는 HTTPS 주소가 필요합니다.")
    return value


class HttpsRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        https_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def read_url(url, stop, limit, destination=None, progress=lambda value: None):
    https_url(url)
    deadline = time.monotonic() + 180
    for attempt in range(3):
        if stop.is_set():raise UpdateError("업데이트 확인을 취소했습니다.")
        if time.monotonic() >= deadline:raise UpdateError("업데이트 다운로드 시간이 초과되었습니다.")
        try:
            return _read_url_once(url, stop, limit, destination, progress, deadline)
        except HTTPError as exc:
            if exc.code not in {408, 429, 500, 502, 503, 504}:raise
            reason = "배포 서버 응답 지연(HTTP "+str(exc.code)+")"
            exc.close()
        except URLError as exc:
            if isinstance(exc.reason, ssl.SSLError):raise
            reason = "배포 서버 연결 실패: "+str(exc.reason)
        except (TimeoutError, ConnectionError, IncompleteRead) as exc:
            reason = "배포 서버 연결 지연 또는 끊김: "+str(exc)
        if attempt == 2:raise UpdateError(reason+" / 3회 시도했습니다. 잠시 후 새 버전 확인을 다시 눌러 주세요.")
        # A failed download is restarted from zero, then checked against the
        # exact release size and SHA-256. Never append unverified partial bytes.
        if stop.wait(min(2**attempt, max(0, deadline-time.monotonic()))):
            raise UpdateError("업데이트 확인을 취소했습니다.")


def _read_url_once(url, stop, limit, destination, progress, deadline):
    opener = build_opener(HTTPSHandler(context=ssl.create_default_context()), HttpsRedirect())
    request = Request(url, headers={"User-Agent": "MumuCollector-Updater/1", "Accept": "*/*", "Cache-Control": "no-cache"})
    chunks, size = [], 0
    stream = None
    try:
        if destination:
            stream = Path(destination).open("wb")
        progress(0)
        with opener.open(request, timeout=min(30, max(.1, deadline-time.monotonic()))) as response:
            https_url(response.geturl())
            while True:
                if stop.is_set():raise UpdateError("업데이트 확인을 취소했습니다.")
                if time.monotonic() > deadline:raise UpdateError("업데이트 다운로드 시간이 초과되었습니다.")
                block = response.read(65536)
                if not block:break
                size += len(block)
                if size > limit:raise UpdateError("업데이트 파일이 허용된 크기를 초과했습니다.")
                if stream:stream.write(block)
                else:chunks.append(block)
                progress(size)
        return size if destination else b"".join(chunks)
    finally:
        if stream:stream.close()


def check_feed(url, current, stop):
    try:
        data = json.loads(read_url(url, stop, 65536))
        if data["app_id"] != APP_ID or data["protocol"] != 1:
            raise UpdateError("이 도우미의 업데이트 정보가 아닙니다.")
        newer = version_tuple(data["version"]) > version_tuple(current)
        https_url(data["url"])
        if not re.fullmatch(r"[a-f0-9]{64}", data["sha256"]):
            raise UpdateError("업데이트 검증 정보가 올바르지 않습니다.")
        if type(data["size"]) is not int or not 0 < data["size"] <= MAX_DOWNLOAD:
            raise UpdateError("업데이트 크기 정보가 올바르지 않습니다.")
        return data if newer else None
    except (KeyError, ValueError, TypeError) as exc:
        raise UpdateError("업데이트 정보 파일을 읽을 수 없습니다.") from exc


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else _legacy_hash(stream)


def _legacy_hash(stream):
    result = hashlib.sha256()
    for chunk in iter(lambda: stream.read(65536), b""):result.update(chunk)
    return result.hexdigest()


def safe_name(name):
    path = PurePosixPath(name)
    if (not name or "\\" in name or ":" in name or path.is_absolute()
            or any(p in {"", ".", ".."} or p.startswith(".") or p.endswith((" ", "."))
                   or re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", p)
                   for p in name.split("/"))):
        raise UpdateError("업데이트 파일에 잘못된 경로가 있습니다.")
    if len(path.parts) > 2 or (len(path.parts) == 2 and path.parts[0] not in {"assets", "fixtures"}):
        raise UpdateError("업데이트 대상이 아닌 폴더가 포함돼 있습니다.")
    if path.suffix.lower() not in {".py", ".pyw", ".txt", ".json", ".png", ".ico", ".bat", ".vbs"}:
        raise UpdateError("지원하지 않는 업데이트 파일입니다.")
    if path.name.casefold() in {"background_settings.json", "settings.json", "collection_history.json", "update_result.json"}:
        raise UpdateError("업데이트가 사용자 설정을 덮어쓸 수 없습니다.")
    return path


def stage_archive(archive_path, work, current, install, expected=None):
    archive_path, work, install = Path(archive_path), Path(work), Path(install)
    if archive_path.stat().st_size > MAX_DOWNLOAD:raise UpdateError("업데이트 파일이 너무 큽니다.")
    if expected and (archive_path.stat().st_size != expected["size"] or digest(archive_path) != expected["sha256"]):
        raise UpdateError("다운로드 검증에 실패했습니다. 현재 버전은 변경하지 않았습니다.")
    stage = work / "stage"
    stage.mkdir(parents=True, exist_ok=False)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            entries = [item for item in archive.infolist() if not item.is_dir()]
            if not entries or len(entries) > 400 or sum(e.file_size for e in entries) > MAX_EXPANDED:
                raise UpdateError("업데이트 압축 크기 또는 파일 수가 올바르지 않습니다.")
            roots = {e.filename.split("/")[0] for e in entries}
            if len(roots) != 1 or not next(iter(roots)).startswith("MumuCollector_v"):
                raise UpdateError("수령 도우미 업데이트 ZIP을 선택하세요.")
            names = {}
            for entry in entries:
                root, sep, name = entry.filename.partition("/")
                safe_name(root + ".txt")
                if not sep:raise UpdateError("업데이트 경로 오류")
                safe_name(name)
                if stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1:
                    raise UpdateError("링크 또는 암호화된 파일은 업데이트할 수 없습니다.")
                key = name.casefold()
                if key in names:raise UpdateError("중복 업데이트 경로입니다.")
                names[key] = (name, entry)
            if "release.json" not in names:raise UpdateError("업데이트 정보가 없는 ZIP입니다.")
            meta_entry = names["release.json"][1]
            if meta_entry.file_size > 65536:raise UpdateError("업데이트 정보가 너무 큽니다.")
            meta = json.loads(archive.read(meta_entry))
            if meta["app_id"] != APP_ID or meta["protocol"] != 1:raise UpdateError("다른 프로그램의 업데이트입니다.")
            if version_tuple(meta["version"]) <= version_tuple(current):raise UpdateError("현재보다 새로운 버전만 적용할 수 있습니다.")
            if expected and meta["version"] != expected["version"]:raise UpdateError("배포 정보와 ZIP 버전이 다릅니다.")
            files = meta["files"]
            if not isinstance(files, dict) or set(files) != {name for name, _ in names.values()} - {"release.json"}:
                raise UpdateError("업데이트 파일 목록이 일치하지 않습니다.")
            required = {"app.py", "launch.pyw", "updater.py", "update_worker.py", "instance_lock.py", "version.py", "requirements.txt", "assets/templates.json"}
            if not required <= set(files):raise UpdateError("필수 업데이트 파일이 없습니다.")
            if files["requirements.txt"] != digest(install / "requirements.txt"):
                raise UpdateError("실행 환경 변경이 필요한 버전입니다. 전체 설치본으로 설치해 주세요.")
            for name, entry in names.values():
                raw = archive.read(entry)
                if name != "release.json" and hashlib.sha256(raw).hexdigest() != files[name]:
                    raise UpdateError("압축 파일 내부 검증에 실패했습니다: " + name)
                target = stage / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
            text = (stage / "version.py").read_text(encoding="utf-8")
            if not re.fullmatch(r'\s*VERSION\s*=\s*[\"\x27]' + re.escape(meta["version"]) + r'[\"\x27]\s*', text):
                raise UpdateError("앱 버전 파일이 배포 정보와 다릅니다.")
        return meta
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def download_update(info, work, stop, current, install, progress=lambda value: None):
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    path = work / "download.zip"
    read_url(info["url"], stop, info["size"], path, progress)
    if stop.is_set():raise UpdateError("업데이트를 취소했습니다.")
    return stage_archive(path, work, current, install, info)


def atomic_json(path, data):
    path = Path(path)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def prepare_job(install, data, work, meta):
    install, data, work = Path(install).resolve(), Path(data).resolve(), Path(work).resolve()
    # The helper is copied from the running, installed version, not the download.
    helper = work / "helper"
    helper.mkdir(exist_ok=True)
    for name in ("updater.py", "update_worker.py", "instance_lock.py"):
        shutil.copy2(install / name, helper / name)
    job = {"install": str(install), "data": str(data), "work": str(work),
           "version": meta["version"], "files": {**meta["files"], "release.json": digest(work/"stage"/"release.json")},
           "python": sys.executable, "status": "prepared"}
    atomic_json(work / "job.json", job)
    return work / "job.json"


def start_helper(job_path):
    job_path = Path(job_path)
    return subprocess.Popen([sys.executable, str(job_path.parent/"helper"/"update_worker.py"), str(job_path)],
        cwd=job_path.parent, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)


def install_transaction(job, health_check=None):
    """Replace only listed program files; exceptions restore all changed files."""
    install, work = Path(job["install"]), Path(job["work"])
    stage, backup = work / "stage", work / "backup"
    if backup.exists():raise UpdateError("이미 적용한 업데이트 작업입니다.")
    for name, checksum in job["files"].items():
        safe_name(name)
        target = install / name
        if any(p.is_symlink() for p in [target, *target.parents]):raise UpdateError("설치 경로에 링크가 있습니다.")
        if target.exists() and not target.is_file():raise UpdateError("업데이트 파일 위치에 폴더가 있습니다.")
        if digest(stage / name) != checksum:raise UpdateError("대기 중인 업데이트 파일이 변경되었습니다.")
    backup.mkdir()
    existed = [name for name in job["files"] if (install/name).is_file()]
    job.update(status="backing_up", existed=existed)
    atomic_json(work/"job.json", job)
    for name in existed:
        target = backup/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(install/name, target)
    job["status"] = "applying"
    atomic_json(work/"job.json", job)
    try:
        for name in job["files"]:
            target = install/name
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(target.name + ".update-tmp")
            shutil.copy2(stage/name, temp)
            os.replace(temp, target)
        # Cached bytecode may have the same size/timestamp after a fast update.
        shutil.rmtree(install/"__pycache__", ignore_errors=True)
        if health_check:
            health_check()
        else:
            subprocess.run([job["python"], "-B", "-c",
                "import app; from vision import Vision; Vision(); from version import VERSION; assert VERSION == " + repr(job["version"])],
                cwd=install, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=30, check=True, creationflags=NO_WINDOW)
    except Exception:
        rollback(job)
        raise
    job["status"] = "complete"
    atomic_json(work/"job.json", job)


def rollback(job):
    install, work = Path(job["install"]), Path(job["work"])
    for name in job["files"]:
        target = install/name
        if name in job["existed"]:
            temp = target.with_name(target.name + ".update-tmp")
            shutil.copy2(work/"backup"/name, temp)
            os.replace(temp, target)
        else:
            target.unlink(missing_ok=True)
        target.with_name(target.name + ".update-tmp").unlink(missing_ok=True)
    shutil.rmtree(install/"__pycache__", ignore_errors=True)
    job["status"] = "rolled_back"
    atomic_json(work/"job.json", job)


def recover_interrupted(data, install):
    """Called by launcher with the instance lock, before importing app files."""
    for job_path in (Path(data)/"updates").glob("*/job.json"):
        job = json.loads(job_path.read_text(encoding="utf-8"))
        if Path(job["install"]).resolve() == Path(install).resolve() and job.get("status") == "applying":
            rollback(job)
            atomic_json(Path(data)/"update_result.json", {"ok": False,
                "message": "중단된 업데이트를 이전 버전으로 복구했습니다."})


def cleanup_updates(data):
    """Keep two rollback copies; discard abandoned staging from earlier runs."""
    completed = []
    for work in (Path(data)/"updates").glob("release-*"):
        if not work.is_dir() or work.is_symlink():continue
        if (work/'exe-job.json').exists():continue
        job_path = work/"job.json"
        if not job_path.exists():
            shutil.rmtree(work, ignore_errors=True)
            continue
        try:
            job = json.loads(job_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):continue
        if job.get("status") in {"complete", "rolled_back"}:
            completed.append(work)
    for work in sorted(completed, key=lambda p:p.stat().st_mtime, reverse=True)[2:]:
        shutil.rmtree(work, ignore_errors=True)
