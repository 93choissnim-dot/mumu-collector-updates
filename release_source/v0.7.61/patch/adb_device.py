"""ADB-only capture and touch. Does not capture the PC desktop or move its mouse."""
from pathlib import Path
from io import BytesIO
import os
import re
import shutil
import subprocess
import threading
import time
import tempfile
import uuid
import cv2
import numpy as np
from PIL import Image
from collector import Halt


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
CAPTURE_MODES = ("exec-out", "shell", "pull")
PACKAGE_QUERIES = (("window", "displays"), ("window",), ("activity", "activities"))
FOCUS_KEYS = ("mCurrentFocus", "mFocusedApp", "topResumedActivity", "mResumedActivity", "ResumedActivity")
READY_STATES = frozenset({"main", "menu", "sleep", "equipment", "offline_reward", "reward", "exit_dialog"} |
                         {room+suffix for room in ("farm", "wood", "mine")
                          for suffix in ("_ready", "_empty", "_wait")})
from task_catalog import PAGE_MARKERS
READY_STATES = READY_STATES | frozenset(PAGE_MARKERS)
# Verified in the user's MuMu diagnostic capture. Unknown pages are bound only
# in this exact game, never in a launcher, another app or an inferred package.
RECOVERY_PACKAGES = frozenset({"com.nns.genesis"})
from daily_actions import DAILY_PAGES
DAILY_RECOVERY_STATES = frozenset(DAILY_PAGES) | {"daily_battle", "daily_clear", "daily_result"}


def response_summary(raw):
    """Small diagnostic only; never log the complete screenshot byte stream."""
    head = raw[:160]
    details = f"{len(raw)} bytes / 앞 24바이트: {raw[:24].hex(' ')}"
    if head and b"\x00" not in head and b"PNG" not in head:
        text = " ".join(head.decode("utf-8", errors="replace").split())
        details += " / 응답: " + text
    return details


def decode_capture(raw):
    """Validate before decoding; repair only legacy newline conversion with valid CRCs."""
    candidate = raw
    for _ in range(3):
        offset = candidate.find(PNG_SIGNATURE, 0, 4096)
        if offset >= 0:
            png = candidate[offset:]
            try:
                with Image.open(BytesIO(png)) as image:
                    width, height = image.size
                    if image.format != "PNG" or min(width, height) < 200 or width * height > 33_177_600:
                        raise ValueError("지원하지 않는 캡처 크기")
                    image.verify()
                decoded = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
                if decoded is not None and decoded.shape[:2] == (height, width):
                    return decoded
            except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
                pass
        # A good PNG is returned above unchanged, including CR/LF bytes inside IDAT.
        repaired = candidate.replace(b"\r\n", b"\n")
        if repaired == candidate:
            break
        candidate = repaired
    raise Halt("정상 PNG 캡처를 받지 못했습니다. " + response_summary(raw))


def select_verified_device(reports, saved=""):
    """Choose by actual screenshot results, never by assuming a particular port."""
    working = {serial: report for serial, report in reports.items() if report.get("image") is not None}
    game = [serial for serial, report in working.items() if report["state"] != "unknown"]
    if len(game) == 1:
        return game[0]
    if saved in game:
        return saved
    if not game:
        if len(working) == 1:
            return next(iter(working))
        if saved in working:
            return saved
    return ""


def inspect_device(adb, serial, vision, log, capture_mode=None):
    """Identify one local endpoint and capture it; never send touch commands."""
    device = AdbDevice(adb, serial, log=log, capture_mode=capture_mode)
    report = {"model": "기기명 미확인", "package": "앱 미확인", "image": None,
              "state": "unknown", "capture_mode": None, "error": "", "package_error": ""}
    try:
        model = device.command(["shell", "getprop", "ro.product.model"], timeout=4)
        report["model"] = " ".join(model.decode("utf-8", errors="replace").split())[:80] or report["model"]
    except Halt as exc:
        device.check()
        log(f"{serial} / 기기 정보: {exc}")
    try:
        report["package"] = device.current_package()
    except Halt as exc:
        device.check()
        report["package_error"] = str(exc)
        log(f"{serial} / 실행 앱 정보: {exc}")
    try:
        report["image"] = device.capture()
        report["state"] = vision.recognize(report["image"]).state
        report["capture_mode"] = device.capture_mode
    except Halt as exc:
        device.check()
        report["error"] = str(exc)
    return report


def local_serial(value):
    value = str(value).strip()
    match = re.fullmatch(r"(?:127\.0\.0\.1|localhost):(\d{1,5})", value)
    if match and 1 <= int(match.group(1)) <= 65535:
        return "127.0.0.1:" + str(int(match.group(1)))
    raise Halt("뮤뮤 연결 주소는 127.0.0.1:포트번호 형식이어야 합니다.")


def parse_devices(text):
    devices = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            try:
                value = local_serial(parts[0])
            except Halt:
                continue
            if value not in devices:
                devices.append(value)
    return devices


def parse_package(text, display_id=0):
    """Read current focus on the captured default display, not a different app tab.

    Android 12 puts focus in `dumpsys window displays`; the `windows` subcommand
    may contain window records without any current-focus field at all.
    """
    scope = None
    scoped = False
    records = []
    for line in text.splitlines():
        header = re.match(r"\s*Display:\s*mDisplayId=(\d+)\b", line)
        if header is None:
            header = re.match(r"\s*Display\s+#(\d+)\b", line)
        if header:
            scope = int(header.group(1))
            scoped = True
        focus = re.match(r"\s*(" + "|".join(FOCUS_KEYS) + r")\s*[:=]\s*(.*)", line)
        if not focus:
            continue
        # Some older Android dumps put the display ID on the focus line itself.
        inline = re.search(r"\b(?:mDisplayId|displayId)=(\d+)\b", line)
        record_scope = int(inline.group(1)) if inline else scope
        scoped = scoped or inline is not None
        component = re.search(r"\b([A-Za-z][\w]*(?:\.[\w]+)+)/[\w.$]+", focus.group(2))
        if component:
            records.append((record_scope, focus.group(1), component.group(1)))
    for key in FOCUS_KEYS:
        candidates = {package for screen, name, package in records
                      if name == key and (screen == display_id if scoped else display_id == 0)}
        if len(candidates) == 1:
            return candidates.pop()
        if len(candidates) > 1:
            raise Halt("현재 화면의 실행 앱 후보가 여러 개여서 대상을 확정하지 못했습니다.")
    raise Halt("기본 화면의 현재 앱 정보가 없습니다.")


def package_response_summary(text):
    """Log only focus/permission diagnostics, not the full Android window dump."""
    relevant = [line.strip() for line in text.splitlines()
                if any(key in line for key in (*FOCUS_KEYS, "Permission Denial", "not found", "Can't find service"))]
    return " / ".join(relevant[:3])[:220] or f"현재 앱 항목 없음 ({len(text)}자 응답)"


def mumu_locations():
    """Inspect only running MuMu/Nemu processes and their local listening ports."""
    from mumu_paths import related_roots
    roots, ports = [], set()
    try:
        import psutil
        for proc in psutil.process_iter(["name", "exe"]):
            try:
                if not any(x in (proc.info.get("name") or "").lower() for x in ("mumu", "nemu")):
                    continue
                exe = proc.info.get("exe")
                if exe:
                    roots.extend(related_roots(Path(exe).parent))
                for conn in proc.net_connections(kind="tcp"):
                    if conn.status == "LISTEN" and conn.laddr and conn.laddr.ip in ("127.0.0.1", "0.0.0.0"):
                        if conn.laddr.port != 5037:
                            ports.add(conn.laddr.port)
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                pass
    except ImportError:
        pass
    except Exception:
        # A failed discovery never expands to unrelated process or network scans.
        pass
    for key in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(key)
        if base:
            roots.extend(Path(base)/p for p in ("Netease/MuMuPlayer-12.0", "Netease/MuMuPlayer",
                "Netease/MuMuPlayerGlobal-12.0", "Netease/MuMuPlayerGlobal", "Nemu"))
    return list(dict.fromkeys(roots)), sorted(ports)


def find_adb(roots):
    from mumu_paths import executable_candidates
    candidates = executable_candidates(roots, ("adb.exe", "adb_server.exe"))
    if candidates:return str(candidates[0])
    path = shutil.which("adb.exe") or shutil.which("adb")
    return path or ""


class Adb:
    def __init__(self, executable, stop=None):
        path = Path(executable).expanduser()
        if not path.is_file():
            raise Halt("ADB 실행 파일을 찾지 못했습니다. 뮤뮤 폴더의 adb.exe 또는 adb_server.exe를 선택하세요.")
        self.path = str(path.resolve())
        self.stop = stop if stop is not None else threading.Event()

    def run(self, args, timeout=10, input_generation=None):
        from contextlib import nullcontext
        from run_control import RunControl, checkpoint
        is_input = 'shell' in args and ('input' in args or ('am' in args and 'start' in args))
        if not is_input:
            checkpoint(self.stop)
        if self.stop.is_set():
            raise Halt("사용자가 중지했습니다.")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        # Default local server; never inherit a remote ADB_SERVER_SOCKET.
        env = dict(os.environ)
        for key in ("ADB_SERVER_SOCKET", "ANDROID_ADB_SERVER_ADDRESS", "ANDROID_ADB_SERVER_PORT", "ANDROID_SERIAL"):
            env.pop(key, None)
        try:
            guard = self.stop.input_guard(input_generation) if is_input and isinstance(self.stop, RunControl) else nullcontext()
            with guard:
                proc = subprocess.Popen([self.path, "-P", "5037", *map(str,args)],
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        stdin=subprocess.DEVNULL, creationflags=flags, env=env)
        except OSError as exc:
            raise Halt("ADB를 실행하지 못했습니다: " + str(exc)) from exc
        deadline = time.monotonic()+timeout
        try:
            while True:
                if self.stop.is_set():
                    raise Halt("사용자가 중지했습니다.")
                if time.monotonic() >= deadline:
                    raise Halt("뮤뮤 응답 시간 초과. ADB 연결과 실행 상태를 확인하세요.")
                try:
                    out, error = proc.communicate(timeout=.1)
                    break
                except subprocess.TimeoutExpired:
                    pass
            if self.stop.is_set():
                raise Halt("사용자가 중지했습니다.")
            if proc.returncode:
                reason = (error or out).decode("utf-8", errors="replace").strip()[:400]
                raise Halt("ADB 연결/명령 실패: " + (reason or str(proc.returncode)))
            return out
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()

    def devices(self):
        return parse_devices(self.run(["devices", "-l"]).decode("utf-8", errors="replace"))

    def connect(self, serial):
        serial = local_serial(serial)
        self.run(["connect", serial], timeout=4)
        return serial in self.devices()

    def is_connected(self, serial):
        """Read-only transport check; cancellation is never a lost connection."""
        try:
            return self.run(["-s", local_serial(serial), "get-state"], timeout=4).strip() == b"device"
        except Halt:
            if self.stop.is_set():
                raise
            return False

    def ensure_connected(self, serial, log=None):
        """Keep an existing link; recover only the selected local endpoint once.

        No server reset, endpoint discovery, or input is part of this check.
        A resumed operation must bind the current game again after it returns.
        """
        serial = local_serial(serial)
        log = log or (lambda text: None)
        try:
            state = self.run(["-s", serial, "get-state"], timeout=4).decode("utf-8", errors="replace").strip()
            if state == "device":
                return
        except Halt:
            if self.stop.is_set():
                raise
        if self.stop.is_set():
            raise Halt("사용자가 중지했습니다.")
        log(serial + " / 선택한 주소에 다시 연결 중")
        if not self.connect(serial):
            raise Halt("선택한 뮤뮤에 연결할 수 없습니다. 주소는 유지했습니다. 뮤뮤 실행 상태를 확인한 뒤 다시 시작하세요.")
        log(serial + " / 연결 복구 완료")


def discover(executable, address, stop, log, instances=None):
    roots, ports = mumu_locations()
    executable = executable.strip() or find_adb(roots)
    adb = Adb(executable, stop)
    if address.strip():
        value = address.strip()
        if value.isdigit():
            value = "127.0.0.1:"+value
        serial = local_serial(value)
        if not adb.connect(serial):
            raise Halt("지정한 주소에 연결되지 않았습니다. 뮤뮤의 ADB 포트를 확인하세요.")
        return adb.path, [serial]
    if instances and not address.strip():
        # Use each instance's official endpoint, not compatibility aliases.
        connected=adb.devices();verified=[]
        for serial in instances:
            if stop.is_set():raise Halt("사용자가 중지했습니다.")
            try:
                if serial in connected or adb.connect(serial):verified.append(serial)
            except Halt:
                if stop.is_set():raise
                log("뮤뮤 연결 확인 실패: "+instances[serial])
        if verified:return adb.path,verified
        raise Halt("실행 중인 뮤뮤에 연결하지 못했습니다. 뮤뮤의 ADB 허용 상태를 확인해 주세요.")
    connected = adb.devices()
    if connected:
        return adb.path, connected
    # 7555 is documented by MuMu. Other candidates are owned by running MuMu processes.
    candidates = list(dict.fromkeys([7555, *ports]))[:12]
    for port in candidates:
        if stop.is_set():
            raise Halt("사용자가 중지했습니다.")
        log(f"뮤뮤 로컬 연결 확인: {port}")
        try:
            adb.connect("127.0.0.1:"+str(port))
        except Halt:
            if stop.is_set():
                raise
    connected = adb.devices()
    if not connected:
        raise Halt("연결된 뮤뮤가 없습니다. ADB 허용 여부와 포트를 확인한 뒤 포트를 직접 입력하세요.")
    return adb.path, connected


class AdbDevice:
    def __init__(self, adb, serial, log=None, capture_mode=None):
        self.adb, self.serial = adb, local_serial(serial)
        self.size = None
        self.package = None
        self.last_capture = None
        self.log = log or (lambda text: None)
        self.capture_mode = capture_mode if capture_mode in CAPTURE_MODES else None
        self.package_query = None
        self.capture_generation = getattr(adb.stop, 'generation', None)

    def command(self, args, timeout=10):
        if isinstance(self.adb, Adb) and 'shell' in args and ('input' in args or ('am' in args and 'start' in args)):
            return self.adb.run(['-s', self.serial, *args], timeout=timeout, input_generation=self.capture_generation)
        return self.adb.run(["-s", self.serial, *args], timeout=timeout)

    def check(self):
        from run_control import checkpoint
        checkpoint(self.adb.stop)
        if self.adb.stop.is_set():
            raise Halt("사용자가 중지했습니다.")

    def current_package(self):
        queries = ([self.package_query] if self.package_query else [])
        queries += [query for query in PACKAGE_QUERIES if query not in queries]
        failures = []
        for query in queries:
            self.check()
            text = ""
            try:
                text = self.command(["shell", "dumpsys", *query], timeout=6).decode("utf-8", errors="replace")
                package = parse_package(text)
                self.check()
            except Halt as exc:
                self.check()
                failures.append(" ".join(query) + ": " + (package_response_summary(text) if text else str(exc)))
                continue
            # Cache the working window command, never the package value. Activity
            # fallback must not hide a newly available current-window focus later.
            if query[0] == "window":
                if self.package_query != query:
                    self.log(f"{self.serial} / 실행 앱 확인 방식: dumpsys {' '.join(query)}")
                self.package_query = query
            return package
        self.package_query = None
        raise Halt("화면 캡처와 별도로 실행 앱 확인에 실패했습니다. "
                   "수령을 시작하지 않습니다. 조회 결과: " + " | ".join(failures))

    def guard_package(self):
        self.check()
        if self.package:
            try:
                if self.current_package() != self.package:
                    raise Halt("뮤뮤 안에서 다른 앱으로 전환되어 중지했습니다.")
            except Halt:
                self.last_capture = None
                raise

    def file_capture(self):
        # A fresh name on every request prevents an old screenshot from being reused.
        remote = "/sdcard/mumu_collector_" + uuid.uuid4().hex + ".png"
        with tempfile.TemporaryDirectory(prefix="mumu_capture_") as directory:
            local = Path(directory) / "screen.png"
            try:
                self.command(["shell", "screencap", "-p", remote], timeout=12)
                response = self.command(["pull", remote, str(local)], timeout=12)
                if not local.is_file():
                    raise Halt("캡처 파일을 받지 못했습니다. " + response_summary(response))
                return local.read_bytes()
            finally:
                if not self.adb.stop.is_set():
                    try:
                        self.command(["shell", "rm", "-f", remote], timeout=3)
                    except Halt:
                        pass

    def raw_capture(self):
        self.last_capture = None
        modes = ([self.capture_mode] if self.capture_mode else [])
        modes += [mode for mode in CAPTURE_MODES if mode not in modes]
        failures = []
        for mode in modes:
            self.check()
            try:
                if mode == "pull":
                    raw = self.file_capture()
                else:
                    raw = self.command([mode, "screencap", "-p"], timeout=12)
                im = decode_capture(raw)
                self.check()
            except (Halt, OSError) as exc:
                self.check()
                detail = f"{self.serial} / {mode}: {exc}"
                failures.append(detail)
                self.log("캡처 방식 확인 실패: " + detail)
                continue
            if self.capture_mode != mode:
                self.log(f"{self.serial} / 화면 캡처 성공 ({mode})")
            self.capture_mode = mode
            return im
        raise Halt(f"{self.serial} 화면 캡처에 실패했습니다. "
                   "연결된 주소를 바꾸어 화면을 확인하거나 실행 기록을 보내 주세요. "
                   "마지막 응답: " + failures[-1])

    def capture(self):
        self.check()
        generation = getattr(self.adb.stop, 'generation', None)
        self.last_capture = None
        self.guard_package()
        im = self.raw_capture()
        if self.size and tuple(im.shape[1::-1]) != self.size:
            raise Halt("뮤뮤 내부 해상도가 변경되어 중지했습니다. 연결 화면을 다시 확인하세요.")
        self.guard_package()
        self.last_capture = time.monotonic()
        self.capture_generation = generation
        return im

    def bind_game(self, vision):
        # Bind only while a supported game screen and the same Android app are present.
        self.check()
        generation = getattr(self.adb.stop, 'generation', None)
        self.package, self.size, self.last_capture = None, None, None
        first = self.current_package()
        im = self.raw_capture()
        screen = vision.recognize(im)
        recoverable = (first in RECOVERY_PACKAGES and (screen.state == "unknown" or screen.state in DAILY_RECOVERY_STATES)
                       and min(im.shape[:2]) >= 200 and abs(im.shape[1]/im.shape[0]-16/9) <= .055)
        if screen.state not in READY_STATES and not recoverable:
            raise Halt("수령을 시작할 게임 화면을 확인하지 못했습니다. 일반 게임 화면이나 게임 절전 화면에서 '화면 확인'을 눌러 주세요.")
        if first != self.current_package():
            raise Halt("확인 중 뮤뮤의 앱이 변경되었습니다. 다시 시작하세요.")
        self.package, self.size = first, tuple(im.shape[1::-1])
        self.last_capture = time.monotonic()
        self.capture_generation = generation
        return screen

    def position(self, point):
        self.guard_package()
        from run_control import RunControl, ResumeRecognition
        if isinstance(self.adb.stop, RunControl) and self.capture_generation != self.adb.stop.generation:
            raise ResumeRecognition()
        if self.size is None or self.last_capture is None:
            raise Halt("게임 화면 확인 전에는 터치할 수 없습니다.")
        if time.monotonic()-self.last_capture > 5:
            raise Halt("최근 화면 확인 시간이 지나 터치를 중지했습니다.")
        x, y = point
        if not (0 <= x < 960 and 0 <= y < 540):
            raise Halt("터치 위치가 게임 화면 밖입니다.")
        return round(x*self.size[0]/960), round(y*self.size[1]/540)

    def click(self, point):
        x, y = self.position(point)
        self.command(["shell", "input", "tap", x, y])

    def drag(self, start, end):
        x1, y1 = self.position(start)
        x2, y2 = self.position(end)
        self.command(["shell", "input", "swipe", x1, y1, x2, y2, 1000])

    def back(self):
        """MuMu Escape's Android back action, scoped to the bound game device."""
        self.position((0, 0))  # Same app, resolution, fresh capture and pause guard.
        self.command(["shell", "input", "keyevent", "KEYCODE_BACK"])
