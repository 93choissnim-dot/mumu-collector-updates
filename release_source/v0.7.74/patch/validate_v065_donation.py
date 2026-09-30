"""Guild donation through real route, durable ledger and pre-input guards."""
from pathlib import Path
import tempfile,threading,unittest
import cv2,numpy as np
from collector import Halt
from daily_state import DailyLedger,korea_day,DAILY_STEPS
from extra_collector import ExtraCollector
from vision import Match,Screen
from run_control import ResumeRecognition
import validate_daily_execution as donor_cases


class GuildDonationTests(unittest.TestCase):
    def route(self,*,remaining=3,free=True,evidence='reward',delay=0,resume=False,
              reject=False,stop=False,old_excluded=False,pending=False,late_free_reward=False,late_after_paid=False,free_counter_delay=0):
        counter=donor_cases.DonationEvidenceTests();counter.setUp()
        class Device:
            clock=0;state='menu';paid=0;free_clicks=0;due=None;reads=0;interrupted=False;late_shown=False;late_overlay=False
            left=remaining;free_available=free;current=None
            def capture(d):
                d.clock+=.08;d.reads+=1
                if getattr(d,'free_due',None) is not None and d.clock>=d.free_due:
                    d.left-=1;d.free_due=None
                    if not d.left:d.state='menu'
                if resume and d.paid and not d.interrupted:
                    d.interrupted=True;raise ResumeRecognition()
                if d.due is not None and d.clock>=d.due:
                    d.due=None
                    if evidence=='reward':d.state='reward'
                    elif evidence=='counter':d.left-=1;d.state='menu' if not d.left else 'donate'
                if late_free_reward and d.free_clicks and (d.paid==1 if late_after_paid else not d.paid) and not d.late_shown and d.state=='donate':
                    d.late_reads=getattr(d,'late_reads',0)+1
                    if d.late_reads>=3:d.state='reward';d.late_shown=True;d.late_overlay=True
                if d.state=='menu':keys=['guild_donated'] if not d.left else ['guild_donate_open']
                elif d.state=='reward':keys=['reward_close']
                else:
                    keys=['donate_close','donate_free' if d.free_available else 'donate_50']
                    if (reject or stop) and not d.free_available:
                        d.paid_reads=getattr(d,'paid_reads',0)+1
                        if d.paid_reads>=3:
                            if reject:keys=['donate_close']
                            if stop:d.stop.set()
                state='reward' if d.state=='reward' else 'daily_guild_menu' if d.state=='menu' else 'daily_donate'
                centers={'guild_donate_open':(100,100),'donate_free':(480,470),'donate_50':(518,470),'donate_close':(690,50),'guild_donated':(100,100),'reward_close':(640,520)}
                d.current=Screen(state,{(k if k=='reward_close' else 'daily_'+k):Match(k,1,0,centers[k]) for k in keys})
                return cv2.cvtColor(counter.frame(d.left),cv2.COLOR_GRAY2BGR)
            def click(d,point):
                assert not d.stop.is_set()
                if d.state=='menu':assert point==(100,100);d.state='donate'
                elif d.state=='reward':
                    assert point==(640,520)
                    if not d.late_overlay:d.left-=1
                    d.late_overlay=False;d.state='menu' if not d.left else 'donate'
                elif point==(690,50):d.state='menu'
                elif d.free_available:
                    assert point==(480,470);d.free_clicks+=1;d.free_available=False
                    if free_counter_delay:d.free_due=d.clock+free_counter_delay;d.expected_free_at=d.free_due
                    else:d.left-=1
                    if not d.left:d.state='menu'
                else:
                    assert point==(518,470);d.paid+=1
                    if d.paid==1:d.first_paid_at=d.clock
                    if evidence!='unchanged':d.due=d.clock+delay
        d=Device();d.stop=threading.Event()
        class Recognizer:
            def recognize(self,image):return d.current
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path=Path(tmp)/'daily.json'
            c=ExtraCollector(d,Recognizer(),d.stop,lambda _:None)
            c.now=lambda:d.clock;c.pause=lambda n:setattr(d,'clock',d.clock+n)
            c.daily_ledger=DailyLedger(ledger_path);c.daily_ident='synthetic';c.daily_day=korea_day()
            c.daily_task='daily_guild';c.daily_step='donation';c.daily_reward_seen=False;c.daily_performed=False
            c.daily_guild_page=lambda:c.daily_wait({'daily_guild_menu','daily_donate'})
            c.daily_main=lambda:None
            if old_excluded:
                for step in (*DAILY_STEPS['daily_guild'],'_complete'):c.daily_mark(step)
                c.daily_checkpoint('done',excluded=True,reason='유료 길드 기부 제외 / 루비 사용 안 함')
            if pending:c.daily_checkpoint('uncertain',pending='donate_50',values={'donation_paid':1})
            error=None
            try:
                if old_excluded:c.collect_daily('daily_guild')
                else:c.daily_guild_donation()
            except ResumeRecognition:
                c.daily_ledger=DailyLedger(ledger_path);c.forget_observations()
                try:c.daily_guild_donation()
                except Halt as exc:error=exc
            except Halt as exc:error=exc
            d.detail=c.daily_detail('donation');d.saved=c.daily_ledger.snapshot(c.daily_ident,c.daily_day).get('daily_guild',{})
            return d,c.daily_done('donation'),error

    def test_free_then_all_remaining_paid_donations(self):
        d,done,error=self.route()
        self.assertIsNone(error);self.assertTrue(done);self.assertEqual((d.free_clicks,d.paid,d.left),(1,2,0))
        self.assertIsNone(d.detail.get('pending'));self.assertFalse(d.detail.get('excluded'))

    def test_all_remaining_paid_donations_when_free_already_used(self):
        d,done,error=self.route(remaining=3,free=False,delay=2)
        self.assertIsNone(error);self.assertTrue(done);self.assertEqual((d.free_clicks,d.paid,d.left),(0,3,0))

    def test_continue_until_game_completion_instead_of_old_three_attempt_cap(self):
        d,done,error=self.route(remaining=5,free=False)
        self.assertIsNone(error);self.assertTrue(done);self.assertEqual((d.paid,d.left),(5,0))

    def test_counter_change_can_confirm_without_reward_overlay(self):
        d,done,error=self.route(free=False,evidence='counter')
        self.assertIsNone(error);self.assertTrue(done);self.assertEqual((d.paid,d.left),(3,0))

    def test_unchanged_button_never_replays_payment(self):
        d,done,error=self.route(free=False,evidence='unchanged')
        self.assertIsNotNone(error);self.assertFalse(done);self.assertEqual(d.paid,1)
        self.assertEqual(d.detail.get('pending'),'donate_50');self.assertLess(d.clock,30)

    def test_post_dispatch_resume_and_restart_do_not_repeat_payment(self):
        d,done,error=self.route(free=False,evidence='unchanged',resume=True)
        self.assertIsNotNone(error);self.assertFalse(done);self.assertEqual(d.paid,1)
        self.assertEqual(d.detail.get('pending'),'donate_50')

    def test_changed_cost_before_input_sends_no_payment(self):
        d,done,error=self.route(free=False,reject=True)
        self.assertIsNotNone(error);self.assertFalse(done);self.assertEqual(d.paid,0)
        self.assertIsNone(d.detail.get('pending'))

    def test_stop_prevents_payment(self):
        d,done,error=self.route(free=False,stop=True)
        self.assertIsNotNone(error);self.assertFalse(done);self.assertEqual(d.paid,0)

    def test_old_excluded_completion_reopens_only_donation(self):
        d,done,error=self.route(remaining=2,free=False,old_excluded=True)
        self.assertIsNone(error);self.assertTrue(done);self.assertEqual(d.paid,2)
        self.assertFalse(d.detail.get('excluded'))
        for step in DAILY_STEPS['daily_guild']:self.assertEqual(d.saved[step],'done')

    def test_late_free_reward_does_not_confirm_a_later_unresolved_payment(self):
        d,done,error=self.route(evidence='unchanged',late_free_reward=True)
        self.assertIsNotNone(error);self.assertFalse(done);self.assertTrue(d.late_shown)
        self.assertEqual((d.free_clicks,d.paid),(1,1));self.assertEqual(d.detail.get('pending'),'donate_50')

    def test_paid_input_waits_for_free_counter_change(self):
        d,done,error=self.route(free_counter_delay=4)
        self.assertIsNone(error);self.assertTrue(done);self.assertEqual(d.paid,2)
        self.assertGreaterEqual(d.first_paid_at,d.expected_free_at)

    def test_delayed_free_reward_after_paid_dispatch_cannot_confirm_payment(self):
        d,done,error=self.route(evidence='unchanged',late_free_reward=True,late_after_paid=True)
        self.assertIsNotNone(error);self.assertFalse(done);self.assertTrue(d.late_shown)
        self.assertEqual((d.free_clicks,d.paid,d.left),(1,1,2))
        self.assertEqual(d.detail.get('pending'),'donate_50')
        self.assertEqual(d.saved.get('donation_verified',0),0)

    def test_excluded_record_with_pending_input_is_not_reopened(self):
        d,done,error=self.route(free=False,old_excluded=True,pending=True)
        self.assertEqual(d.paid,0);self.assertEqual(d.detail.get('pending'),'donate_50')

    def test_existing_uncertain_payment_remains_pending(self):
        d,done,error=self.route(free=False,pending=True)
        self.assertIsNotNone(error);self.assertFalse(done);self.assertEqual(d.paid,0)
        self.assertEqual(d.detail.get('pending'),'donate_50')

    def test_final_badge_resolves_prior_payment_without_spending(self):
        d,done,error=self.route(remaining=0,free=False,pending=True)
        self.assertIsNone(error);self.assertTrue(done);self.assertEqual(d.paid,0)
        self.assertIsNone(d.detail.get('pending'))


if __name__=='__main__':unittest.main()
