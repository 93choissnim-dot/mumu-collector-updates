"""Bounded restart of the exact game after a proven exit to Android HOME."""
import re
import time
from startup_notice import download_confirm
from network_notice import detect_network_notice,network_confirm
from collector import Halt
from run_control import checkpoint,active_clock,ResumeRecognition

GAME_PACKAGE='com.nns.genesis'
GAME_PACKAGES=frozenset({GAME_PACKAGE,'com.nns.genesis.onestore'})
# Only screens for which existing start navigation has verified actions.
RECOVERY_READY={'main','menu','sleep','offline_reward','reward','equipment','exit_dialog'}

class GameRecovery:
    def __init__(self,device,vision,stop,verify_identity,log,progress=None,clock=None):
        self.device=device;self.vision=vision;self.stop=stop;self.verify_identity=verify_identity
        self.log=log;self.progress=progress or log;self.clock=clock or (lambda:active_clock(stop));self.attempts=0;self.target=None;self.observed_package=None;self.startup={}
    def check(self):
        checkpoint(self.stop)
        if self.stop.is_set():raise Halt('사용자가 중지했습니다.')
    def component(self,category,package=None):
        args=['shell','cmd','package','resolve-activity','--brief','-a','android.intent.action.MAIN','-c',category]
        if package:args+=['-p',package]
        raw=self.device.command(args,timeout=5).decode('utf-8',errors='replace')
        candidates=re.findall(r'^([A-Za-z][\w]*(?:\.[\w]+)+/[\w.$]+)\s*$',raw,re.M)
        if len(candidates)!=1:raise Halt('게임 재접속 대상을 확정하지 못했습니다. 화면을 확인해 주세요.')
        component=candidates[0]
        if package and component.split('/')[0]!=package:raise Halt('게임 재접속 앱이 달라 중지했습니다.')
        return component
    def exited(self,home):
        if self.device.current_package()!=home:return False
        raw=self.device.command(['shell','ps','-A'],timeout=5).decode('utf-8',errors='replace')
        lines=[line.split() for line in raw.splitlines() if line.strip()]
        if not lines or 'PID' not in lines[0] or not any(k in lines[0] for k in ('NAME','CMD','CMDLINE','COMMAND')):
            raise Halt('게임 실행 상태를 확인하지 못해 자동 재접속을 보류합니다.')
        return not any(any(row[-1]==p or row[-1].startswith(p+':') for p in GAME_PACKAGES) for row in lines[1:])
    def recover(self):
        while True:
            try:return self._recover()
            except ResumeRecognition:
                self.check()  # Pause invalidates every pre-launch observation.
    def _recover(self):
        self.check();self.verify_identity()
        if self.device.package is not None and self.device.package not in GAME_PACKAGES:return False
        foreground=self.device.current_package()
        if foreground in GAME_PACKAGES:
            self.observed_package=foreground;self.device.package=foreground
            if self.startup.get('pending') and self.startup.get('target')==foreground:
                self.target=foreground
                return self.wait_ready(self.startup['home'])
            notice=detect_network_notice(self.device.raw_capture())
            if notice is not None:
                if self.startup.get('network_unconfirmed'):
                    raise Halt('네트워크 재접속 결과 미확인 / 같은 확인 입력을 반복하지 않습니다.')
                if notice.confirm is None:raise Halt('네트워크 오류창의 활성 확인 버튼을 기다립니다.')
                self.target=foreground;home=self.component('android.intent.category.HOME').split('/')[0]
                self.startup.clear();self.startup.update(pending=True,target=foreground,home=home,confirmed=set(),deadline=self.clock()+90)
                return self.wait_ready(home)
            if self.startup.get('network_unconfirmed') and self.startup.get('target')==foreground:
                self.target=foreground;self.startup.update(pending=True,deadline=self.clock()+90)
                return self.wait_ready(self.startup['home'])
            return False
        self.target=self.device.package
        if self.target is None:
            installed=[]
            for package in sorted(GAME_PACKAGES):
                raw=self.device.command(['shell','pm','path',package],timeout=5).decode('utf-8',errors='replace')
                if any(line.startswith('package:') for line in raw.splitlines()):installed.append(package)
            if len(installed)!=1:raise Halt('설치된 게임 판본을 확정하지 못했습니다. 게임을 직접 열고 뮤뮤 연결을 확인해 주세요.')
            self.target=installed[0]
        home=self.component('android.intent.category.HOME').split('/')[0]
        if home in GAME_PACKAGES or not self.exited(home):return False
        if self.attempts>=2:raise Halt('게임 자동 재접속 2회 제한 / 반복 종료 원인을 확인해 주세요.')
        component=self.component('android.intent.category.LAUNCHER',self.target)
        generation=getattr(self.stop,'generation',None)
        self.verify_identity();self.check()
        if not self.exited(home):return False
        if self.device.current_package()!=home:return False
        self.device.capture_generation=generation
        self.check();self.attempts+=1
        network_unconfirmed=self.startup.get('network_unconfirmed',False)
        self.startup.clear();self.startup.update(pending=True,target=self.target,home=home,confirmed={'network'} if network_unconfirmed else set(),deadline=self.clock()+90)
        if network_unconfirmed:self.startup['network_unconfirmed']=True
        self.progress(f'게임 종료 확인 / 다시 접속 중 ({self.attempts}/2)')
        try:
            raw=self.device.command(['shell','am','start','-W','-n',component],timeout=15).decode('utf-8',errors='replace')
        except ResumeRecognition:
            self.attempts-=1
            raise
        if re.search(r'Error:|Exception|Status:\s*(?!ok\b)\S+',raw,re.I):
            raise Halt('게임 앱 재실행 실패 / 뮤뮤 화면을 확인해 주세요.')
        self.device.last_capture=None
        return self.wait_ready(home)
    def confirm_startup(self,kind,point):
        self.check();self.verify_identity()
        if self.device.current_package()!=self.target:return False
        generation=getattr(self.stop,'generation',None)
        image=self.device.raw_capture()
        if kind=='download':fresh=download_confirm(image)
        elif kind=='network':fresh=network_confirm(image)
        else:
            screen=self.vision.recognize(image)
            match=screen.matches.get('offline_confirm') if screen.state=='offline_reward' else None
            fresh=match.center if match else None
        if fresh is None or abs(fresh[0]-point[0])+abs(fresh[1]-point[1])>10:return False
        self.check();self.verify_identity()
        if self.device.current_package()!=self.target:return False
        self.device.package=self.target;self.device.size=tuple(image.shape[1::-1])
        self.device.last_capture=time.monotonic();self.device.capture_generation=generation
        self.startup.setdefault('confirmed',set()).add(kind)
        if kind=='network':self.startup['network_unconfirmed']=True
        from adb_device import InputNotSent
        try:self.device.click(fresh)
        except (ResumeRecognition,InputNotSent):
            self.startup['confirmed'].discard(kind)
            if kind=='network':self.startup.pop('network_unconfirmed',None)
            raise
        self.log('재접속 / '+{'download':'다운로드 안내 확인','offline':'오프라인 보상 확인','network':'네트워크 오류 확인'}[kind])
        return True
    def wait_ready(self,home):
        deadline=self.startup.setdefault('deadline',self.clock()+90);stable=0;previous=None
        confirmed=self.startup.setdefault('confirmed',set())
        self.progress('게임 재접속 / 정상 화면을 기다리는 중')
        while self.clock()<deadline:
            self.check();self.verify_identity()
            foreground=self.device.current_package()
            if foreground not in (home,self.target):raise Halt('재접속 중 다른 앱으로 바뀌어 중지했습니다.')
            if foreground==self.target:
                image=self.device.raw_capture();screen=self.vision.recognize(image)
                notice=detect_network_notice(image)
                if notice is not None:
                    if notice.confirm and 'network' not in confirmed:self.confirm_startup('network',notice.confirm)
                    stable=0;previous=None
                    if self.stop.wait(1):self.check()
                    continue
                download=download_confirm(image)
                if download is not None and 'download' not in confirmed:
                    if self.confirm_startup('download',download):
                        confirmed.add('download');deadline=self.clock()+300;self.startup['deadline']=deadline
                        self.progress('게임 데이터 다운로드 / 최대 5분 대기')
                    stable=0;previous=None
                    if self.stop.wait(1):self.check()
                    continue
                if screen.state=='offline_reward':
                    match=screen.matches.get('offline_confirm')
                    if match and 'offline' not in confirmed and self.confirm_startup('offline',match.center):confirmed.add('offline')
                    stable=0;previous=None
                    if self.stop.wait(1):self.check()
                    continue
                stable=stable+1 if screen.state==previous else 1;previous=screen.state
                if stable>=2 and screen.state in RECOVERY_READY:
                    self.verify_identity();bound=self.device.bind_game(self.vision)
                    if self.device.package!=self.target or bound.state not in RECOVERY_READY:
                        raise Halt('게임 재접속 후 정상 화면을 다시 확인하지 못했습니다.')
                    self.startup['pending']=False;self.startup.pop('network_unconfirmed',None);self.observed_package=self.target
                    self.log('게임 재접속 확인 / 완료와 결과 미확인 기록을 유지합니다.')
                    return True
            else:
                stable=0;previous=None
                if self.startup.get('network_unconfirmed') and self.exited(home):
                    return self._recover()
            if self.stop.wait(min(1,max(0,deadline-self.clock()))):raise Halt('사용자가 중지했습니다.')
        self.startup['pending']=False
        raise Halt('게임 재접속 대기 시간 초과 / 로그인, 인증 또는 로딩 화면을 확인해 주세요.')
