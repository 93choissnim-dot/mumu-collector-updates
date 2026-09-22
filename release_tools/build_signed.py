"""Build a signed candidate. Never changes public releases or update feeds."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from signing import Signer,verify_packed

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    # Check missing signing prerequisites before spending time or changing files.
    config=json.loads(args.config.read_text(encoding='utf-8'));signer=Signer(config)
    if sys.platform!='win32':raise SystemExit('Run on Windows with an issued signing identity.')
    import PyInstaller
    if PyInstaller.__version__!='6.22.3':raise SystemExit('Use the reviewed PyInstaller version 6.22.3.')
    source=args.source.resolve();output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    stage=output/'signed-input';stage.mkdir()
    env=dict(os.environ,CHANKI_SIGN_SOURCE=str(source),CHANKI_SIGN_STAGE=str(stage),CHANKI_SIGN_CONFIG=str(args.config.resolve()))
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--distpath',str(output/'dist'),
        '--workpath',str(output/'work'),str(Path(__file__).with_name('signed.spec'))],env=env,check=True)
    exe=output/'dist/ChankiHelper.exe'
    inputs=json.loads((stage/'inventory.json').read_text(encoding='utf-8'))
    inventory={name:Path(path).read_bytes() for name,path in inputs.items()}
    # Revalidate all staged inputs, then verify their exact packed bytes.
    for path in inputs.values():signer.verify(Path(path))
    packed=verify_packed(exe,inventory)
    outer=signer(exe)
    verify_packed(exe,inventory)
    smoke_env=dict(os.environ,LOCALAPPDATA=str(output/'health-data'),PYINSTALLER_RESET_ENVIRONMENT='1')
    health=output/'health.json'
    subprocess.run([str(exe),'--health-check',str(health),'--full-ui-checks'],env=smoke_env,check=True,timeout=180)
    status=json.loads(health.read_text(encoding='utf-8'))
    if status.get('ok') is not True or status.get('frozen') is not True:raise ValueError('Signed EXE health check failed.')
    report={'signature':outer,'sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),
            'binary_sha256':packed,'version':status['version'],'health_ok':True,
            'smart_app_control_enforcement_tested':False}
    (output/'signed-candidate.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Signed candidate validated. Smart App Control enforcement and update compatibility remain release gates.')

if __name__=='__main__':main()
