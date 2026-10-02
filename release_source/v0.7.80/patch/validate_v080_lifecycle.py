"""Cross-route receipt, unsent reservation and recognition cooldown regressions."""
import tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from action_state import ActionState
from adb_device import InputNotSent
from collector import Halt,ScreenChanged
from daily_state import DailyLedger,korea_day
from vision import Screen,Match
import validate_autumn as autumn
import validate_collection as rooms
import validate_daily_execution as daily

class LifecycleTests(unittest.TestCase):
    def room(self,room='farm'):
        c,d,clock,_=rooms.CollectionRegression().run_flow()
        c.now=clock.monotonic;d.state=room;c.trace.task=room
        return c,d
    def test_unsent_facility_reservation_does_not_block_next_run(self):
        for room in ('farm','wood','mine'):
            c,d=self.room(room)
            click=d.click;d.click=lambda _:(_ for _ in ()).throw(InputNotSent('local rejection'))
            with self.assertRaises(InputNotSent):c.collect_room(room,c.screen())
            self.assertFalse(c.action_state.pending(room))
            self.assertEqual(c.action_state.get(room)['input_resolution']['kind'],'not_sent')
            d.click=click;c.collect_room(room,c.screen())
            self.assertEqual(d.claims[room],1)
            self.assertEqual(c.results[room],'collected')
    def test_facility_late_screen_change_retires_only_untransmitted_intent(self):
        c,d=self.room();reserve=c.action_state.reserve
        def change(*a,**kw):reserve(*a,**kw);d.initial_modes['farm']='empty'
        c.action_state.reserve=change
        try:c.collect_room('farm',c.screen())
        except ScreenChanged:pass
        self.assertEqual(d.claims['farm'],0)
        self.assertFalse(c.action_state.pending('farm'))
        self.assertEqual(c.action_state.get('farm')['input_resolution']['kind'],'not_sent')
    def test_facility_transport_uncertainty_preserves_intent(self):
        c,d=self.room();d.click=lambda _:(_ for _ in ()).throw(Halt('lost acknowledgement'))
        with self.assertRaises(Halt):c.collect_room('farm',c.screen())
        self.assertTrue(c.action_state.pending('farm'))
    def test_autumn_unsent_intent_is_not_inherited(self):
        d,c=autumn.RouteTests().collector();click=d.click
        def reject(p):
            if d.state=='autumn' and p==(889,494):raise InputNotSent('local rejection')
            click(p)
        d.click=reject
        c.cycle(['autumn'])
        self.assertFalse(c.action_state.pending('autumn'))
        self.assertEqual(c.action_state.get('autumn')['input_resolution']['kind'],'not_sent')
        d.click=click;c.cycle(['autumn'])
        self.assertEqual(d.claims,1)
    def test_autumn_reward_records_before_first_close_guard(self):
        d,c=autumn.RouteTests().collector(reward=True,stuck=True);screen=d.screen;reads=0
        def vanish():
            nonlocal reads
            if d.state=='reward':
                reads+=1
                if reads>=3:d.state='autumn'
            return screen()
        d.screen=vanish
        self.assertEqual(c.cycle(['autumn']),{'autumn':'collected'})
        self.assertEqual(d.claims,1)
        self.assertFalse(c.action_state.pending('autumn'))
        self.assertEqual(c.action_state.get('autumn')['input_resolution']['source'],'free_reward_confirmed')
    def test_facility_reward_confirmation_survives_close_capture_failure(self):
        c,d=self.room();capture=d.capture;reads=0
        def crash():
            nonlocal reads
            if d.claims['farm']:
                reads+=1
                if reads>=4:raise Halt('capture lost after reward')
                d.clock.now+=.1
                return Screen('reward',{'reward_close':Match('reward_close',1,0,(640,520))})
            return capture()
        d.capture=crash
        with self.assertRaises(Halt):c.collect_room('farm',c.screen())
        self.assertFalse(c.action_state.pending('farm'))
        self.assertEqual(c.action_state.get('farm')['input_resolution']['source'],'free_reward_confirmed')

    def test_store_proof_survives_capture_loss_before_first_close_guard(self):
        from validate_v075_store import StoreRecoveryTests
        h=StoreRecoveryTests();self.addCleanup(h.doCleanups)
        c,d=h.flow();capture=d.capture;reads=0
        def crash():
            nonlocal reads
            if d.index==1:
                reads+=1
                if reads>=4:raise Halt('capture lost before close guard')
            return capture()
        d.capture=crash
        with self.assertRaises(Halt):c.free_store_step('cube_ad')
        new,nd=h.resumed(c)
        new.free_store_step('cube_ad')
        self.assertTrue(new.daily_done('cube_ad'))
        self.assertFalse(new.daily_detail().get('pending'))
        self.assertEqual(nd.clicks,[])

class CooldownTests(unittest.TestCase):
    def test_general_recognition_block_expires_but_pending_survives_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'actions.json';s=ActionState(path,'account')
            with patch('time.time',return_value=1000):
                s.reserve('ranking');s.fail('ranking','entry','unknown','missing');s.fail('ranking','entry','unknown','missing')
                self.assertTrue(s.blocked('ranking'))
            with patch('time.time',return_value=1301):
                restarted=ActionState(path,'account')
                self.assertFalse(restarted.blocked('ranking'))
                self.assertTrue(restarted.pending('ranking'))
    def daily(self):
        h=daily.DailyExecutionTests();h.setUp();self.addCleanup(h.tearDown)
        c=h.c;c.daily_recover=Mock();return c
    def test_daily_recognition_rechecks_after_cooldown_and_can_finish(self):
        c=self.daily()
        def fail():raise Halt('missing free key')
        with patch('time.time',return_value=1000):
            c.daily_run_step('treasure','보물',fail);c.daily_run_step('treasure','보물',fail)
            c.daily_run_step('treasure','보물',lambda:c.daily_mark('treasure'))
            self.assertFalse(c.daily_done('treasure'))
        with patch('time.time',return_value=1301):
            c.daily_ledger=DailyLedger(c.daily_ledger.path)
            c.daily_run_step('treasure','보물',lambda:c.daily_mark('treasure'))
            self.assertTrue(c.daily_done('treasure'))
    def test_expired_recognition_hold_is_not_reblocked_by_journal_result(self):
        from session_workflow import held_reason
        s=ActionState();s.update('ranking',version=__import__('version').VERSION,blocked=True,retry_after=1000)
        records={'daily_store':{'_steps':{'ruby':{'status':'blocked','retry_after':1000}}}}
        with patch('time.time',return_value=2000):
            self.assertEqual(held_reason('ranking','deferred',s,{}),'')
            self.assertEqual(held_reason('daily_store','deferred',s,records),'')
    def test_legacy_recognition_timestamp_can_expire_but_invalid_time_cannot(self):
        from recognition_backoff import recognition_hold
        with patch('time.time',return_value=2000):
            self.assertFalse(recognition_hold({'updated_at':'1970-01-01T00:16:40+00:00'}))
            for data in ({},{'updated_at':'bad'},{'updated_at':'1970-01-01T00:16:40'},
                         {'retry_after':True},{'retry_after':float('nan')},{'retry_after':'1000'}):
                self.assertTrue(recognition_hold(data))

    def test_daily_block_with_uncertain_payment_never_rearmed_by_age(self):
        c=self.daily();c.daily_task='daily_guild';c.daily_step='donation'
        c.daily_checkpoint('blocked',pending='donate_50',failures=2,retry_after=1000)
        with patch('time.time',return_value=2000):
            c.daily_run_step('donation','기부',lambda:self.fail('uncertain payment rearmed'))
        self.assertEqual(c.daily_detail()['pending'],'donate_50')

if __name__=='__main__':unittest.main()
