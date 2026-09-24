"""Real archives/files; rejected downloads and reversible installation failures."""
import hashlib
import json
from pathlib import Path
import shutil
import stat
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile
from build_release import build
import updater as u
from instance_lock import InstanceLock


class UpdateTests(unittest.TestCase):
    def setUp(self):
        version_patch=patch("build_release.VERSION","0.4.0");version_patch.start();self.addCleanup(version_patch.stop)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.source=self.base/"source";self.source.mkdir()
        self.install=self.base/"설치 폴더";self.install.mkdir()
        for name in ("app.py","launch.pyw","updater.py","update_worker.py","instance_lock.py"):
            (self.source/name).write_text("# new app\n",encoding="utf-8")
            (self.install/name).write_text("# old app\n",encoding="utf-8")
        (self.source/"version.py").write_text('VERSION = "0.4.0"\n')
        (self.install/"version.py").write_text('VERSION = "0.3.9"\n')
        (self.source/"requirements.txt").write_text("test dependency\n")
        (self.install/"requirements.txt").write_text("test dependency\n")
        (self.source/"assets").mkdir();(self.source/"assets/templates.json").write_text("{}")
        (self.install/"assets").mkdir();(self.install/"assets/templates.json").write_text('{"old":true}')
        (self.install/".venv").mkdir();(self.install/".venv/keep").write_text("keep")
        (self.install/"background_settings.json").write_text('{"keep":true}')
        self.archive,self.sha=build(self.source,self.base/"out", "https://example.test/app.zip","https://example.test/latest.json")
        self.info=json.loads((self.base/"out/latest.json").read_text(encoding="utf-8"))
        self.work=self.base/"work";self.work.mkdir()

    def stage(self,archive=None,current="0.3.9",expected=True):
        return u.stage_archive(archive or self.archive,self.work,current,self.install,self.info if expected else None)

    def mutated(self,extra=None,replace=None):
        target=self.base/"changed.zip"
        with zipfile.ZipFile(self.archive) as old,zipfile.ZipFile(target,"w",zipfile.ZIP_DEFLATED) as new:
            for name in old.namelist():
                raw=old.read(name)
                if replace and name.endswith(replace[0]):raw=replace[1]
                new.writestr(name,raw)
            if extra:new.writestr(*extra)
        return target

    def job(self):
        meta=self.stage()
        path=u.prepare_job(self.install,self.base,self.work,meta)
        return json.loads(path.read_text(encoding="utf-8"))

    def test_valid_package_stages_without_changing_installation(self):
        meta=self.stage()
        self.assertEqual(meta["version"],"0.4.0")
        self.assertEqual((self.install/"app.py").read_text(encoding="utf-8"),"# old app\n")

    def test_truncated_download_rejected(self):
        self.archive.write_bytes(self.archive.read_bytes()[:-10])
        with self.assertRaises(u.UpdateError):self.stage()
        self.assertFalse((self.work/"stage").exists())

    def test_bad_sha_rejected(self):
        self.info["sha256"]="0"*64
        with self.assertRaises(u.UpdateError):self.stage()

    def test_internal_modified_file_rejected(self):
        archive=self.mutated(replace=("app.py",b"tampered"))
        with self.assertRaises(u.UpdateError):self.stage(archive,expected=False)
        self.assertFalse((self.work/"stage").exists())

    def test_traversal_rejected(self):
        archive=self.mutated(extra=("MumuCollector_v0.4.0/../escape.py",b"bad"))
        with self.assertRaises(u.UpdateError):self.stage(archive,expected=False)
        self.assertFalse((self.base/"escape.py").exists())

    def test_case_insensitive_duplicate_rejected(self):
        archive=self.mutated(extra=("MumuCollector_v0.4.0/APP.PY",b"bad"))
        with self.assertRaises(u.UpdateError):self.stage(archive,expected=False)

    def test_user_settings_in_package_rejected(self):
        archive=self.mutated(extra=("MumuCollector_v0.4.0/background_settings.json",b"{}"))
        with self.assertRaises(u.UpdateError):self.stage(archive,expected=False)

    def test_zip_symlink_rejected(self):
        entry=zipfile.ZipInfo("MumuCollector_v0.4.0/link.py");entry.create_system=3
        entry.external_attr=(stat.S_IFLNK|0o777)<<16
        archive=self.mutated(extra=(entry,b"app.py"))
        with self.assertRaises(u.UpdateError):self.stage(archive,expected=False)

    def test_no_downgrade_or_reinstall(self):
        with self.assertRaises(u.UpdateError):self.stage(current="0.4.0")

    def test_changed_dependencies_require_full_installer(self):
        (self.install/"requirements.txt").write_text("different")
        with self.assertRaisesRegex(u.UpdateError,"실행 환경 변경"):self.stage()

    def test_feed_mismatch_rejected(self):
        self.info["version"]="0.4.1"
        with self.assertRaises(u.UpdateError):self.stage()

    def test_apply_preserves_settings_and_environment(self):
        job=self.job();u.install_transaction(job,health_check=lambda:None)
        self.assertEqual((self.install/"app.py").read_text(encoding="utf-8"),"# new app\n")
        self.assertEqual((self.install/"background_settings.json").read_text(encoding="utf-8"),'{"keep":true}')
        self.assertEqual((self.install/".venv/keep").read_text(encoding="utf-8"),"keep")
        self.assertEqual(job["status"],"complete")

    def test_health_failure_rolls_back_every_file(self):
        before={p.relative_to(self.install).as_posix():p.read_bytes() for p in self.install.rglob("*") if p.is_file()}
        job=self.job()
        def fail():raise RuntimeError("new app cannot start")
        with self.assertRaises(RuntimeError):u.install_transaction(job,fail)
        after={p.relative_to(self.install).as_posix():p.read_bytes() for p in self.install.rglob("*") if p.is_file()}
        self.assertEqual(before,after);self.assertEqual(job["status"],"rolled_back")

    def test_partial_file_write_failure_rolls_back(self):
        job=self.job();original=u.os.replace;count=[0]
        def fail_one(src,dst):
            if Path(src).name.endswith(".update-tmp"):
                count[0]+=1
                if count[0]==3:raise OSError("disk failure")
            return original(src,dst)
        with patch.object(u.os,"replace",side_effect=fail_one):
            with self.assertRaises(OSError):u.install_transaction(job,lambda:None)
        self.assertEqual((self.install/"app.py").read_text(encoding="utf-8"),"# old app\n")
        self.assertEqual((self.install/"version.py").read_text(encoding="utf-8"),'VERSION = "0.3.9"\n')
        self.assertFalse((self.install/"release.json").exists())

    def test_staged_file_changed_blocks_all_writes(self):
        job=self.job();(self.work/"stage/app.py").write_text("tampered")
        with self.assertRaises(u.UpdateError):u.install_transaction(job,lambda:None)
        self.assertEqual((self.install/"app.py").read_text(encoding="utf-8"),"# old app\n")

    def test_symlink_install_target_rejected(self):
        job=self.job();(self.install/"app.py").unlink()
        (self.install/"app.py").symlink_to(self.base/"outside.py")
        with self.assertRaises(u.UpdateError):u.install_transaction(job,lambda:None)
        self.assertFalse((self.base/"outside.py").exists())

    def test_interrupted_transaction_recovered_on_next_launch(self):
        job=self.job()
        u.install_transaction(job,lambda:None)
        job["status"]="applying";u.atomic_json(self.work/"job.json",job)
        updates=self.base/"updates";updates.mkdir()
        new=updates/"interrupted";shutil.move(self.work,new)
        job["work"]=str(new);u.atomic_json(new/"job.json",job)
        u.recover_interrupted(self.base,self.install)
        self.assertEqual((self.install/"app.py").read_text(encoding="utf-8"),"# old app\n")
        self.assertFalse(json.loads((self.base/"update_result.json").read_text(encoding="utf-8"))["ok"])

    def test_feed_allows_only_https_and_valid_metadata(self):
        with patch.object(u,"read_url",return_value=json.dumps(self.info).encode()):
            self.assertEqual(u.check_feed("https://example.test/latest.json","0.3.9",threading.Event())["version"],"0.4.0")
            self.assertIsNone(u.check_feed("https://example.test/latest.json","0.4.0",threading.Event()))
        self.info["url"]="http://example.test/app.zip"
        with patch.object(u,"read_url",return_value=json.dumps(self.info).encode()):
            with self.assertRaises(u.UpdateError):u.check_feed("https://example.test/latest.json","0.3.9",threading.Event())
        for url in ("http://example.test/app.zip","file:///tmp/app.zip","https://user:token@example.test/app.zip"):
            with self.assertRaises(u.UpdateError):u.https_url(url)

    def test_http_redirect_downgrade_rejected(self):
        with self.assertRaises(u.UpdateError):
            u.HttpsRedirect().redirect_request(None,None,302,"",{},"http://example.test/app.zip")

    def test_stream_download_validation_and_cancel(self):
        raw=self.archive.read_bytes()
        class Response:
            def __init__(self):self.raw=raw
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def geturl(self):return "https://example.test/app.zip"
            def read(self,n):chunk,self.raw=self.raw[:n],self.raw[n:];return chunk
        with patch.object(u,"build_opener") as opener:
            opener.return_value.open.side_effect=lambda *a,**k:Response()
            meta=u.download_update(self.info,self.work,threading.Event(),"0.3.9",self.install)
            self.assertEqual(meta["version"],"0.4.0")
            stopped=threading.Event();stopped.set()
            with self.assertRaises(u.UpdateError):u.read_url("https://example.test/app.zip",stopped,100)

    def test_real_helper_waits_for_instance_exit_then_restarts_updated_app(self):
        source=Path(__file__).parent
        for name in ("updater.py","update_worker.py","instance_lock.py"):
            shutil.copy2(source/name,self.install/name)
            shutil.copy2(source/name,self.source/name)
        (self.source/"vision.py").write_text("class Vision: pass\n")
        (self.source/"launch.pyw").write_text('from pathlib import Path\nfrom version import VERSION\nPath("restarted.txt").write_text(VERSION)\n')
        self.archive,_=build(self.source,self.base/"out","https://example.test/app.zip")
        self.info=json.loads((self.base/"out/latest.json").read_text(encoding="utf-8"))
        meta=self.stage();job=u.prepare_job(self.install,self.base,self.work,meta)
        lock=InstanceLock(self.base/"collector.lock");self.assertTrue(lock.acquire())
        child=u.start_helper(job)
        try:
            time.sleep(.3)
            self.assertIsNone(child.poll())
            self.assertEqual((self.install/"version.py").read_text(encoding="utf-8"),'VERSION = "0.3.9"\n')
            lock.release();child.wait(timeout=10)
            deadline=time.monotonic()+3
            while not (self.install/"restarted.txt").exists() and time.monotonic()<deadline:time.sleep(.05)
            self.assertEqual((self.install/"restarted.txt").read_text(encoding="utf-8"),"0.4.0")
            self.assertTrue(json.loads((self.base/"update_result.json").read_text(encoding="utf-8"))["ok"])
            self.assertEqual((self.install/".venv/keep").read_text(encoding="utf-8"),"keep")
        finally:
            lock.release()
            if child.poll() is None:child.terminate();child.wait(timeout=3)


if __name__=="__main__":unittest.main()
