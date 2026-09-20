"""Windows tray callbacks enqueue commands; never access Tk from a tray thread."""
import os
from pathlib import Path
from PIL import Image


class Tray:
    def __init__(self,events):
        import pystray
        self.events=events
        def send(kind):return lambda icon,item:events.put((kind,None))
        self.icon=pystray.Icon('ChankiHelper',Image.open(Path(__file__).parent/'assets/chanki.ico'),
            '창키 도우미',pystray.Menu(
                pystray.MenuItem('도우미 열기',send('tray_open'),default=True),
                pystray.MenuItem('일시중지 / 재시작',send('tray_pause')),
                pystray.MenuItem('수령 중지',send('tray_stop')),
                pystray.MenuItem('종료',send('tray_exit'))))
        def ready(icon):
            icon.visible=True
            events.put(('tray_ready',None))
        self.icon.run_detached(setup=ready)
    def status(self,text):self.icon.title=('창키 도우미 — '+text)[:120]
    def close(self):self.icon.stop()
