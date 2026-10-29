"""Native price evidence and inherited free-store request regression tests."""
import base64,json,unittest
from pathlib import Path
from datetime import datetime,timedelta
from unittest.mock import patch
import cv2,numpy as np
from vision import Vision,Screen,Match
from collector import Halt
from daily_state import KST,save_json
from validate_v072_free_daily import RouteHarness

class NativePriceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.vision=Vision()
    def frame(self,key):
        im=np.full((540,960,3),110,np.uint8)
        data=json.loads((Path(__file__).parent/'assets/v096_pass_cases.json').read_text())
        for piece in data[key]:
            x,y,r,b=piece['box'];im[y:b,x:r]=cv2.imdecode(np.frombuffer(base64.b64decode(piece['png']),np.uint8),1)
        return im
    def test_native_won_prices_are_excluded_without_claim_markers(self):
        for key in ('keys','gear'):
            for width in (960,1280,1920):
                with self.subTest(key=key,width=width):
                    im=cv2.resize(self.frame(key),(width,width*9//16));s=self.vision.recognize(im)
                    self.assertIn('daily_pass_'+key+'_purchase',s.matches)
                    self.assertNotIn('daily_pass_'+key+'_active',s.matches)
    def test_blank_dim_or_contextless_button_is_not_purchase(self):
        for key in ('keys','gear'):
            for kind in ('dim','context','no_amount'):
                im=self.frame(key)
                if kind=='dim':im=(im*.5).astype(np.uint8)
                elif kind=='context':im[:450]=110
                else:im[480:515,(710 if key=='keys' else 530):(855 if key=='keys' else 690)]=[120,160,145]
                self.assertNotIn('daily_pass_'+key+'_purchase',self.vision.recognize(im).matches)
        self.assertNotIn('daily_pass_keys_purchase',self.vision.recognize(self.frame('keys_blank')).matches)

class StoreResumeTests(RouteHarness,unittest.TestCase):
    def route(self,key='ruby',*,old=False,armed=False,stuck=False):
        tab='general' if key=='cube_ad' else 'currency'
        states=[self.screen('free_store',**{'open_'+key:(359,230),'selected_'+tab:(73,30)}),
                self.screen('free_store_confirm_'+key,**{'confirm_'+key:(480,387),'dialog_close':(631,86)}),
                Screen('reward',{'reward_close':Match('reward_close',1,0,(640,520))}),
                self.screen('free_store',home=(919,28))]
        c,d=self.make('daily_store',key,states,stuck=stuck)
        c.daily_checkpoint('uncertain',pending='free_confirm_'+key)
        if old:
            data=c.daily_ledger.data[c.daily_ident][c.daily_day]['daily_store']['_steps'][key]
            data['input_request']['requested_at']=(datetime.now(KST)-timedelta(days=4)).isoformat()
            save_json(c.daily_ledger.path,c.daily_ledger.data)
        if armed:c.arm_free_resume()
        return c,d
    def test_old_store_requests_do_not_block_fresh_literal_free_dialog(self):
        for key in ('ruby','ruby_ad','cube_ad'):
            with self.subTest(key=key):
                c,d=self.route(key,old=True);old=c.daily_detail()['input_request']['id']
                c.free_store_step(key)
                self.assertTrue(c.daily_done(key));self.assertEqual(len(d.clicks),3)
                history=c.daily_detail()['input_history']
                record=next(r for r in history if r['request']['id']==old)
                self.assertFalse(record['resolution']['confirmed'])
    def test_new_run_may_retry_inherited_request_once(self):
        c,d=self.route(armed=True);c.free_store_step('ruby')
        self.assertTrue(c.daily_done('ruby'));self.assertEqual(len(d.clicks),3)
    def test_same_run_unarmed_pending_is_not_replayed(self):
        c,d=self.route()
        with self.assertRaises(Halt):c.free_store_step('ruby')
        self.assertEqual(d.clicks,[])
    def test_changed_or_paid_dialog_preserves_previous_request(self):
        c,d=self.route(old=True);old=c.daily_detail()['input_request']['id']
        recognize=c.vision.recognize
        c.vision.recognize=lambda im:self.screen('free_store_dialog',dialog_close=(631,86)) if int(im[0,0,0])==1 else recognize(im)
        with self.assertRaises(Halt):c.free_store_step('ruby')
        self.assertEqual(c.daily_detail()['input_request']['id'],old)
        self.assertEqual(len(d.clicks),1)
    def test_new_failed_request_cannot_reuse_fresh_run_permission(self):
        c,d=self.route(armed=True)
        click=d.click
        def dispatch(point):
            click(point)
            if d.index==2:raise Halt('connection lost after confirmation')
        d.click=dispatch
        with self.assertRaises(Halt):c.free_store_step('ruby')
        count=len(d.clicks);d.index=0;c.forget_observations();c.arm_free_resume()
        with self.assertRaises(Halt):c.free_store_step('ruby')
        self.assertEqual(len(d.clicks),count)
    def test_future_or_unattributed_history_is_not_discarded(self):
        for kind in ('future','missing','paid'):
            c,d=self.route(old=True)
            data=c.daily_ledger.data[c.daily_ident][c.daily_day]['daily_store']['_steps']['ruby']
            if kind=='future':data['input_request']['requested_at']=(datetime.now(KST)+timedelta(days=1)).isoformat()
            elif kind=='missing':data.pop('input_request')
            else:data['pending']='donate_50';data['input_request']['action']='donate_50'
            save_json(c.daily_ledger.path,c.daily_ledger.data)
            with self.assertRaises(Halt):c.free_store_step('ruby')
            self.assertEqual(d.clicks,[]);self.assertTrue(c.daily_detail()['pending'])

    def test_explicit_zero_cube_card_resolves_old_pending_without_claim(self):
        c,d=self.make('daily_store','cube_ad',[self.screen('free_store',done_cube_ad=(359,85),selected_general=(73,30))])
        c.daily_checkpoint('uncertain',pending='free_confirm_cube_ad')
        c.free_store_step('cube_ad');self.assertTrue(c.daily_done('cube_ad'));self.assertEqual(d.clicks,[])

class FleetStoreOnlyTests(unittest.TestCase):
    def test_store_only_fresh_run_arms_existing_same_day_request(self):
        import tempfile
        from contextlib import ExitStack
        from unittest.mock import Mock
        from validate_fleet import ManualLaunchTests
        from daily_state import ManualQuestLedger
        from action_state import account_scope
        app=ManualLaunchTests().app();app.players={'a':dict(app.players['a'],daily_selected={'daily_store':True,'daily_summon':False,'daily_pass':False,'daily_dungeons':False,'daily_guild':False})}
        app.log=Mock();app.history=Mock();seen=[]
        with tempfile.TemporaryDirectory() as directory,ExitStack() as stack:
            root=Path(directory);scope=account_scope('a','')
            ledger=ManualQuestLedger(root/'daily_manual.json',scope=scope)
            ledger.checkpoint(scope,'daily_store','ruby','uncertain',pending='free_confirm_ruby')
            request=ledger.detail(scope,'daily_store','ruby')['input_request']
            stack.enter_context(patch('app.DATA',root))
            stack.enter_context(patch('fleet_collection.CatalogLookup')).return_value.read.return_value={'serial':{'instance_id':'a','name':'synthetic'}}
            stack.enter_context(patch('fleet_collection.Adb'))
            stack.enter_context(patch('fleet_collection.AdbDevice'))
            stack.enter_context(patch('fleet_collection.Vision'))
            stack.enter_context(patch('game_recovery.GameRecovery'))
            stack.enter_context(patch('fleet_collection.bind_input_evidence'))
            stack.enter_context(patch('fleet_collection.save_execution_trace'))
            def cycle(c,rooms,*args):
                self.assertEqual(rooms,['daily_store'])
                seen.append(getattr(c,'free_resume_requests',{}).get(('daily_store','ruby')))
                return {'daily_store':'deferred'}
            stack.enter_context(patch('run_review.run_reviewed_cycle',side_effect=cycle))
            stack.enter_context(patch('fleet_collection.run_fleet',side_effect=lambda jobs,repeat,stop,update,execute,*a,**k:execute(jobs[0],jobs[0]['rooms'])))
            app.launch('daily')
            self.assertEqual(seen,[request])

if __name__=='__main__':unittest.main()
