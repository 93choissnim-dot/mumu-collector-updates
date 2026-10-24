"""Fresh-run reconciliation and acknowledged navigation regressions."""
import unittest
from unittest.mock import Mock
import numpy as np
from validate_v072_free_daily import RouteHarness
from vision import Screen,Match
from collector import Halt

class FreshFreeTests(RouteHarness,unittest.TestCase):
    def test_new_run_rechecks_remaining_free_summon_and_keeps_old_uncertainty(self):
        s=self.screen
        c,d=self.make('daily_summon','pet',[
            s('free_summon_pet',1,summon=(230,500),identity_pet=(840,125)),
            s('free_summon_pet',0,identity_pet=(840,125))])
        c.daily_checkpoint('uncertain',pending='free_summon',before_count=1)
        old=c.daily_detail()['input_request']['id']
        self.assertTrue(hasattr(c,'arm_free_resume'))
        c.arm_free_resume();c.free_summon_step('pet')
        self.assertTrue(c.daily_done('pet'));self.assertEqual(len(d.clicks),1)
        history=c.daily_detail()['input_history']
        archived=next(x for x in history if x['request']['id']==old)
        self.assertFalse(archived['resolution']['confirmed'])

    def test_new_run_permission_cannot_replay_new_failed_input(self):
        s=self.screen
        c,d=self.make('daily_summon','pet',[s('free_summon_pet',1,summon=(230,500),identity_pet=(840,125))],stuck=True)
        c.daily_checkpoint('uncertain',pending='free_summon',before_count=1)
        self.assertTrue(hasattr(c,'arm_free_resume'))
        c.arm_free_resume()
        with self.assertRaises(Halt):c.free_summon_step('pet')
        c.arm_free_resume()
        with self.assertRaises(Halt):c.free_summon_step('pet')
        self.assertEqual(len(d.clicks),1)

    def test_missing_free_label_never_retires_history(self):
        c,d=self.make('daily_summon','pet',[self.screen('free_summon_pet',1,identity_pet=(840,125))])
        c.daily_checkpoint('uncertain',pending='free_summon',before_count=1)
        self.assertTrue(hasattr(c,'arm_free_resume'));c.arm_free_resume()
        with self.assertRaises(Halt):c.free_summon_step('pet')
        self.assertEqual(d.clicks,[]);self.assertTrue(c.daily_detail()['pending'])

class CubeRecognitionTests(unittest.TestCase):
    def frame(self,counter='card_zero'):
        from free_daily_vision import FreeDailyVision
        from pathlib import Path
        v=FreeDailyVision(Path(__file__).parent/'assets')
        im=np.full((540,960,3),60,np.uint8)
        for k,x,y in [('store_header',18,13),('store_home',905,14),('card_cube',736,315),(counter,758,288)]:
            tile=v.refs[k];h,w=tile.shape[:2];im[y:y+h,x:x+w]=tile
        im[251:278,73:155]=[140,180,205]
        return v,im
    def test_visible_exhausted_cube_card_is_done(self):
        v,im=self.frame();state,m=v.recognize(im)
        self.assertEqual(state,'free_store');self.assertIn('daily_free_done_cube_ad',m)
        self.assertNotIn('daily_free_open_cube_ad',m)
    def test_available_or_unreadable_cube_is_not_done(self):
        for counter in ['card_one',None]:
            v,im=self.frame(counter or 'card_zero')
            if counter is None:im[288:308,758:840]=0
            self.assertNotIn('daily_free_done_cube_ad',v.recognize(im)[1])

class NavigationTests(RouteHarness,unittest.TestCase):
    def test_final_sleep_pass_does_not_wake_already_sleeping_game(self):
        c,d=self.make('daily_dungeons','return',[Screen('sleep',{})])
        self.assertEqual(c.cycle([],True),{})
        self.assertEqual(d.clicks,[])

    def daily(self,state,**keys):
        return Screen(state,{'daily_'+k:Match('daily_'+k,1,0,p) for k,p in keys.items()})
    def test_relic_close_reobserves_after_ignored_first_click(self):
        room=self.daily('daily_relic',relic_close=(790,86));menu=self.daily('daily_guild_menu')
        c,d=self.make('daily_guild','relic',[room,room,menu])
        self.assertTrue(hasattr(c,'daily_close_relic'));c.daily_close_relic()
        self.assertEqual(d.index,2);self.assertEqual(len(d.clicks),2)
    def test_relic_close_is_bounded(self):
        c,d=self.make('daily_guild','relic',[self.daily('daily_relic',relic_close=(790,86))],stuck=True)
        self.assertTrue(hasattr(c,'daily_close_relic'))
        with self.assertRaises(Halt):c.daily_close_relic()
        self.assertEqual(len(d.clicks),3)
    def test_free_key_retries_only_literal_free_with_zero_entries(self):
        page='daily_room_treasure'
        free=self.daily(page,d_free_1=(744,440),d_count_0=(680,392))
        enter=self.daily(page,d_enter=(744,440))
        c,d=self.make('daily_dungeons','treasure',[free,free,enter])
        self.assertTrue(hasattr(c,'daily_claim_free_key'))
        returned=c.daily_claim_free_key(page)
        self.assertIn('daily_d_enter',returned.matches);self.assertEqual(len(d.clicks),2)
    def test_unreadable_free_key_counter_sends_nothing(self):
        page='daily_room_treasure'
        c,d=self.make('daily_dungeons','treasure',[self.daily(page,d_free_1=(744,440))])
        self.assertTrue(hasattr(c,'daily_claim_free_key'))
        with self.assertRaises(Halt):c.daily_claim_free_key(page)
        self.assertEqual(d.clicks,[])
    def test_boss_overlay_before_sleep_is_observed_until_menu_returns(self):
        menu=Screen('menu',{'sleep_menu':Match('sleep_menu',1,0,(838,501))})
        c,d=self.make('daily_dungeons','return',[menu,Screen('sleep',{})])
        recognize=c.vision.recognize;reads=[0]
        def observed(im):
            reads[0]+=1
            return Screen('unknown',{}) if 3<=reads[0]<=6 else recognize(im)
        c.vision.recognize=observed
        self.assertTrue(hasattr(c,'restore_sleep_after_work'));c.restore_sleep_after_work()
        self.assertEqual(d.index,1);self.assertEqual(len(d.clicks),1)

class DonationTests(RouteHarness,unittest.TestCase):
    def test_previous_day_paid_pending_does_not_block_current_free_donation(self):
        from datetime import datetime,timedelta
        from daily_state import KST
        def page(state,**keys):return Screen(state,{'daily_'+k:Match(k,1,0,p) for k,p in keys.items()})
        c,d=self.make('daily_guild','donation',[
            page('daily_guild_menu',guild_donate_open=(100,100)),
            page('daily_donate',donate_free=(480,470),donate_close=(690,50)),
            page('daily_guild_menu',guild_donated=(100,100))])
        c.daily_guild_page=lambda:c.daily_wait({'daily_guild_menu','daily_donate'})
        c.daily_checkpoint('uncertain',pending='donate_50',values={'donation_paid':1})
        entry=c.daily_ledger.data[c.daily_ident][c.daily_day]['daily_guild']['_steps']['donation']
        entry['input_request']['requested_at']=(datetime.now(KST)-timedelta(days=1)).isoformat()
        try:c.daily_guild_donation()
        except Halt:pass
        self.assertTrue(c.daily_done('donation'))
        self.assertEqual([p for _,p in d.clicks],[(100,100),(480,470)])
        self.assertFalse(c.daily_detail()['input_history'][0]['resolution']['confirmed'])

class ReviewOrderTests(unittest.TestCase):
    def test_review_precedes_only_sleep_pass(self):
        import run_review,threading
        self.assertTrue(hasattr(run_review,'run_reviewed_cycle'))
        c=Mock();c.daily_ledger=None;c.action_state.get.return_value={};c.action_state.blocked.return_value=False
        c.manual_retry_tasks=set();calls=[]
        c.results={};c.claim_counts={'farm':2}
        def execute(tasks,restore=False):
            calls.append((list(tasks),restore))
            if not tasks:c.results={};c.claim_counts={}
            return {'farm':'failed' if len(calls)==1 else 'collected'} if tasks else {}
        result=run_review.run_reviewed_cycle(c,['farm'],execute,lambda _:None,threading.Event())
        self.assertEqual(calls,[(['farm'],False),(['farm'],False),([],True)])
        self.assertEqual(result,{'farm':'collected'})
        self.assertEqual(c.results,{'farm':'collected'})
        self.assertEqual(c.claim_counts,{'farm':2})


class RegularFreeResumeTests(unittest.TestCase):
    def facility(self,room='mine',**kwargs):
        from validate_collection import CollectionRegression
        c,d,clock,_=CollectionRegression().run_flow(**kwargs)
        c.now=clock.monotonic;d.state=room
        return c,d

    def test_current_version_pending_retries_each_facility_and_keeps_uncertain_history(self):
        for room in ('farm','wood','mine'):
            with self.subTest(room=room):
                c,d=self.facility(room);c.action_state.reserve(room)
                old=c.action_state.pending(room)['id']
                c.arm_regular_free_resume()
                c.collect_room(room,c.screen())
                self.assertEqual(d.claims[room],1)
                self.assertEqual(c.results[room],'collected')
                history=c.action_state.get(room)['input_history']
                prior=next(x for x in history if x['request']['id']==old)
                self.assertFalse(prior['resolution']['confirmed'])
                self.assertEqual(prior['resolution']['source'],'fresh_run_free_claim_retry')

    def test_retry_permission_cannot_rearm_a_new_failure_during_same_run(self):
        c,d=self.facility(post={'mine':'ready'});c.action_state.reserve('mine')
        c.arm_regular_free_resume();c.collect_room('mine',c.screen())
        new=c.action_state.pending('mine')['id']
        c.arm_regular_free_resume();c.collect_room('mine',c.screen())
        self.assertEqual(d.claims['mine'],1)
        self.assertEqual(c.action_state.pending('mine')['id'],new)
        self.assertEqual(c.results['mine'],'deferred')

    def test_unknown_current_button_preserves_old_request_without_click(self):
        c,d=self.facility(initial_modes={'mine':'wait'});c.action_state.reserve('mine')
        old=c.action_state.pending('mine').copy();c.arm_regular_free_resume()
        c.collect_room('mine',c.screen())
        self.assertEqual(d.claims['mine'],0)
        self.assertEqual(c.action_state.pending('mine'),old)

    def test_empty_current_button_reconciles_without_click(self):
        c,d=self.facility(initially_empty=True);c.action_state.reserve('mine')
        c.arm_regular_free_resume();c.collect_room('mine',c.screen())
        self.assertEqual(d.claims['mine'],0)
        self.assertFalse(c.action_state.pending('mine'))

    def test_paid_or_unknown_action_is_never_armed(self):
        c,d=self.facility()
        for task,slot in [('daily_guild','donate_50'),('daily_dungeons','enter'),('training','claim'),('mine','upgrade')]:
            c.action_state.reserve(task,slot)
        c.arm_regular_free_resume()
        for task,slot in [('daily_guild','donate_50'),('daily_dungeons','enter'),('training','claim'),('mine','upgrade')]:
            self.assertFalse(c.can_retry_regular_free(task,slot))

    def test_retry_permission_cannot_cross_account_or_ledger(self):
        from action_state import ActionState
        c,d=self.facility();c.action_state.reserve('mine');c.arm_regular_free_resume()
        original=c.action_state;c.action_state=ActionState()
        c.action_state.update('mine',**original.get('mine'))
        self.assertFalse(c.can_retry_regular_free('mine'))
        c.action_state=original;c.action_state.scope='other'
        self.assertFalse(c.can_retry_regular_free('mine'))

    def test_next_run_retries_the_persisted_failure(self):
        c,d=self.facility(post={'mine':'ready'});c.action_state.reserve('mine')
        c.arm_regular_free_resume();c.collect_room('mine',c.screen())
        fresh,device=self.facility();fresh.action_state=c.action_state
        fresh.arm_regular_free_resume();fresh.collect_room('mine',fresh.screen())
        self.assertEqual(device.claims['mine'],1)
        self.assertEqual(fresh.results['mine'],'collected')


    def test_all_extra_free_slots_retry_current_pending(self):
        from validate_extra import Device
        from extra_collector import ExtraCollector
        for task,slot in [('ranking','claim'),('excavation','claim'),('worldboss','cerberus'),('worldboss','kraken'),('worldboss','void')]:
            with self.subTest(task=task,slot=slot):
                d=Device(task);d.state={'ranking':'ranking','excavation':'excavation','worldboss':'boss_rank'}[task]
                v=Mock();v.recognize.side_effect=lambda _:d.screen()
                c=ExtraCollector(d,v,d.stop,lambda _:None);c.now=lambda:d.clock
                c.pause=lambda n:setattr(d,'clock',d.clock+n);c.boss_slot=slot
                c.action_state.reserve(task,slot);c.arm_regular_free_resume()
                self.assertEqual(c.claim_extra(task,c.screen()),'collected')
                self.assertEqual(d.claims,1);self.assertFalse(c.action_state.pending(task,slot))

    def test_autumn_current_pending_retries_once_and_cannot_rearm(self):
        from validate_autumn import RouteTests
        for stuck in (False,True):
            with self.subTest(stuck=stuck):
                d,c=RouteTests().collector(stuck=stuck)
                c.action_state.reserve('autumn');c.arm_regular_free_resume()
                c.cycle(['autumn']);self.assertEqual(d.claims,1)
                if stuck:
                    c.arm_regular_free_resume();c.cycle(['autumn'])
                    self.assertEqual(d.claims,1)
                    self.assertTrue(c.action_state.pending('autumn'))
                else:self.assertFalse(c.action_state.pending('autumn'))

    def test_request_changed_after_snapshot_cannot_authorize_retry(self):
        c,d=self.facility();c.action_state.reserve('mine');c.arm_regular_free_resume()
        c.action_state.reserve('mine',repeat_authorized=True)
        c.collect_room('mine',c.screen());self.assertEqual(d.claims['mine'],0)


    def test_request_changes_immediately_before_input_prevent_dispatch(self):
        from collector import ScreenChanged
        c,d=self.facility();c.action_state.reserve('mine');c.arm_regular_free_resume()
        self.assertTrue(c.can_retry_regular_free('mine'))
        original=c.tap
        def race(screen,name,**kwargs):
            reserve=kwargs['before_input']
            def changed():
                c.action_state.reserve('mine',repeat_authorized=True)
                reserve()
            kwargs['before_input']=changed
            return original(screen,name,**kwargs)
        c.tap=race
        with self.assertRaises(ScreenChanged):
            c.free_claim_tap(c.screen(),'ready_mine','mine',repeat_source='fresh_run_free_claim_retry')
        self.assertEqual(d.claims['mine'],0)
        self.assertFalse(c.can_retry_regular_free('mine'))



class ReliabilityV093Tests(unittest.TestCase):
    def test_fresh_continuation_accepts_free_pending_but_reconnect_does_not(self):
        from action_state import ActionState
        from session_workflow import held_reason
        a=ActionState();a.reserve('mine')
        self.assertTrue(held_reason('mine','deferred',a,{}))
        self.assertEqual(held_reason('mine','deferred',a,{},fresh_run=True),'')
        a.reserve('mine','upgrade')
        self.assertTrue(held_reason('mine','deferred',a,{},fresh_run=True))

    def test_invalid_recognition_cooldown_rechecks_but_keeps_pending_guard(self):
        from recognition_backoff import recognition_hold
        from action_state import ActionState
        from session_workflow import held_reason
        for entry in ({},{'retry_after':'bad'},{'retry_after':float('nan')},{'updated_at':'bad'}):
            self.assertFalse(recognition_hold(entry))
        a=ActionState();a.reserve('training')
        self.assertTrue(held_reason('training','deferred',a,{},fresh_run=True))

    def test_continuation_routes_current_free_request_to_new_run(self):
        from pathlib import Path
        import tempfile
        from action_state import ActionState
        from run_journal import RunJournal
        from session_workflow import continuation
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);j=RunJournal(p/'run_progress.json');j.begin('a',['mine']);j.result('a','mine','deferred')
            ActionState(p/'action_state.json','a').reserve('mine')
            result=continuation(p,{'a':{'enabled':True,'selected':{'mine':True},'name':'A'}})
            self.assertEqual(result['targets'],{'a':['mine']})



class ScopedRecordsV093Tests(unittest.TestCase):
    def test_action_scope_ignores_but_preserves_unrelated_damage(self):
        import tempfile,json
        from pathlib import Path
        from action_state import ActionState
        from daily_state import LedgerError
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'state.json';bad={'mine':{'pending':[]}}
            p.write_text(json.dumps({'broken':bad}))
            a=ActionState(p,'good',isolated=True);a.reserve('mine')
            self.assertEqual(json.loads(p.read_text())['broken'],bad)
            with self.assertRaises(LedgerError):ActionState(p,'broken',isolated=True)
            p.write_text('[]')
            with self.assertRaises(LedgerError):ActionState(p,'good',isolated=True)

    def test_daily_scope_preserves_unrelated_paid_damage_and_stops_selected(self):
        import tempfile,json
        from pathlib import Path
        from daily_state import ManualQuestLedger,LedgerError
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'daily.json';bad={'manual':{'daily_guild':{'_steps':[],'donation_paid':3}}}
            p.write_text(json.dumps({'broken':bad}))
            a=ManualQuestLedger(p,scope='good');a.begin_run('good');a.mark('good','daily_store','pass')
            self.assertEqual(json.loads(p.read_text())['broken'],bad)
            with self.assertRaises(LedgerError):ManualQuestLedger(p,scope='broken')
            with self.assertRaises(LedgerError):a.snapshot('broken')

    def test_journal_isolates_selected_account_and_preserves_corrupt_neighbor(self):
        import tempfile,json
        from pathlib import Path
        from run_journal import RunJournal
        from daily_state import LedgerError
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'journal.json';p.write_text(json.dumps({'broken':{'tasks':[]}}))
            j=RunJournal(p,isolated=True);j.begin('good',['mine']);j.result('good','mine','collected')
            self.assertEqual(json.loads(p.read_text())['broken'],{'tasks':[]})
            with self.assertRaises(LedgerError):j.begin('broken',['mine'])

    def test_continuation_keeps_healthy_account_when_selected_neighbor_is_damaged(self):
        import tempfile,json
        from pathlib import Path
        from run_journal import RunJournal
        from session_workflow import continuation
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);j=RunJournal(p/'run_progress.json')
            j.begin('good',['mine']);j.begin('bad',['mine'])
            (p/'action_state.json').write_text(json.dumps({'bad':{'mine':{'pending':[]}}}))
            players={k:{'enabled':True,'selected':{'mine':True},'name':k} for k in ('bad','good')}
            plan=continuation(p,players)
            self.assertEqual(plan['targets'],{'good':['mine']})
            self.assertTrue(any(x['id']=='bad' and '기록' in x['reason'] for x in plan['held']))



class IncidentEvidenceV093Tests(unittest.TestCase):
    def test_free_request_has_attributable_preinput_evidence(self):
        import tempfile,json,zipfile
        from pathlib import Path
        from types import SimpleNamespace
        from action_state import ActionState
        from diagnostics import bind_input_evidence,export_diagnostics
        from execution_trace import ExecutionTrace
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);scope='b'*24;trace=ExecutionTrace()
            c=SimpleNamespace(trace=trace,daily_ledger=None,action_state=ActionState(root/'action_state.json',scope),
                last_image=np.zeros((540,960,3),np.uint8),last_screen=Screen('mine_ready',{}))
            bind_input_evidence(c,root,'a'*24,scope,lambda _:None)
            c.action_state.reserve('mine');request=c.action_state.pending('mine')['id']
            name='last_'+scope+'_mine_claim_requested_input.zip'
            self.assertTrue((root/name).exists())
            export_diagnostics(root,root/'out.zip')
            with zipfile.ZipFile(root/'out.zip') as z:self.assertIn(name,z.namelist())
            with zipfile.ZipFile(root/name) as z:
                self.assertEqual(json.loads(z.read('evidence.json'))['detail']['pending']['claim']['id'],request)

    def test_incidents_preserve_first_failure_each_run_with_bounded_retention(self):
        import tempfile,json,zipfile
        from pathlib import Path
        from diagnostics import save_collection_failure,export_diagnostics
        from execution_trace import ExecutionTrace
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);image=np.zeros((540,960,3),np.uint8)
            def save(run,reason):
                trace=ExecutionTrace();trace.run_id=f'{run:032x}';trace.account_scope='b'*24;trace.task='mine';trace.step='claim'
                save_collection_failure(root,'a'*24,image,Screen('mine_ready',{}),reason,'mine',trace=trace)
            save(1,'first');first=list(root.glob('incident_*.zip'))
            self.assertEqual(len(first),1);original=first[0].read_bytes()
            save(1,'repeat');self.assertEqual(first[0].read_bytes(),original)
            for run in range(2,16):save(run,'new')
            incidents=list(root.glob('incident_*.zip'));self.assertEqual(len(incidents),12)
            self.assertLessEqual(sum(p.stat().st_size for p in incidents),24*1024*1024)
            self.assertFalse(first[0].exists())
            export_diagnostics(root,root/'out.zip')
            with zipfile.ZipFile(root/'out.zip') as z:self.assertTrue(any(n.startswith('incident_') for n in z.namelist()))



class ReviewFixesV093Tests(unittest.TestCase):
    def test_bad_legacy_account_does_not_prevent_healthy_fleet_job(self):
        import tempfile,json
        from pathlib import Path
        from unittest.mock import patch
        from validate_fleet import ManualLaunchTests
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);a=ManualLaunchTests().app();a.log=Mock()
            (root/'daily_tasks.json').write_text(json.dumps({'a':{'2026-10-25':{'daily_guild':{'_steps':[]}}}}))
            with patch('app.DATA',root),patch('fleet_collection.run_fleet') as runner:a.launch('daily')
            self.assertEqual([j['id'] for j in runner.call_args.args[0]],['b'])
            self.assertEqual(json.loads((root/'daily_tasks.json').read_text())['a']['2026-10-25']['daily_guild']['_steps'],[])

    def test_repeat_time_journal_damage_is_a_scoped_failure(self):
        import tempfile,json
        from pathlib import Path
        from unittest.mock import patch
        from validate_fleet import ManualLaunchTests
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);a=ManualLaunchTests().app();a.log=Mock();out=[]
            def runner(jobs,repeat,stop,update,execute,event,**kwargs):
                p=root/'run_progress.json';data=json.loads(p.read_text());data['a']={'tasks':[]};p.write_text(json.dumps(data))
                out.append(execute(jobs[0],jobs[0]['rooms']))
            with patch('app.DATA',root),patch('fleet_collection.run_fleet',side_effect=runner):a.launch('repeat')
            self.assertEqual(out,[{'farm':'failed'}])

    def test_overview_shows_good_account_and_explicit_damaged_account(self):
        import tempfile,json
        from pathlib import Path
        from today_overview import load_overview
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);p=root/'action_state.json';p.write_text(json.dumps({'bad':{'mine':{'pending':[]}}}));before=p.read_bytes()
            players={k:{'enabled':True,'name':k,'selected':{'mine':True},'daily_selected':{}} for k in ('bad','good')}
            rows={a['id']:a for a in load_overview(root,players)['accounts']}
            self.assertTrue(rows['bad']['record_error'])
            self.assertTrue(all(r['status']=='held' for r in rows['bad']['tasks']))
            self.assertFalse(rows['good'].get('record_error'));self.assertEqual(p.read_bytes(),before)

    def test_daily_underscore_incident_is_retained_and_exported(self):
        import tempfile,zipfile
        from pathlib import Path
        from execution_trace import ExecutionTrace
        from diagnostics import save_collection_failure,export_diagnostics
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);tr=ExecutionTrace();tr.account_scope='b'*24;tr.task='daily_store';tr.step='ruby_ad'
            save_collection_failure(root,'a'*24,np.zeros((540,960,3),np.uint8),Screen('free_store',{}),'failed','daily_store',trace=tr)
            incidents=list(root.glob('incident_*.zip'));self.assertEqual(len(incidents),1)
            export_diagnostics(root,root/'out.zip')
            with zipfile.ZipFile(root/'out.zip') as z:
                manifest=__import__('json').loads(z.read('diagnostics.json'))
                self.assertTrue(any(e['file']==incidents[0].name for e in manifest['entries']))

if __name__=='__main__':unittest.main()
