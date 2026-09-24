"""Windows Authenticode signing. No trust-store or policy changes are made."""
import hashlib
import json
from pathlib import Path,PureWindowsPath
import re
import shutil
import subprocess
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parent

def require_trusted(report):
    if (report.get('status')!='Valid' or report.get('signature_type')!='Authenticode'
        or report.get('algorithm')!='1.2.840.113549.1.1.1' or report.get('timestamp') is not True
        or not re.fullmatch('[0-9A-Fa-f]{40}',report.get('thumbprint',''))):
        raise ValueError('A valid embedded RSA signature and timestamp are required: '+str(report.get('status')))
    return report

def sign_arguments(config):
    tool=config.get('signtool');url=config.get('timestamp_url','')
    if not isinstance(tool,str) or not tool or urlsplit(url).scheme not in {'http','https'} or not urlsplit(url).netloc:
        raise ValueError('Configure the Windows SDK SignTool and RFC3161 timestamp URL first.')
    thumb=config.get('thumbprint');dlib=config.get('dlib');metadata=config.get('metadata')
    if thumb and not dlib and not metadata and re.fullmatch('[0-9A-Fa-f]{40}',thumb):
        selector=['/sha1',thumb]
    elif not thumb and isinstance(dlib,str) and dlib and isinstance(metadata,str) and metadata:
        selector=['/dlib',dlib,'/dmdf',metadata]
    else:raise ValueError('Configure exactly one issued certificate or authenticated cloud signing profile.')
    return [tool,'sign','/fd','SHA256','/td','SHA256','/tr',url,*selector]

def signature_report(path):
    run=subprocess.run(['pwsh','-NoProfile','-File',str(ROOT/'signature_report.ps1'),'-Path',str(Path(path).resolve())],
        check=True,capture_output=True,encoding='utf-8-sig')
    return json.loads(run.stdout)

class Signer:
    def __init__(self,config):self.command=sign_arguments(config)
    def verify(self,path):
        report=require_trusted(signature_report(path))
        # /pa verifies the trusted Authenticode chain; /all checks every signature;
        # /tw also reports absent timestamps. Warnings are nonzero and rejected.
        subprocess.run([self.command[0],'verify','/pa','/all','/tw',str(path)],check=True,capture_output=True)
        return report
    def __call__(self,path):
        report=signature_report(path)
        if report.get('status')=='NotSigned':
            subprocess.run([*self.command,str(path)],check=True,capture_output=True)
        # Do not hide tampering, expired/untrusted signatures or ECC by replacing them.
        return self.verify(path)

def stage_binaries(toc,destination,signer):
    destination=Path(destination).resolve();result=[];inventory={};seen=set()
    for name,source,kind in toc:
        path=PureWindowsPath(name)
        if path.is_absolute() or path.drive or '..' in path.parts or ':' in name:
            raise ValueError('Unsafe binary destination: '+name)
        normalized=path.as_posix();key=normalized.casefold()
        if key in seen:raise ValueError('Duplicate binary destination: '+name)
        seen.add(key)
        src=Path(source)
        with src.open('rb') as stream:is_pe=stream.read(2)==b'MZ'
        if not is_pe:
            if path.suffix.lower() in {'.exe','.dll','.pyd'}:raise ValueError('Invalid PE file: '+name)
            result.append((name,source,kind));continue
        target=destination/normalized;target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():raise ValueError('Signing stage must be fresh: '+name)
        shutil.copyfile(src,target);signer(target)
        inventory[normalized]=target.read_bytes();result.append((name,str(target),kind))
    return result,inventory

def verify_payload(actual,expected):
    if set(actual)!=set(expected):raise ValueError('Packed binary inventory differs from signed input.')
    if any(actual[name]!=expected[name] for name in expected):
        raise ValueError('A binary changed after signing.')

def verify_packed(exe,inventory):
    from PyInstaller.archive.readers import CArchiveReader
    archive=CArchiveReader(str(exe));actual={}
    for name in archive.toc:
        raw=archive.extract(name)
        if isinstance(raw,bytes) and raw.startswith(b'MZ'):actual[PureWindowsPath(name).as_posix()]=raw
    verify_payload(actual,inventory)
    return {name:hashlib.sha256(raw).hexdigest() for name,raw in inventory.items()}
