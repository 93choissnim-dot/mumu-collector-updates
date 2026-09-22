"""Build and test the Windows-only, single-file distribution."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from version import VERSION

BASE=Path(__file__).resolve().parent
OUT=BASE/'exe_release'
NAME='창키 도우미'


def run(args,**kwargs):subprocess.run(args,check=True,**kwargs)


def build():
    if sys.platform!='win32':raise SystemExit('Build on Windows x64.')
    OUT.mkdir(exist_ok=True)
    common=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--windowed','--noupx',
        '--name',NAME,'--icon',str(BASE/'assets/chanki.ico'),
        '--add-data',str(BASE/'assets')+';assets','--collect-data','customtkinter','--hidden-import','pystray._win32',
        '--exclude-module','matplotlib','--exclude-module','pytest','--exclude-module','IPython',
        '--exclude-module','PyQt5','--exclude-module','PySide6','--exclude-module','scipy',
        '--exclude-module','pandas',str(BASE/'frozen_entry.py')]
    # Diagnose the folder build first, then produce the user's one-file EXE.
    run(common[:-1]+['--onedir','--distpath',str(BASE/'dist_folder'),common[-1]],cwd=BASE)
    smoke(BASE/'dist_folder'/NAME/(NAME+'.exe'),OUT/'folder-health.json')
    run(common[:-1]+['--onefile','--distpath',str(BASE/'dist_single'),common[-1]],cwd=BASE)
    built=BASE/'dist_single'/(NAME+'.exe')
    exe=OUT/'ChankiHelper.exe';shutil.copy2(built,exe)
    smoke(exe,OUT/'exe-health.json')
    meta={'app_id':'ChankiHelperExe','protocol':1,'version':VERSION,'files':{NAME+'.exe':sha(exe)}}
    archive=OUT/('ChankiHelper_v'+VERSION+'_update.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        z.write(exe,NAME+'.exe');z.writestr('release.json',json.dumps(meta,ensure_ascii=False))
    feed={'app_id':'ChankiHelperExe','protocol':1,'version':VERSION,
        'url':'https://github.com/93choissnim-dot/mumu-collector-updates/releases/download/v'+VERSION+'/'+archive.name,
        'sha256':sha(archive),'size':archive.stat().st_size,'notes':'가을맞이 0/10 실제 화면 인식과 이전 보류 해제, 패스 진입 안정화'}
    (OUT/'latest-exe.json').write_text(json.dumps(feed,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'checksums.txt').write_text(sha(exe)+'  ChankiHelper.exe\n'+sha(archive)+'  '+archive.name+'\n',encoding='ascii')
    run([sys.executable,str(BASE/'validate_exe_windows.py'),str(exe),str(archive)],cwd=BASE)


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def smoke(exe,result):
    env=dict(os.environ,LOCALAPPDATA=str(OUT/'smoke-data'),PYINSTALLER_RESET_ENVIRONMENT='1')
    # No Python in PATH, no system PYTHONHOME/PYTHONPATH: invoke just the EXE.
    env['PATH']=str(Path(os.environ['SystemRoot'])/'System32')
    env.pop('PYTHONHOME',None);env.pop('PYTHONPATH',None)
    try:
        run([str(exe),'--health-check',str(result),'--full-ui-checks'],cwd=exe.parent,env=env,timeout=120)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        error=OUT/'smoke-data'/'MumuCollector'/'exe_error.log'
        if error.exists():print(error.read_text(encoding='utf-8'),flush=True)
        for path in [result.with_suffix('.progress.json'),result.with_suffix('.threads.log')]:
            if path.exists():print(path.name,path.read_text(encoding='utf-8'),flush=True)
        raise
    report=json.loads(result.read_text(encoding='utf-8'))
    assert report['ok'] and report['frozen'] and report['version']==VERSION and report['bits']==64 and report['full_ui_checks'] and report['vector_rendering_ui'] and report['game_theme_ui'] and report['improvements_ui'] and report['taskbar_ui'] and report['start_navigation'],report


if __name__=='__main__':build()
