"""Assemble the reviewed 0.7.10 source from a pinned released base and patch."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

root=Path(__file__).resolve().parent
manifest=json.loads((root/'patch_manifest.json').read_text(encoding='utf-8'))
archive=Path('MumuCollector_v'+manifest['base_version']+'.zip')
assert hashlib.sha256(archive.read_bytes()).hexdigest()==manifest['base_sha256'],'Base archive changed'
destination=Path('source').resolve()
with zipfile.ZipFile(archive) as z:
    for item in z.infolist():
        assert (destination/item.filename).resolve().is_relative_to(destination),'Unsafe archive path'
    assert z.testzip() is None,'Corrupt source archive'
    z.extractall(destination)
source=destination/('MumuCollector_v'+manifest['version'])
(destination/('MumuCollector_v'+manifest['base_version'])).rename(source)
for name,expected in manifest['files'].items():
    target=(source/name).resolve()
    assert target.is_relative_to(source),'Unsafe patch path'
    payload=root/'patch'/name
    assert hashlib.sha256(payload.read_bytes()).hexdigest()==expected,'Patch changed: '+name
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(payload,target)
print('Reviewed source prepared:',manifest['version'],len(manifest['files']),'patch files')
