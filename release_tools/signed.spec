# PyInstaller 6.22.3, Windows only. Sign binary copies before embedding them.
import json,os,sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files
tools=Path(SPECPATH).resolve();sys.path.insert(0,str(tools))
from signing import Signer,stage_binaries
source=Path(os.environ['CHANKI_SIGN_SOURCE']).resolve()
stage=Path(os.environ['CHANKI_SIGN_STAGE']).resolve()
config=json.loads(Path(os.environ['CHANKI_SIGN_CONFIG']).read_text(encoding='utf-8'))
signer=Signer(config)
a=Analysis([str(source/'frozen_entry.py')],pathex=[str(source)],
    binaries=[],datas=[(str(source/'assets'),'assets')]+collect_data_files('customtkinter'),
    hiddenimports=['pystray._win32'],hookspath=[],hooksconfig={},runtime_hooks=[],
    excludes=['matplotlib','pytest','IPython','PyQt5','PySide6','scipy','pandas'],noarchive=False)
a.binaries,binaries=stage_binaries(a.binaries,stage/'binaries',signer)
a.datas,data_binaries=stage_binaries(a.datas,stage/'data',signer)
if set(binaries)&set(data_binaries):raise ValueError('Conflicting binary destinations')
binaries.update(data_binaries)
(stage/'inventory.json').write_text(json.dumps({name:str((stage/('binaries' if name not in data_binaries else 'data')/name).resolve()) for name in binaries}),encoding='utf-8')
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,a.binaries,a.datas,[],name='ChankiHelper',debug=False,
    bootloader_ignore_signals=False,strip=False,upx=False,console=False,icon=str(source/'assets/chanki.ico'))
