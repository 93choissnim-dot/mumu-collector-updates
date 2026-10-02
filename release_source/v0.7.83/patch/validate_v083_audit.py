"""Deterministic device-boundary simulations for the final route audit."""
import unittest
from unittest.mock import Mock
from collector import Halt,ScreenChanged
from vision import Screen,Match
from validate_v072_free_daily import RouteHarness

class NavigationAudit(RouteHarness,unittest.TestCase):
    def test_all_daily_entries_recheck_if_target_arrives_before_touch(self):
        for key,target in [('store','free_store'),('summon','free_summon_character'),
                           ('dungeon','daily_dungeons'),('guild','daily_guild_menu'),('pass','daily_pass_ad')]:
            with self.subTest(route=key):
                c,d=self.make('daily_store','ruby',[Screen('main',{'top_pass':Match('top_pass',1,0,(599,28))}),Screen(target,{})])
                original=c.trace.event;changed=False
                def event(name,**kw):
                    nonlocal changed
                    original(name,**kw)
                    if name=='input' and not changed:d.index=1;changed=True
                c.trace.event=event
                try:out=c.daily_open(key,{target})
                except ScreenChanged as exc:self.fail(str(exc))
                self.assertEqual(out.state,target);self.assertEqual(d.clicks,[])
    def test_dungeon_card_arrival_during_final_guard_uses_current_room(self):
        listing=Screen('daily_dungeons',{'daily_card_stone':Match('daily_card_stone',1,0,(400,250))})
        c,d=self.make('daily_dungeons','stone',[listing,Screen('daily_room_stone',{})])
        original=c.trace.event
        def event(name,**kw):
            original(name,**kw)
            if name=='input':d.index=1
        c.trace.event=event
        try:out=c.daily_find_dungeon('stone')
        except ScreenChanged as exc:self.fail(str(exc))
        self.assertEqual(out.state,'daily_room_stone');self.assertEqual(d.clicks,[])
    def test_recovery_accepts_list_arrival_before_close(self):
        room=Screen('daily_room_stone',{'daily_d_close':Match('daily_d_close',1,0,(900,30))})
        c,d=self.make('daily_dungeons','stone',[room,Screen('daily_dungeons',{})])
        original=c.trace.event
        def event(name,**kw):
            original(name,**kw)
            if name=='input':d.index=1
        c.trace.event=event
        try:c.daily_recover()
        except ScreenChanged as exc:self.fail(str(exc))
        self.assertEqual(d.clicks,[])

class StoreAudit(RouteHarness,unittest.TestCase):
    def flow(self,key):
        tab='general' if key=='cube_ad' else 'currency'
        return self.make('daily_store',key,[
            self.screen('free_store',**{'open_'+key:(350,240),'selected_'+tab:(100,80)}),
            self.screen('free_store_confirm_'+key,**{'confirm_'+key:(480,387),'dialog_close':(631,86)}),
            Screen('reward',{'reward_close':Match('reward_close',1,0,(640,520))}),
            self.screen('free_store',**{'done_'+key:(350,240),'selected_'+tab:(100,80)})])
    def test_transient_final_guard_rejection_does_not_fail_free_purchase(self):
        for key in ('ruby','ruby_ad','cube_ad'):
            for rejected in ('free_open_'+key,'free_confirm_'+key):
                with self.subTest(key=key,rejected=rejected):
                    c,d=self.flow(key);event=c.trace.event;capture=c.screen;armed=False;injected=False
                    def trace(name,**kw):
                        nonlocal armed
                        event(name,**kw)
                        if name=='input' and kw.get('action')==rejected and not injected:armed=True
                    def screen():
                        nonlocal armed,injected
                        actual=capture()
                        if armed:armed=False;injected=True;return Screen('unknown',{})
                        return actual
                    c.trace.event=trace;c.screen=screen
                    try:c.free_store_step(key)
                    except ScreenChanged as exc:self.fail(str(exc))
                    self.assertTrue(injected);self.assertTrue(c.daily_done(key))
                    self.assertEqual([p for _,p in d.clicks],[(350,240),(480,387),(640,520)])
                    self.assertFalse(c.daily_detail().get('pending'))
    def test_lost_purchase_acknowledgement_is_never_replayed(self):
        for key in ('ruby','ruby_ad','cube_ad'):
            with self.subTest(key=key):
                c,d=self.flow(key);click=d.click
                def lost(point):
                    before=d.index;click(point)
                    if before==1:raise Halt('lost acknowledgement')
                d.click=lost
                with self.assertRaises(Halt):c.free_store_step(key)
                self.assertEqual(len(d.clicks),2);self.assertTrue(c.daily_detail().get('pending'))

class DelayMatrix(RouteHarness,unittest.TestCase):
    flow=StoreAudit.flow
    def test_purchase_delay_and_capture_latency_matrix(self):
        for key in ('ruby','ruby_ad','cube_ad'):
            for latency in (.05,.3,1.5,3.):
                for delay in (0.,5.,25.,75.):
                    with self.subTest(key=key,latency=latency,delay=delay):
                        c,d=self.flow(key);capture=d.capture;click=d.click;recognize=c.vision.recognize;ready_at=0
                        def slow_capture():
                            image=capture();d.clock+=latency-.1;return image
                        def delayed_click(point):
                            nonlocal ready_at
                            before=d.index;click(point)
                            if before==1:ready_at=d.clock+delay
                        def delayed_observation(image):
                            if int(image[0,0,0])==2 and d.clock<ready_at:return Screen('unknown',{})
                            return recognize(image)
                        d.capture=slow_capture;d.click=delayed_click;c.vision.recognize=delayed_observation
                        c.free_store_step(key)
                        self.assertTrue(c.daily_done(key));self.assertFalse(c.daily_detail().get('pending'))
                        self.assertEqual([p for _,p in d.clicks],[(350,240),(480,387),(640,520)])
    def test_persistent_guard_rejection_is_bounded_and_sends_no_purchase(self):
        for key in ('ruby','ruby_ad','cube_ad'):
            c,d=self.flow(key);event=c.trace.event;capture=c.screen;armed=False
            def trace(name,**kw):
                nonlocal armed
                event(name,**kw)
                if name=='input' and kw.get('action')=='free_confirm_'+key:armed=True
            def screen():
                nonlocal armed
                actual=capture()
                if armed:armed=False;return Screen('unknown',{})
                return actual
            c.trace.event=trace;c.screen=screen
            with self.assertRaises(ScreenChanged):c.free_store_step(key)
            self.assertEqual(len(d.clicks),1);self.assertFalse(c.daily_detail().get('pending'))
            self.assertLess(d.clock,20)
    def test_stop_before_each_store_touch_blocks_that_touch(self):
        for key in ('ruby','ruby_ad','cube_ad'):
            for boundary in (0,1,2):
                with self.subTest(key=key,boundary=boundary):
                    c,d=self.flow(key);event=c.trace.event
                    def trace(name,**kw):
                        event(name,**kw)
                        if name=='input' and d.index==boundary:c.stop.set()
                    c.trace.event=trace
                    with self.assertRaises(Halt):c.free_store_step(key)
                    self.assertEqual(len(d.clicks),boundary)

class NavigationLimits(RouteHarness,unittest.TestCase):
    def test_already_at_each_destination_never_leaves_it(self):
        for key,target in [('store','free_store'),('summon','free_summon_character'),
                           ('dungeon','daily_dungeons'),('guild','daily_guild_menu'),('pass','daily_pass_ad')]:
            c,d=self.make('daily_store','ruby',[Screen(target,{})])
            self.assertEqual(c.daily_open(key,{target}).state,target);self.assertEqual(d.clicks,[])
    def test_changed_destination_never_retries_transport_error(self):
        for key,target in [('store','free_store'),('summon','free_summon_character'),('dungeon','daily_dungeons'),('guild','daily_guild_menu')]:
            c,d=self.make('daily_store','ruby',[Screen('main',{}),Screen(target,{})]);click=d.click
            def lost(point):click(point);raise Halt('lost acknowledgement')
            d.click=lost
            with self.assertRaises(Halt):c.daily_open(key,{target})
            self.assertEqual(len(d.clicks),1)

class CombatBoundaryMatrix(unittest.TestCase):
    def test_cold_loading_deadline_and_unknown_frame_matrix(self):
        import numpy as np
        import validate_combat_start as fixture
        for black in (True,False):
            for delay in (0,5,18,21,40,57,61,90):
                with self.subTest(black=black,delay=delay):
                    h=fixture.CombatStartTests();h.setUp();self.addCleanup(h.doCleanups)
                    c=h.c;clear=fixture.screen('daily_clear','battle_leave')
                    def screen():
                        state=fixture.screen('unknown') if h.clock<delay else clear if not c.device.click.called else h.room
                        c.last_screen=state
                        c.last_image=np.full((540,960,3),0 if black else 80,np.uint8)
                        return state
                    c.screen=screen
                    if delay<(60 if black else 20):
                        returned,result=c.daily_combat({h.room.state},accept_clear=True,
                            on_result=lambda:c.daily_confirm_input(c.daily_combat_evidence))
                        self.assertTrue(result);self.assertEqual(returned.state,h.room.state)
                        self.assertFalse(c.daily_detail().get('pending'));self.assertEqual(c.device.click.call_count,1)
                    else:
                        with self.assertRaises(Halt):c.daily_combat({h.room.state},accept_clear=True)
                        self.assertTrue(c.daily_detail().get('pending'));c.device.click.assert_not_called()
                        self.assertLess(h.clock,61 if black else 21)

class StoreHistoryAudit(RouteHarness,unittest.TestCase):
    def inherited(self,key,age=1,stamp=None,action=None):
        from datetime import timedelta
        from daily_state import ManualQuestLedger,korea_now
        c,d=self.make('daily_store',key,[self.screen('free_store',**{'done_'+key:(350,240),'selected_currency':(100,80)})])
        c.daily_ledger=ManualQuestLedger(c.daily_ledger.path)
        c.daily_checkpoint('uncertain',pending=action or 'free_confirm_'+key)
        detail=c.daily_detail()
        detail['input_request']['requested_at']=stamp if stamp is not None else (korea_now()-timedelta(days=age)).isoformat()
        c.daily_ledger.update(c.daily_ident,c.daily_task,{'_steps':{key:detail}})
        return c,d
    def test_prior_day_request_is_not_confirmed_by_today_sold_out(self):
        for key in ('ruby','ruby_ad'):
            with self.subTest(key=key):
                c,d=self.inherited(key);old=c.daily_detail()['input_request']['id']
                c.free_store_step(key)
                self.assertTrue(c.daily_done(key));self.assertEqual(d.clicks,[])
                record=next(x for x in c.daily_detail()['input_history'] if x['request']['id']==old)
                self.assertFalse(record['resolution']['confirmed'])
                self.assertEqual(record['resolution']['source'],'expired_daily_allowance')
    def test_unverifiable_origin_cannot_be_completed_by_current_marker(self):
        for key in ('ruby','ruby_ad'):
            for fields in ({'age':-1},{'stamp':'bad'},{'stamp':'2026-10-01T23:00:00'},{'action':'donate_50'}):
                with self.subTest(key=key,fields=fields):
                    c,d=self.inherited(key,**fields);old=c.daily_detail()['input_request']
                    with self.assertRaises(Halt):c.free_store_step(key)
                    self.assertFalse(c.daily_done(key));self.assertEqual(d.clicks,[])
                    self.assertEqual(c.daily_detail()['input_request'],old)
    def test_current_day_known_store_request_can_complete_without_purchase(self):
        for key in ('ruby','ruby_ad'):
            c,d=self.inherited(key,age=0);c.free_store_step(key)
            self.assertTrue(c.daily_done(key));self.assertEqual(d.clicks,[])
            self.assertTrue(c.daily_detail()['input_resolution']['confirmed'])

class DailyHistoryAudit(RouteHarness,unittest.TestCase):
    def test_pass_and_donation_current_markers_do_not_confirm_yesterday(self):
        from datetime import timedelta
        from daily_state import ManualQuestLedger,korea_now
        cases=[('daily_pass',k,'pass_'+k+'_active','daily_pass_'+k,'pass_'+k+suffix)
               for k in ('ad','keys','gear') for suffix in ('_done','_purchase')]
        cases+=[('daily_guild','donation',k,'daily_guild_menu','guild_donated') for k in ('donate_free','donate_50')]
        for task,key,pending,page,marker in cases:
            with self.subTest(task=task,key=key,marker=marker,pending=pending):
                state=Screen(page,{'daily_'+marker:Match('daily_'+marker,1,0,(100,100))})
                c,d=self.make(task,key,[state]);c.daily_ledger=ManualQuestLedger(c.daily_ledger.path)
                c.daily_checkpoint('uncertain',pending=pending)
                detail=c.daily_detail();detail['input_request']['requested_at']=(korea_now()-timedelta(days=1)).isoformat()
                c.daily_ledger.update(c.daily_ident,task,{'_steps':{key:detail}})
                if task=='daily_pass':c.daily_pass_tab(key,90,{page})
                else:c.daily_guild_donation()
                self.assertTrue(c.daily_done(key));self.assertEqual(d.clicks,[])
                self.assertFalse(c.daily_detail()['input_resolution']['confirmed'])
    def test_current_purchase_only_pass_does_not_confirm_unseen_claim(self):
        c,d=self.make('daily_pass','ad',[Screen('daily_pass_ad',{'daily_pass_ad_purchase':Match('daily_pass_ad_purchase',1,0,(100,100))})])
        c.daily_checkpoint('uncertain',pending='pass_ad_active')
        c.daily_pass_tab('ad',90,{'daily_pass_ad'})
        self.assertTrue(c.daily_done('ad'));self.assertEqual(d.clicks,[])
        self.assertFalse(c.daily_detail()['input_resolution']['confirmed'])

class EditionBindingAudit(unittest.TestCase):
    def test_both_supported_editions_bind_every_known_daily_state(self):
        import threading,numpy as np
        from adb_device import AdbDevice,DAILY_RECOVERY_STATES
        for package in ('com.nns.genesis','com.nns.genesis.onestore'):
            for state in sorted(DAILY_RECOVERY_STATES):
                with self.subTest(package=package,state=state):
                    device=AdbDevice(Mock(stop=threading.Event()),'127.0.0.1:16384')
                    device.current_package=Mock(return_value=package)
                    device.raw_capture=Mock(return_value=np.zeros((540,960,3),np.uint8))
                    vision=Mock();vision.recognize.return_value=Screen(state,{})
                    try:bound=device.bind_game(vision)
                    except Halt as exc:self.fail(str(exc))
                    self.assertEqual(bound.state,state);self.assertEqual(device.package,package)
    def test_unknown_onestore_and_unrelated_app_do_not_gain_binding(self):
        import threading,numpy as np
        from adb_device import AdbDevice
        for package,state in [('com.nns.genesis.onestore','unknown'),('com.browser.app','free_store')]:
            d=AdbDevice(Mock(stop=threading.Event()),'127.0.0.1:16384')
            d.current_package=Mock(return_value=package);d.raw_capture=Mock(return_value=np.zeros((540,960,3),np.uint8))
            v=Mock();v.recognize.return_value=Screen(state,{})
            with self.assertRaises(Halt):d.bind_game(v)
            self.assertIsNone(d.package)

if __name__=='__main__':unittest.main()
