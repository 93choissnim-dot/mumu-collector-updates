import threading
import unittest
from unittest.mock import Mock,patch
from fleet_runner import run_fleet
from collector import Collector,Halt
from mumu_names import read_catalog
import json

class Clock:
    def __init__(self):self.now=0;self.stopped=False
    def is_set(self):return self.stopped
    def wait(self,t):self.now+=t;return self.stopped

class FleetTests(unittest.TestCase):
    def jobs(self):return [{'id':'a','name':'본캐','rooms':['farm'],'minutes':1},{'id':'b','name':'부캐','rooms':['mine'],'minutes':2}]
    def test_failure_does_not_stop_other_instance(self):
        seen=[]
        def run(j,r):
            seen.append(j['id'])
            if j['id']=='a':raise Halt('lost')
            return {'mine':'collected'}
        run_fleet(self.jobs(),False,threading.Event(),threading.Event(),run,lambda *x:None)
        self.assertEqual(seen,['a','b'])
    def test_independent_intervals(self):
        clock=Clock();seen=[]
        def run(j,r):
            seen.append((j['id'],round(clock.now)))
            if len(seen)==5:clock.stopped=True
            return {r[0]:'skipped'}
        run_fleet(self.jobs(),True,clock,threading.Event(),run,lambda *x:None,lambda:clock.now)
        self.assertEqual(seen,[('a',0),('b',0),('a',60),('a',120),('b',120)])
    def test_update_waits_for_current_then_stops(self):
        update=threading.Event();seen=[]
        def run(j,r):seen.append(j['id']);update.set();return {r[0]:'collected'}
        run_fleet(self.jobs(),True,threading.Event(),update,run,lambda *x:None)
        self.assertEqual(seen,['a'])
    def test_stop_prevents_next_instance(self):
        stop=threading.Event();seen=[]
        def run(j,r):seen.append(j['id']);stop.set();return {}
        run_fleet(self.jobs(),False,stop,threading.Event(),run,lambda *x:None)
        self.assertEqual(seen,['a'])
    def test_failed_room_has_only_two_early_retries(self):
        clock=Clock();seen=[];jobs=self.jobs()[:1];jobs[0]['minutes']=60
        def run(j,r):
            seen.append(round(clock.now))
            if len(seen)==4:clock.stopped=True
            return {'farm':'failed'}
        run_fleet(jobs,True,clock,threading.Event(),run,lambda *x:None,lambda:clock.now)
        self.assertEqual(seen,[0,120,240,3600])
    def collector(self):
        c=Collector(Mock(),Mock(),threading.Event(),Mock())
        c.progress=Mock();c.click_match=Mock();c.ensure_menu=Mock(return_value=Mock())
        # This fixture isolates collection-failure recovery. Entry navigation
        # now has its own real-state tests in validate_entry.py.
        c.open_room=Mock(return_value=Mock())
        c.screen=Mock(return_value=Mock(state='menu'))
        c.collect_room=Mock(side_effect=[Halt('farm unknown'),Mock()])
        return c
    def test_facility_failure_recovers_before_next(self):
        c=self.collector();c.cycle(['farm','mine'])
        self.assertEqual(c.results['farm'],'failed')
        self.assertEqual(c.collect_room.call_count,2)
        self.assertEqual([call.args[0] for call in c.open_room.call_args_list],['farm','mine'])
        self.assertEqual(c.ensure_menu.call_args_list[1].args[1],'farm')
    def test_unsafe_recovery_prevents_next_facility(self):
        c=self.collector();c.ensure_menu.side_effect=[Mock(),Halt('unknown screen')]
        with self.assertRaises(Halt):c.cycle(['farm','mine'])
        self.assertEqual(c.collect_room.call_count,1)
        self.assertEqual([call.args[0] for call in c.open_room.call_args_list],['farm'])
    @patch('adb_device.mumu_locations',return_value=([],[]))
    @patch('mumu_names.Path.is_file',return_value=True)
    @patch('mumu_names.subprocess.Popen')
    def test_identity_survives_name_and_port_change(self,popen,*_):
        proc=popen.return_value;proc.returncode=0;proc.poll.return_value=0
        def read(name,port,index=0):
            proc.communicate.return_value=(json.dumps({str(index):{'name':name,'adb_port':port,'created_timestamp':10}}).encode(),b'')
            return next(iter(read_catalog('/mumu/adb.exe',threading.Event(),lambda x:None).values()))['instance_id']
        self.assertEqual(read('본캐',16384),read('새 이름',16416))
        self.assertNotEqual(read('본캐',16384),read('본캐',16384,1))

if __name__=='__main__':unittest.main()

class ManualLaunchTests(unittest.TestCase):
    def app(self):
        from fleet_collection import FleetCollection
        import queue
        app=FleetCollection();app.busy=lambda:False;app.capture_profile=Mock();app.save=Mock()
        app.players={'a':{'name':'one','enabled':True,'minutes':180,'selected':{'farm':True,'daily_pass':True}},
                     'b':{'name':'two','enabled':True,'minutes':120,'selected':{}},
                     'c':{'name':'three','enabled':False,'minutes':60,'selected':{'mine':True}}}
        app.count_label=Mock();app.fleet_states={};app.adb_path=Mock();app.device_reports={};app.events=queue.Queue()
        app.stop=threading.Event();app.update_pending=threading.Event();app.run_worker=Mock(side_effect=lambda fn,*a,**k:fn())
        return app
    def test_manual_button_includes_all_groups_and_daily_only_targets(self):
        from daily_state import DAILY_TASKS
        app=self.app()
        with patch('fleet_collection.run_fleet') as worker:app.launch('daily')
        jobs,repeat,*_=worker.call_args.args
        self.assertFalse(repeat);self.assertEqual([j['id'] for j in jobs],['a','b'])
        self.assertTrue(all(j['rooms']==list(DAILY_TASKS) for j in jobs))
        self.assertEqual(app.players['a']['selected'],{'farm':True,'daily_pass':True})
    def test_ordinary_run_ignores_legacy_daily_checkboxes(self):
        for mode in ('once','repeat'):
            app=self.app()
            with patch('fleet_collection.run_fleet') as worker:app.launch(mode)
            jobs,repeat,*_=worker.call_args.args
            self.assertEqual([j['rooms'] for j in jobs],[['farm']]);self.assertEqual(repeat,mode=='repeat')
    def test_busy_blocks_second_worker(self):
        app=self.app();app.busy=lambda:True
        app.launch('daily');app.run_worker.assert_not_called();app.save.assert_not_called()
