"""One-file Windows EXE updates. Separate channel from Python source packages."""
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from version import VERSION
from updater import (UpdateError, digest, read_url, https_url, version_tuple, atomic_json, NO_WINDOW)
from instance_lock import InstanceLock

APP_ID='ChankiHelperExe'
EXE_NAME='창키 도우미.exe'
CHANNEL='https://github.com/93choissnim-dot/mumu-collector-updates/releases/latest/download/latest-exe.json'
MAX_SIZE=200_000_000



def policy_block_message(version):
    return (f'v{version} 실행이 Windows 앱 제어 정책에 차단됐습니다 (WinError 4551). '
            '이 버전의 자동 재시도를 중지했습니다. 진단 파일을 개발자/관리자에게 전달해 '
            '서명·신뢰 정책을 확인한 뒤 “새 버전 확인”으로 직접 재시도하세요.')


def policy_blocked(data, version):
    try:
        path=Path(data)/'update_policy_block.json'
        if path.stat().st_size>65536:return False
        value=json.loads(path.read_text(encoding='utf-8'))
        return (value.get('target_version')==version and value.get('winerror')==4551
                or version in value.get('blocked_versions',[]))
    except (OSError,ValueError,TypeError,AttributeError):return False


def record_failure(job, stage, path, exc, rollback='not_needed'):
    """Persist before recovery so a second failure cannot erase the original cause."""
    failure={'created_at':datetime.now().astimezone().isoformat(),
             'source_version':job.get('source_version','unknown'), 'target_version':job.get('version','unknown'),
             'stage':stage,'path':str(path),'work':job.get('work'),
             'winerror':getattr(exc,'winerror',None),'error_type':type(exc).__name__,
             'error':str(exc)[:8000],'rollback':rollback}
    job['failure']=failure
    persist_failure(job)
    return failure


def persist_failure(job):
    failure=job.get('failure')
    if not failure:return
    # Small standalone/legacy test jobs may not have a data directory.
    if job.get('data'):
        data=Path(job['data'])
        try:
            data.mkdir(parents=True,exist_ok=True)
            first=data/'update_failure_first.json'
            same_failure=False
            try:
                if first.stat().st_size<=65536:
                    initial=json.loads(first.read_text(encoding='utf-8'))
                    same_failure=(initial.get('created_at')==failure.get('created_at')
                                  and initial.get('work')==failure.get('work'))
            except (OSError,ValueError,AttributeError):pass
            if not first.exists() or same_failure:atomic_json(first,failure)
            atomic_json(data/'update_failure_latest.json',failure)
            if failure.get('winerror')==4551:
                blocked=[];policy_path=data/'update_policy_block.json'
                try:
                    if policy_path.stat().st_size<=65536:
                        previous=json.loads(policy_path.read_text(encoding='utf-8'))
                        blocked=previous.get('blocked_versions',[])
                        if not isinstance(blocked,list):blocked=[]
                        blocked=[v for v in blocked if isinstance(v,str) and len(v)<100]
                except (OSError,ValueError,AttributeError):pass
                version=failure['target_version']
                blocked=[v for v in blocked if v!=version]+[version]
                atomic_json(policy_path,dict(failure,blocked_versions=blocked[-16:]))
            from diagnostics import append_log
            append_log(data/'update.log',json.dumps(failure,ensure_ascii=False)+'\n')
        except OSError:pass  # Diagnostic storage must never prevent rollback.
    try:atomic_json(Path(job['work'])/'exe-job.json',job)
    except OSError:pass


def failure_message(job, exc):
    failure=job.get('failure',{})
    if failure.get('winerror')==4551:
        message=policy_block_message(failure.get('target_version','unknown'))
    else:message='EXE 업데이트 실패: '+str(exc)
    if failure.get('rollback')=='failed':message+=' 이전 버전 복구도 실패했습니다: '+failure.get('rollback_error','')
    return message

def fresh_env():
    env=dict(os.environ);env['PYINSTALLER_RESET_ENVIRONMENT']='1'
    return env


def check_feed(url,current,stop):
    try:
        info=json.loads(read_url(url,stop,65536))
        if info['app_id']!=APP_ID or info['protocol']!=1:raise UpdateError('EXE 버전의 업데이트 정보가 아닙니다.')
        https_url(info['url'])
        if len(info['sha256'])!=64 or any(c not in '0123456789abcdef' for c in info['sha256']):raise ValueError('checksum')
        if type(info['size']) is not int or not 0<info['size']<=MAX_SIZE:raise ValueError('size')
        return info if version_tuple(info['version'])>version_tuple(current) else None
    except (KeyError,ValueError,TypeError) as exc:raise UpdateError('EXE 업데이트 정보를 읽을 수 없습니다.') from exc


def stage_archive(archive,work,current,expected):
    archive,work=Path(archive),Path(work)
    if archive.stat().st_size!=expected['size'] or archive.stat().st_size>MAX_SIZE or digest(archive)!=expected['sha256']:
        raise UpdateError('EXE 다운로드 검증 실패')
    stage=work/'stage';stage.mkdir(exist_ok=False)
    try:
        with zipfile.ZipFile(archive) as z:
            entries=z.infolist()
            if len(entries)!=2 or {e.filename for e in entries}!={EXE_NAME,'release.json'}:raise UpdateError('EXE 파일 목록 오류')
            if sum(e.file_size for e in entries)>MAX_SIZE:raise UpdateError('EXE 압축 크기 초과')
            if any(stat.S_ISLNK(e.external_attr>>16) or e.flag_bits&1 for e in entries):raise UpdateError('링크/암호화 파일은 사용할 수 없습니다.')
            if z.getinfo('release.json').file_size>65536:raise UpdateError('EXE 정보 크기 초과')
            meta=json.loads(z.read('release.json'))
            if meta['app_id']!=APP_ID or meta['protocol']!=1 or meta['version']!=expected['version']:raise UpdateError('EXE 버전 정보 불일치')
            if version_tuple(meta['version'])<=version_tuple(current):raise UpdateError('새 버전이 아닙니다.')
            if set(meta['files'])!={EXE_NAME}:raise UpdateError('EXE 내부 목록 불일치')
            z.extract(EXE_NAME,stage)
            if digest(stage/EXE_NAME)!=meta['files'][EXE_NAME]:raise UpdateError('EXE 내부 검증 실패')
            with (stage/EXE_NAME).open('rb') as f:
                if f.read(2)!=b'MZ':raise UpdateError('Windows 실행 파일이 아닙니다.')
            atomic_json(stage/'release.json',meta)
        return meta
    except Exception:
        shutil.rmtree(stage,ignore_errors=True);raise


def download_update(info,work,stop,current,install,progress=lambda value:None):
    work=Path(work);work.mkdir(parents=True,exist_ok=True)
    archive=work/'download.zip'
    read_url(info['url'],stop,info['size'],archive,progress)
    if stop.is_set():raise UpdateError('업데이트를 취소했습니다.')
    return stage_archive(archive,work,current,info)


def prepare_job(install,data,work,meta):
    work=Path(work).resolve();target=Path(sys.executable).resolve()
    helper=work/'helper.exe';shutil.copy2(target,helper)
    job={'format':'exe','target':str(target),'data':str(Path(data).resolve()),'work':str(work),
         'source_version':VERSION,'created_at':datetime.now().astimezone().isoformat(),
         'version':meta['version'],'sha256':meta['files'][EXE_NAME],'status':'prepared'}
    atomic_json(work/'exe-job.json',job)
    return work/'exe-job.json'


def start_helper(job_path,recover=False):
    path=Path(job_path)
    return subprocess.Popen([str(path.parent/'helper.exe'),'--update-worker',str(path)]+(['--recover'] if recover else []),
        cwd=path.parent,env=fresh_env(),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=NO_WINDOW)


def replace_file(source,target):
    target=Path(target);temp=target.with_name(target.name+'.update-tmp')
    shutil.copy2(source,temp)
    deadline=time.monotonic()+30
    while True:
        try:os.replace(temp,target);return
        except PermissionError:
            if time.monotonic()>=deadline:raise
            time.sleep(.2)


def install(job,health=None):
    work,target=Path(job['work']),Path(job['target'])
    incoming=work/'stage'/EXE_NAME;backup=work/'backup.exe'
    stage='validate_target';error_path=target;backed_up=False
    try:
        if target.is_symlink() or any(p.is_symlink() for p in target.parents):raise UpdateError('EXE 설치 경로에 링크가 있습니다.')
        stage='validate_download';error_path=incoming
        if digest(incoming)!=job['sha256']:raise UpdateError('대기 중인 EXE가 변경됐습니다.')
        stage='backup';error_path=backup
        shutil.copy2(target,backup);backed_up=True
        job['status']='applying';atomic_json(work/'exe-job.json',job)
        stage='replace';error_path=target
        replace_file(incoming,target)
        stage='health_check'
        if health:health()
        else:
            result=work/'health.json';result.unlink(missing_ok=True)
            env=fresh_env();env['LOCALAPPDATA']=str(work/'health-data')
            subprocess.run([str(target),'--health-check',str(result)],env=env,cwd=target.parent,
                stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=NO_WINDOW,timeout=90,check=True)
            stage='health_report';error_path=result
            report=json.loads(result.read_text(encoding='utf-8'))
            if report.get('version')!=job['version'] or report.get('ok') is not True:raise UpdateError('새 EXE 실행 확인 실패')
    except Exception as exc:
        failure=record_failure(job,stage,error_path,exc,'pending' if backed_up else 'not_needed')
        if backed_up:
            try:
                replace_file(backup,target)
                job['status']='rolled_back';failure['rollback']='succeeded'
            except Exception as rollback_exc:
                failure['rollback']='failed';failure['rollback_error']=str(rollback_exc)[:8000]
                failure['rollback_winerror']=getattr(rollback_exc,'winerror',None)
            failure['rollback_at']=datetime.now().astimezone().isoformat()
            persist_failure(job)
        raise
    job['status']='complete';atomic_json(work/'exe-job.json',job)


def worker(job_path,recover=False):
    path=Path(job_path).resolve();job=json.loads(path.read_text(encoding='utf-8'))
    if job.get('format')!='exe' or Path(job['work']).resolve()!=path.parent:raise UpdateError('EXE 작업 경로 오류')
    data=Path(job['data']);lock=InstanceLock(data/'collector.lock');deadline=time.monotonic()+60
    while not lock.acquire():
        if time.monotonic()>deadline:
            atomic_json(data/'update_result.json',{'ok':False,'message':'도우미가 종료되지 않아 EXE 업데이트를 취소했습니다.'});return
        time.sleep(.2)
    try:
        try:
            if recover:
                replace_file(path.parent/'backup.exe',Path(job['target']))
                job['status']='rolled_back'
                if job.get('failure'):
                    job['failure'].update(rollback='succeeded',rollback_at=datetime.now().astimezone().isoformat())
                    persist_failure(job)
                atomic_json(path,job)
                result={'ok':False,'message':'중단된 EXE 업데이트를 이전 버전으로 복구했습니다.'}
            else:
                if job['status']!='prepared':raise UpdateError('이미 처리된 EXE 업데이트 작업입니다.')
                install(job);result={'ok':True,'message':'v'+job['version']+' EXE 업데이트 완료'}
        except Exception as exc:
            if not job.get('failure'):record_failure(job,'recovery' if recover else 'worker',job['target'],exc,'failed' if recover else 'not_needed')
            elif recover:
                job['failure'].update(rollback='failed',rollback_error=str(exc)[:8000],
                    rollback_winerror=getattr(exc,'winerror',None),rollback_at=datetime.now().astimezone().isoformat())
                persist_failure(job)
            result={'ok':False,'message':failure_message(job,exc),'failure':job.get('failure')}
        atomic_json(data/'update_result.json',result)
    finally:lock.release()
    if job.get('status')=='applying':return  # Never relaunch a failed rollback loop.
    try:
        subprocess.Popen([job['target']],cwd=Path(job['target']).parent,env=fresh_env(),
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=NO_WINDOW)
    except Exception as exc:
        record_failure(job,'relaunch',job['target'],exc)
        atomic_json(data/'update_result.json',{'ok':False,'message':failure_message(job,exc),'failure':job['failure']})


def recover_pending(data):
    target=Path(sys.executable).resolve()
    unreadable=False
    for path in (Path(data)/'updates').glob('release-*/exe-job.json'):
        try:
            job=json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(job,dict) or not isinstance(job.get('target'),str) or not job['target']:
                raise ValueError('Invalid update record')
            job_target=Path(job['target']).resolve()
        except (OSError,ValueError,TypeError):
            # Retain the damaged record for diagnosis. One historical record
            # must not prevent the installed app or another recovery starting.
            unreadable=True;continue
        if job_target==target and job.get('status')=='applying':
            # The saved old helper is independent of the installed executable.
            start_helper(path,recover=True);return True
    if unreadable:
        atomic_json(Path(data)/'update_result.json',{'ok':False,
            'message':'읽을 수 없는 이전 업데이트 기록이 있습니다. 기록은 보존했고 현재 버전을 실행합니다.'})
    return False


def cleanup_updates(data,target=None,keep=2,now=None):
    """Prune only completed jobs for this executable while its lock is held."""
    root=Path(data)/'updates'
    target=Path(target or sys.executable).resolve();now=time.time() if now is None else now
    def linked(path):
        return path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction())
    if linked(root):return
    completed=[]
    for work in root.glob('release-*'):
        if not work.is_dir() or linked(work):continue
        path=work/'exe-job.json'
        try:
            if path.is_file() and not linked(path):
                job=json.loads(path.read_text(encoding='utf-8'))
                if (job.get('format')=='exe' and Path(job.get('target','')).resolve()==target
                    and Path(job.get('work','')).resolve()==work.resolve()
                    and job.get('status') in {'complete','rolled_back'}):
                    completed.append((path.stat().st_mtime,work))
            elif not path.exists() and not (work/'job.json').exists() and now-work.stat().st_mtime>7*86400:
                # Abandoned staging is recognizable by our own validated manifest.
                meta=work/'stage'/'release.json'
                if not linked(work/'stage') and meta.is_file() and not linked(meta):
                    value=json.loads(meta.read_text(encoding='utf-8'))
                    if value.get('app_id')==APP_ID and set(value.get('files',{}))=={EXE_NAME}:
                        shutil.rmtree(work,ignore_errors=True)
        except (OSError,ValueError,TypeError):continue
    for index,(_,work) in enumerate(sorted(completed,reverse=True)):
        if index>=max(1,keep):
            shutil.rmtree(work,ignore_errors=True);continue
        # Retain the rollback binary and transaction record, not redundant copies.
        for name in ('download.zip','helper.exe','stage','health-data'):
            path=work/name
            if linked(path):continue
            try:
                if path.is_dir():shutil.rmtree(path)
                else:path.unlink(missing_ok=True)
            except OSError:pass  # A still-exiting helper will be retried next launch.
