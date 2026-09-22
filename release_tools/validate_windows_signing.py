"""Real Windows signature checks; no certificate or policy installation."""
import json
import os
from pathlib import Path
import subprocess
import sys
from signing import Signer,require_trusted,signature_report

def main():
    unsigned=Path(sys.argv[1]).resolve()
    report=signature_report(unsigned)
    if report['status']!='NotSigned':raise AssertionError('Expected the pinned v0.7.47 unsigned EXE')
    try:require_trusted(report)
    except ValueError:pass
    else:raise AssertionError('Unsigned published EXE passed the signing gate')
    sdk=Path(os.environ['ProgramFiles(x86)'])/'Windows Kits/10/bin'
    candidates=sorted(sdk.glob('*/x64/signtool.exe'),reverse=True)
    if not candidates:raise RuntimeError('Windows SDK SignTool missing')
    signer=Signer({'signtool':str(candidates[0]),'thumbprint':'A'*40,'timestamp_url':'http://timestamp.digicert.com'})
    # verify() uses the real Microsoft Windows trust engine and SignTool. It
    # never uses the placeholder thumbprint or invokes a signing operation.
    trusted=signer.verify(Path(sys.executable))
    changed=unsigned.parent/'tampered-python.exe'
    payload=bytearray(Path(sys.executable).read_bytes());payload[4096]^=1;changed.write_bytes(payload)
    try:signer.verify(changed)
    except (ValueError,subprocess.CalledProcessError):pass
    else:raise AssertionError('Tampered signed EXE passed verification')
    print(json.dumps({'unsigned_release_rejected':True,'trusted_python_verified':trusted['status'],
                      'tampered_exe_rejected':True,'trusted_signing_identity_available':False}))

if __name__=='__main__':main()
