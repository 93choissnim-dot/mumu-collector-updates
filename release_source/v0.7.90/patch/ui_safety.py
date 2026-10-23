"""Explicit cancellation of collection, repeat schedules and passive recovery."""


class SafetyUI:
    def stop_all(self):
        # Cancel both controls before touching widgets or disk. A watcher may
        # already hold the device lane while a collection worker waits for it.
        self.stop.set()
        self.game_watch.enable(False)
        self.config['game_watch']=False
        self.watch_value.set(False)
        self.pause_allowed=False
        self.pause_button.configure(text='일시중지',state='disabled')
        self.watch_status.configure(text='꺼짐')
        self.next_at=None
        for state in self.fleet_states.values():state['next_at']=None
        self.countdown.set('예약 없음')
        message='완전 중지 / 작업과 게임 자동 복구를 멈췄습니다.'
        self.finish_text=message
        self.status.set('완전 중지 중 / 게임 자동 복구 꺼짐' if self.busy() else message)
        self.log(message+' 자동 복구는 스위치를 다시 켜야 시작됩니다.')
        try:
            self.save()
        except OSError as exc:
            # A failed setting write must never undo either cancellation.
            message='완전 중지됨 / 자동 복구 끄기 설정 저장 실패: '+str(exc)
            self.status.set(message)
            self.log(message)
            return False
        return True
