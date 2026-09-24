"""Exercise real frozen helper update/restart and rollback on Windows."""
from pathlib import Path
import json,os,shutil,subprocess,sys,tempfile,time
import psutil
from unittest.mock import patch
import exe_updater as u
from version import VERSION


def main(exe,archive):
    exe,archive=Path(exe).resolve(),Path(archive).resolve()
    info=json.loads((exe.parent/'latest-exe.json').read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory(prefix='Chanki Windows 한글 ') as folder:
        root=Path(folder);target=root/'창키 도우미.exe';shutil.copy2(exe,target)
        data=root/'data';data.mkdir();work=data/'updates'/'release-test';work.mkdir(parents=True)
        meta=u.stage_archive(archive,work,'0.0.0',info)
        with patch.object(u.sys,'executable',str(target)):
            job_path=u.prepare_job(root,data,work,meta)
        # A real frozen EXE helper replaces the EXE, validates it, and restarts UI.
        env=u.fresh_env();env['LOCALAPPDATA']=str(root/'userdata');env['PATH']=str(Path(os.environ['SystemRoot'])/'System32')
        child=subprocess.Popen([str(work/'helper.exe'),'--update-worker',str(job_path)],env=env,cwd=work)
        try:
            assert child.wait(timeout=150)==0
            assert json.loads(job_path.read_text(encoding='utf-8'))['status']=='complete'
            assert u.digest(target)==u.digest(exe)
            health=json.loads((work/'health.json').read_text(encoding='utf-8'))
            assert health['ok'] and health['startup_ui'] and not health['full_ui_checks']
        except BaseException:
            # Keep the original failure and stop only processes from this test.
            for path in [job_path,work/'health.json',work/'health.progress.json',
                         work/'health.threads.log',
                         work/'health-data'/'MumuCollector'/'exe_error.log',data/'update_result.json']:
                if path.is_file():
                    print('UPDATE_DIAGNOSTIC',path.name,path.read_text(encoding='utf-8'),flush=True)
                    shutil.copy2(path,exe.parent/('update-diagnostic-'+path.name))
            owned=[]
            for proc in psutil.process_iter(['pid','exe']):
                try:
                    if proc.info['exe'] and any(os.path.samefile(proc.info['exe'],p) for p in [target,work/'helper.exe']):
                        owned.append(proc);proc.kill()
                except (OSError,psutil.NoSuchProcess,psutil.AccessDenied):pass
            psutil.wait_procs(owned,timeout=15)
            raise
        # Stop only this test's restarted EXE before temporary-directory cleanup.
        deadline=time.monotonic()+30
        matched=[]
        while time.monotonic()<deadline:
            matched=[]
            for proc in psutil.process_iter(['pid','exe']):
                try:
                    if proc.info['exe'] and os.path.samefile(proc.info['exe'],target):matched.append(proc)
                except (OSError,psutil.NoSuchProcess):pass
            if matched and (root/'userdata'/'MumuCollector'/'collector.lock').exists():break
            time.sleep(.3)
        assert matched,'Updated EXE did not restart'
        # Windows can report the same path with its 8.3 short spelling.
        # Stop all matching bootloader/application processes before cleanup.
        for proc in matched:
            try:proc.kill()
            except psutil.NoSuchProcess:pass
        gone,alive=psutil.wait_procs(matched,timeout=15)
        assert not alive,'Test processes did not exit'
        # Actual Windows file replacement plus failure-triggered restoration.
        rollback=root/'rollback';rollback.mkdir();(rollback/'stage').mkdir()
        dummy=root/'dummy.exe';dummy.write_bytes(b'MZ old')
        (rollback/'stage'/u.EXE_NAME).write_bytes(b'MZ new')
        job={'target':str(dummy),'work':str(rollback),'sha256':u.digest(rollback/'stage'/u.EXE_NAME),'version':VERSION}
        def fail():raise RuntimeError('health check failed')
        try:u.install(job,health=fail)
        except RuntimeError:pass
        else:raise AssertionError('Expected rollback')
        assert dummy.read_bytes()==b'MZ old' and job['status']=='rolled_back'
    (exe.parent/'windows-validation.json').write_text(json.dumps({'ok':True,'real_exe_update':True,'restart':True,'rollback':True}),encoding='utf-8')

if __name__=='__main__':main(sys.argv[1],sys.argv[2])
