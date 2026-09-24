"""Bounded restart of the exact game after a proven exit to Android HOME."""
import re
from collector import Halt
from run_control import checkpoint,active_clock,ResumeRecognition

GAME_PACKAGE='com.nns.genesis'
# Only screens for which existing start navigation has verified actions.
RECOVERY_READY={'main','menu','sleep','offline_reward','reward','equipment','exit_dialog'}

class GameRecovery:
    def __init__(self,device,vision,stop,verify_identity,log,progress=None,clock=None):
        self.device=device;self.vision=vision;self.stop=stop;self.verify_identity=verify_identity
        self.log=log;self.progress=progress or log;self.clock=clock or (lambda:active_clock(stop));self.attempts=0
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
        return not any(row[-1]==GAME_PACKAGE or row[-1].startswith(GAME_PACKAGE+':') for row in lines[1:])
    def recover(self):
        while True:
            try:return self._recover()
            except ResumeRecognition:
                self.check()  # Pause invalidates every pre-launch observation.
    def _recover(self):
        self.check();self.verify_identity()
        if self.device.package not in (None,GAME_PACKAGE):return False
        if self.device.current_package()==GAME_PACKAGE:return False
        home=self.component('android.intent.category.HOME').split('/')[0]
        if home==GAME_PACKAGE or not self.exited(home):return False
        if self.attempts>=2:raise Halt('게임 자동 재접속 2회 제한 / 반복 종료 원인을 확인해 주세요.')
        component=self.component('android.intent.category.LAUNCHER',GAME_PACKAGE)
        generation=getattr(self.stop,'generation',None)
        self.verify_identity();self.check()
        if not self.exited(home):return False
        self.device.capture_generation=generation
        self.check();self.attempts+=1
        self.progress(f'게임 종료 확인 / 다시 접속 중 ({self.attempts}/2)')
        try:
            raw=self.device.command(['shell','am','start','-W','-n',component],timeout=15).decode('utf-8',errors='replace')
        except ResumeRecognition:
            self.attempts-=1
            raise
        if re.search(r'Error:|Exception|Status:\s*(?!ok\b)\S+',raw,re.I):
            raise Halt('게임 앱 재실행 실패 / 뮤뮤 화면을 확인해 주세요.')
        self.device.last_capture=None
        deadline=self.clock()+90;stable=0;previous=None
        self.progress('게임 재접속 / 정상 화면을 기다리는 중')
        while self.clock()<deadline:
            self.check();self.verify_identity()
            foreground=self.device.current_package()
            if foreground not in (home,GAME_PACKAGE):raise Halt('재접속 중 다른 앱으로 바뀌어 중지했습니다.')
            if foreground==GAME_PACKAGE:
                screen=self.vision.recognize(self.device.raw_capture())
                stable=stable+1 if screen.state==previous else 1;previous=screen.state
                if stable>=2 and screen.state in RECOVERY_READY:
                    self.verify_identity();bound=self.device.bind_game(self.vision)
                    if self.device.package!=GAME_PACKAGE or bound.state not in RECOVERY_READY:
                        raise Halt('게임 재접속 후 정상 화면을 다시 확인하지 못했습니다.')
                    self.log('게임 재접속 확인 / 완료와 결과 미확인 기록을 유지합니다.')
                    return True
            else:stable=0;previous=None
            if self.stop.wait(min(1,max(0,deadline-self.clock()))):raise Halt('사용자가 중지했습니다.')
        raise Halt('게임 재접속 대기 시간 초과 / 로그인, 인증 또는 로딩 화면을 확인해 주세요.')
