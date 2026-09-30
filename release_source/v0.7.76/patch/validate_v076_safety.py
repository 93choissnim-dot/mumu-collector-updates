"""Regression contracts for settings failures, stale recovery and free routes.

Use exact production method bodies with external UI/ADB boundaries replaced.
No live Android input, account screenshots or Windows desktop are needed here.
"""
import ast
import json
import os
from pathlib import Path
import queue
import tempfile
import threading
from types import FunctionType, ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent
# Windows (including the packaged EXE) uses real imported bytecode. The Linux
# audit workspace can exercise the same bodies without optional UI/CV modules.
RUNTIME={}
if os.name=='nt':
    import app,adb_device,game_recovery,free_daily_actions,daily_actions
    RUNTIME={m.__name__+'.py':m for m in (app,adb_device,game_recovery,free_daily_actions,daily_actions)}

def runtime_method(fn,namespace):
    for key,value in fn.__globals__.items():namespace.setdefault(key,value)
    clone=FunctionType(fn.__code__,namespace,fn.__name__,fn.__defaults__,fn.__closure__)
    clone.__kwdefaults__=fn.__kwdefaults__
    return clone

class Halt(Exception):pass
class ScreenChanged(Halt):pass
class InputNotSent(Halt):pass
class ResumeRecognition(Halt):pass
class OutcomeUnknown(Halt):pass

def method(filename,cls,name,namespace):
    if filename in RUNTIME:return runtime_method(getattr(getattr(RUNTIME[filename],cls),name),namespace)
    tree=ast.parse((ROOT/filename).read_text(encoding='utf-8'))
    owner=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==cls)
    node=next(n for n in owner.body if isinstance(n,ast.FunctionDef) and n.name==name)
    exec(compile(ast.Module(body=[node],type_ignores=[]),filename,'exec'),namespace)
    return namespace[name]

def class_methods(filename,cls,namespace):
    if filename in RUNTIME:
        owner=getattr(RUNTIME[filename],cls)
        return type(cls,(),{name:runtime_method(fn,namespace) for name,fn in vars(owner).items() if isinstance(fn,FunctionType)})
    tree=ast.parse((ROOT/filename).read_text(encoding='utf-8'))
    owner=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==cls)
    methods={}
    for node in owner.body:
        if isinstance(node,ast.FunctionDef):
            exec(compile(ast.Module(body=[node],type_ignores=[]),filename,'exec'),namespace)
            methods[node.name]=namespace[node.name]
    return type(cls,(),methods)

class Value:
    def __init__(self,value=None):self.value=value
    def set(self,value):self.value=value
    def get(self):return self.value

class SettingsTests(unittest.TestCase):
    def app(self,busy=True):
        ns={'os':SimpleNamespace(name='posix'),'queue':queue,'json':json,'LABELS':{}}
        cls=class_methods('app.py','App',ns);a=object.__new__(cls)
        a.stop=threading.Event();a.update_stop=threading.Event();a.events=queue.Queue()
        a.watch_value=Value(True);a.status=Value();a.config={'game_watch':True};a.players={'a':{}}
        a.next_at=123;a.failure=False;a.finish_text='';a.closing=False
        a.tray=None;a.hotkey_listener=None;a.busy=lambda:busy;a.poll_scheduled=[];a.destroyed=[]
        a.root=SimpleNamespace(after=lambda *v:a.poll_scheduled.append(v),destroy=lambda:a.destroyed.append(True))
        a.game_watch=SimpleNamespace(enabled=True)
        a.game_watch.enable=lambda v:setattr(a.game_watch,'enabled',v)
        return a,ns
    def test_close_cancels_before_fallible_save(self):
        a,_=self.app();observed=[]
        def save():
            observed.append((a.stop.is_set(),a.game_watch.enabled,a.update_stop.is_set()))
            raise OSError('disk full')
        a.save=save
        try:a.close()
        except OSError:pass
        self.assertEqual(observed,[(True,False,True)])
        self.assertTrue(a.closing)
    def test_close_finishes_even_when_settings_cannot_be_written(self):
        a,_=self.app(busy=False);a.save=lambda:(_ for _ in ()).throw(OSError('disk full'))
        try:a.close()
        except OSError:pass
        self.assertEqual(a.destroyed,[True])
        self.assertTrue(a.stop.is_set());self.assertFalse(a.game_watch.enabled)
    def test_poll_save_failure_halts_and_schedules_next_poll(self):
        a,_=self.app();a.events.put(('watch_package',('a','com.nns.genesis')))
        a.save=lambda:(_ for _ in ()).throw(OSError('settings locked'))
        try:a.poll()
        except OSError:pass
        self.assertTrue(a.stop.is_set())
        self.assertFalse(a.game_watch.enabled)
        self.assertEqual([v[0] for v in a.poll_scheduled],[150])
        self.assertIn('settings locked',a.status.get())
        # The scheduled entry point remains usable after the fault.
        a._poll_once=lambda:None
        a.poll_scheduled[0][1]()
        self.assertEqual(len(a.poll_scheduled),2)
    def configured(self,path):
        a,ns=self.app();ns['CONFIG']=path
        a.capture_profile=lambda:None;a.adb_path=Value('adb');a.address=Value('');a.chosen_serial=lambda:'127.0.0.1:16384'
        a.stop_hotkey=SimpleNamespace(value='F8');a.view_id='a'
        ui=ModuleType('ui_layout');ui.window_size=lambda root:None
        return a,ui
    def test_closing_poll_error_still_destroys_idle_window(self):
        a,_=self.app(busy=False);a.closing=True
        a._poll_once=lambda:(_ for _ in ()).throw(OSError('settings locked'))
        a.poll()
        self.assertEqual(a.destroyed,[True]);self.assertEqual(a.poll_scheduled,[])
    def test_tray_exit_destroys_window_only_once(self):
        a,_=self.app(busy=False);a.save=lambda:None
        a.events.put(('tray_exit',None));a.poll()
        self.assertEqual(a.destroyed,[True]);self.assertEqual(a.poll_scheduled,[])
    def test_real_save_failure_stops_automation_and_preserves_old_file(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'settings.json';p.write_text('{"old":true}')
            a,ui=self.configured(p)
            with patch.dict('sys.modules',{'ui_layout':ui}),patch('pathlib.Path.replace',side_effect=OSError('read only')):
                with self.assertRaises(OSError):a.save()
            self.assertTrue(a.stop.is_set());self.assertFalse(a.game_watch.enabled)
            self.assertEqual(json.loads(p.read_text()),{'old':True})
    def test_successful_settings_save_preserves_active_run(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'settings.json';a,ui=self.configured(p)
            with patch.dict('sys.modules',{'ui_layout':ui}):a.save()
            self.assertEqual(json.loads(p.read_text())['serial'],'127.0.0.1:16384')
            self.assertFalse(a.stop.is_set());self.assertTrue(a.game_watch.enabled)

class RecoveryAgeTests(unittest.TestCase):
    def run_confirmation(self,delay,kind='network'):
        clock=[0];checks=[0];sent=[]
        ns={'time':SimpleNamespace(monotonic=lambda:clock[0]),'Halt':Halt,
            'InputNotSent':InputNotSent,'ResumeRecognition':ResumeRecognition,'network_confirm':lambda im:(100,100),
            'download_confirm':lambda im:(100,100)}
        confirm=method('game_recovery.py','GameRecovery','confirm_startup',ns)
        position=method('adb_device.py','AdbDevice','position',ns)
        click=method('adb_device.py','AdbDevice','click',ns)
        control=ModuleType('run_control');control.RunControl=type('RunControl',(),{});control.ResumeRecognition=ResumeRecognition
        adb=ModuleType('adb_device');adb.InputNotSent=InputNotSent
        def verify():
            checks[0]+=1
            if checks[0]==2:clock[0]+=delay
        d=SimpleNamespace(current_package=lambda:'com.nns.genesis',raw_capture=lambda:SimpleNamespace(shape=(540,960,3)),
            guard_package=lambda:None,adb=SimpleNamespace(stop=object()),command=lambda args:sent.append(args))
        d.position=lambda point:position(d,point);d.click=lambda point:click(d,point)
        r=SimpleNamespace(check=lambda:None,verify_identity=verify,device=d,target='com.nns.genesis',
            stop=SimpleNamespace(generation=0),startup={},log=lambda _:None,
            vision=SimpleNamespace(recognize=lambda im:SimpleNamespace(state='offline_reward',matches={'offline_confirm':SimpleNamespace(center=(100,100))})))
        with patch.dict('sys.modules',{'run_control':control,'adb_device':adb}):
            try:confirm(r,kind,(100,100))
            except InputNotSent:pass
        return sent,r.startup
    def test_slow_identity_check_cannot_rejuvenate_any_startup_capture(self):
        for kind in ('network','download','offline'):
            with self.subTest(kind=kind):
                sent,state=self.run_confirmation(6,kind)
                self.assertEqual(sent,[])
                self.assertNotIn(kind,state.get('confirmed',set()))
                self.assertFalse(state.get('network_unconfirmed'))
    def test_fresh_startup_capture_still_dispatches(self):
        sent,state=self.run_confirmation(1)
        self.assertEqual(sent,[['shell','input','tap',100,100]])
        self.assertTrue(state['network_unconfirmed'])

class FreeRouteTests(unittest.TestCase):
    def fixture(self,pending=None,error=InputNotSent):
        adb=ModuleType('adb_device');adb.InputNotSent=InputNotSent
        mocked=patch.dict('sys.modules',{'adb_device':adb});mocked.start();self.addCleanup(mocked.stop)
        ns={'InputNotSent':InputNotSent,'Halt':Halt,'ScreenChanged':ScreenChanged,'OutcomeUnknown':OutcomeUnknown,
            'STORE_PAGES':{'free_store'},'step_label':lambda *a:'/'.join(a)}
        cls=class_methods('free_daily_actions.py','FreeDailyActions',ns)
        cls.daily_try_tap=method('daily_actions.py','DailyActions','daily_try_tap',ns)
        c=cls();c.detail={'pending':pending} if pending else {};c.dispatched=[]
        c.free_check_day=lambda:None;c.daily_detail=lambda:c.detail
        c.daily_checkpoint=lambda status,**fields:c.detail.update(fields,status=status)
        def tap(screen,key,point=None,*,before_input,**kw):
            before_input()
            if error is not InputNotSent:c.dispatched.append(key)
            raise error('input boundary')
        c.daily_tap=tap;c.forget_observations=lambda:None;c.pause=lambda _:None
        return c
    def test_explicit_unsent_new_request_is_retired(self):
        adb=ModuleType('adb_device');adb.InputNotSent=InputNotSent
        for key in ('summon','confirm_cube_ad'):
            with self.subTest(key=key),patch.dict('sys.modules',{'adb_device':adb}):
                c=self.fixture()
                with self.assertRaises(InputNotSent):c.free_commit(None,key,2)
                self.assertIsNone(c.detail.get('pending'))
                self.assertEqual(c.detail.get('resolution_source'),'input_not_sent')
                self.assertEqual(c.dispatched,[])
    def test_transport_uncertainty_preserves_new_request(self):
        adb=ModuleType('adb_device');adb.InputNotSent=InputNotSent
        with patch.dict('sys.modules',{'adb_device':adb}):
            c=self.fixture(error=Halt)
            with self.assertRaises(Halt):c.free_commit(None,'summon',2)
            self.assertEqual(c.detail['pending'],'free_summon')
            self.assertEqual(len(c.dispatched),1)
    def test_inherited_pending_is_never_retired_or_dispatched(self):
        c=self.fixture(pending='old_request')
        with self.assertRaises(OutcomeUnknown):c.free_commit(None,'summon',2)
        self.assertEqual(c.detail['pending'],'old_request');self.assertEqual(c.dispatched,[])
    def shop(self,absent=False,visible=False):
        c=self.fixture();c.drags=[]
        def screen():
            keys={'free_selected_general'}
            if absent:keys.add('free_cube_absent')
            elif visible or c.drags:keys.add('free_open_cube_ad')
            return SimpleNamespace(state='free_store',matches=keys)
        c.daily_wait=lambda states:screen();c.daily_has=lambda s,k:k in s.matches
        c.daily_ready=lambda states,keys:screen()
        c.free_store_scroll=lambda s,up=False:c.drags.append(up)
        return c
    def test_target_found_after_first_scroll_stops_search(self):
        c=self.shop();c.free_store_find('cube_ad');self.assertEqual(c.drags,[True])
    def test_visible_cube_absent_needs_no_scroll(self):
        c=self.shop(absent=True);c.free_store_find('cube_ad');self.assertEqual(c.drags,[])
    def test_visible_card_needs_no_scroll(self):
        c=self.shop(visible=True);c.free_store_find('cube_ad');self.assertEqual(c.drags,[])
    def test_cube_absent_does_not_confirm_inherited_pending(self):
        c=self.shop(absent=True);c.detail={'pending':'free_confirm_cube_ad'}
        c.free_store_finish_proven_reward=lambda key:False
        with self.assertRaises(OutcomeUnknown):c.free_store_step('cube_ad')
        self.assertEqual(c.detail['pending'],'free_confirm_cube_ad')

if __name__=='__main__':unittest.main()
