"""History retry and worker lifecycle regressions without a display or game input."""
import queue
import tempfile
import threading
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock,patch
import app
import ui_history
from history import History
from run_control import RunControl
from stop_hotkey import StopHotkey
from ui_state import retry_tasks

class Widget:
    def __init__(self,*args,**kw):self.args=args;self.kw=kw;self.exists=True
    def __getattr__(self,name):return lambda *args,**kw:None
    def configure(self,**kw):self.kw.update(kw)
    def cget(self,key):return self.kw.get(key)
    def winfo_exists(self):return self.exists
    def winfo_children(self):return []
    def destroy(self):self.exists=False
class Value:
    def __init__(self,value=''):self.value=value
    def get(self):return self.value
    def set(self,value):self.value=value
class Root(Widget):
    def __init__(self):super().__init__();self.idle=[]
    def after_idle(self,callback):self.idle.append(callback)
    def flush(self):
        pending,self.idle=self.idle,[]
        for callback in pending:callback()
    def winfo_width(self):return 1000
    def _get_window_scaling(self):return 1

class HistoryLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.stack=ExitStack()
        self.stack.enter_context(patch.object(app,'DATA',Path(self.tmp.name)))
        a=self.a=app.App.__new__(app.App)
        a.worker=None;a.events=queue.Queue();a.stop=RunControl();a.update_pending=threading.Event();a.update_applying=False
        a.status=Value();a.stop_hotkey=StopHotkey('F8');a.hotkey_listener=None;a.hotkey_capture=False;a.closing=False
        a.fleet_states={};a.controls=[Widget()];a.stop_button=Widget();a.pause_button=Widget()
        a.render_roster=Mock();a.render_fleet_status=Mock();a.refresh_details=Mock();a.log=Mock()
        a.countdown=Value();a.root=Root();a.status_label=Widget();a.compact_layout=False;a.view_id='vm'
        a.players={'vm':{'name':'VM','serial':'s','selected':{'farm':True},'minutes':60,'enabled':True}}
        a.history=History(Path(self.tmp.name)/'history.json');a.history.record('vm','farm','failed',reason='fixture')
        a.capture_profile=Mock();a.save=Mock();a.count_label=Widget();a.adb_path=Value('adb');a.device_reports={};a.select_player=Mock()
        self.widgets=[]
        def widget(*args,**kw):
            item=Widget(*args,**kw);self.widgets.append(item);return item
        self.stack.enter_context(patch.multiple(ui_history.ctk,CTkToplevel=Widget,CTkFrame=Widget,CTkScrollableFrame=Widget))
        self.stack.enter_context(patch.object(ui_history.tk,'StringVar',Value))
        self.stack.enter_context(patch.multiple(ui_history,heading=widget,label=widget,button=widget,panel=widget,GameTabs=Widget,font=lambda *a,**kw:None,fit_window=lambda *a,**kw:(720,650)))
        self.gate=threading.Event()
    def tearDown(self):
        self.gate.set()
        if self.a.worker:self.a.worker.join(2)
        self.stack.close();self.tmp.cleanup()
    def test_queued_completion_keeps_retry_owned_until_poll(self):
        a=self.a;a.history_dialog('vm')
        row=next(w for w in self.widgets if '이 작업만 재시도' in w.args)
        a.run_worker(lambda:None,'first',pausable=True);a.worker.join(2)
        a.launch=Mock()
        row.args[2]()
        self.assertTrue(a.busy(),'finished thread remains owned until its completion event is consumed')
        a.launch.assert_not_called()
        a.poll();self.assertFalse(a.busy());self.assertEqual(a.stop_button.kw['state'],'disabled')
        a.run_worker(lambda:self.gate.wait(2),'second',pausable=True)
        a.toggle_pause();a.poll()
        self.assertTrue(a.stop.paused);self.assertEqual(a.stop_button.kw['state'],'normal')
    def test_history_updates_once_after_done_and_not_each_poll(self):
        a=self.a;a.run_worker(lambda:self.gate.wait(2),'first',pausable=True);a.history_dialog('vm')
        self.assertEqual(a.history_retry_button.kw['state'],'disabled')
        self.gate.set();a.worker.join(2);a.poll();a.root.flush()
        self.assertEqual(a.history_retry_button.kw['state'],'normal')
        rendered=len(self.widgets)
        a.poll();a.root.flush();a.poll();a.root.flush()
        self.assertEqual(len(self.widgets),rendered)
    def test_refresh_history_refreshes_open_rows_and_batches_requests(self):
        a=self.a;a.history_dialog('vm');rendered=len(self.widgets)
        a.history.record('vm','farm','collected')
        a.refresh_history();a.refresh_history();a.root.flush()
        self.assertEqual(a.history_retry_button.kw['state'],'disabled')
        self.assertGreater(len(self.widgets),rendered)
        self.assertEqual(len(a.root.idle),0)
    def test_daily_retry_includes_issues_even_without_regular_selection(self):
        self.assertEqual(retry_tasks({'selected':{}},{'daily_guild':{'result':'deferred'}},['daily_guild']),['daily_guild'])
        self.assertEqual(retry_tasks({'selected':{'farm':False}},{'farm':{'result':'failed'},'daily_pass':{'result':'collected'}}),[])
    def test_daily_retry_button_launches_daily_target(self):
        a=self.a;a.history.record('vm','daily_guild','failed');a.launch=Mock()
        a.retry_failed('vm',['daily_guild'])
        a.launch.assert_called_once_with('retry',{'vm':['daily_guild']})
    def test_blocked_retry_explains_pause_and_update(self):
        a=self.a;a.run_worker(lambda:self.gate.wait(2),'first',pausable=True);a.stop.pause()
        a.retry_failed('vm',['farm']);self.assertIn('중지',a.status.get())
        a.update_pending.set();a.retry_failed('vm',['farm']);self.assertIn('업데이트',a.status.get())
    def test_pending_resolution_is_available_for_daily_and_training_issues(self):
        a=self.a;a.history.record('vm','daily_guild','deferred');a.history.record('vm','training','deferred')
        a.history_dialog('vm')
        buttons=[w for w in self.widgets if '보류 해결' in w.args]
        self.assertEqual(len(buttons),2)
        self.assertTrue(all(w.kw['state']=='normal' for w in buttons))
    def test_disabled_task_retry_explains_selection(self):
        a=self.a;a.players['vm']['selected']['farm']=False
        a.retry_failed('vm',['farm']);self.assertIn('작업 설정',a.status.get())

if __name__=='__main__':unittest.main()
