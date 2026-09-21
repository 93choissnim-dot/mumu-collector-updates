"""Replay a locally supplied capture corpus. Images never need to be published."""
import argparse
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
from vision import Vision


def replay(manifest):
    manifest=Path(manifest);cases=json.loads(manifest.read_text(encoding='utf-8'))['cases']
    if not cases:raise ValueError('Empty capture corpus')
    vision=Vision();results=[]
    for case in cases:
        path=(manifest.parent/case['file']).resolve();raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=case['sha256']:raise AssertionError('Capture changed: '+case['name'])
        image=cv2.imdecode(np.frombuffer(raw,np.uint8),1)
        if image is None:raise AssertionError('Unreadable capture: '+case['name'])
        screen=vision.recognize(image)
        assert screen.state==case['state'],(case['name'],screen.state,case['state'])
        assert all(k in screen.matches for k in case.get('required',[])),(case['name'],'required marker missing')
        assert not any(k in screen.matches for k in case.get('forbidden',[])),(case['name'],'forbidden marker accepted')
        results.append({'name':case['name'],'state':screen.state,'ok':True})
    return {'ok':True,'captures':len(results),'results':results}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('manifest');parser.add_argument('--output')
    args=parser.parse_args();report=json.dumps(replay(args.manifest),ensure_ascii=False,indent=2)
    if args.output:Path(args.output).write_text(report,encoding='utf-8')
    print(report)
