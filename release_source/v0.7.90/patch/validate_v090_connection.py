"""Connection draft validation, transactional saves and read-only diagnostics."""
import importlib
import importlib.util
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest


class Value:
    def __init__(self, value=''):self.value=value
    def get(self):return self.value
    def set(self,value):self.value=value


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('ui_connection'), 'connection setup module is missing')
        self.ui=importlib.import_module('ui_connection')
    def app(self):
        app=SimpleNamespace(adb_path=Value('old.exe'),address=Value('127.0.0.1:1'),
            config={'adb_path':'old.exe','address':'127.0.0.1:1','game_watch':True},
            busy=lambda:False,closing=False,worker_pending=None,worker=None,
            watch_thread=None,update_thread=None,update_applying=False,
            update_pending=threading.Event(),device_lane=threading.RLock(),saved=0,connected=0)
        def save():
            app.saved+=1
            app.config.update(adb_path=app.adb_path.get(),address=app.address.get())
        def connect():app.connected+=1
        app.save=save;app.connect=connect
        return app
    def test_blank_means_auto_discovery_and_numeric_port_is_local(self):
        self.assertEqual(self.ui.validate_connection('', ''),('', ''))
        self.assertEqual(self.ui.validate_connection('  ', ' 07555 '),('', '127.0.0.1:7555'))
        self.assertEqual(self.ui.validate_connection('', 'localhost:65535'),('', '127.0.0.1:65535'))
    def test_only_existing_named_adb_executables_are_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ('adb.exe','adb_server.exe','ADB.EXE'):
                path=Path(directory)/name;path.touch()
                self.assertEqual(self.ui.validate_connection(str(path), '')[0],str(path))
            for value in (directory,str(Path(directory)/'missing.exe'),str(Path(directory)/'adb.exe')+' version'):
                with self.assertRaises(ValueError):self.ui.validate_connection(value,'')
            bad=Path(directory)/'other.exe';bad.touch()
            with self.assertRaises(ValueError):self.ui.validate_connection(str(bad),'')
    def test_remote_and_command_like_addresses_are_rejected(self):
        for value in ('0','65536','-1','1.2.3.4:5555','127.0.0.1:5555 shell','7555;whoami','emulator-5554'):
            with self.subTest(value=value),self.assertRaises(ValueError):self.ui.validate_connection('',value)
    def test_save_and_reconnect_use_existing_connection_operation(self):
        app=self.app();self.ui.apply_connection(app,'','7555',reconnect=True)
        self.assertEqual((app.adb_path.get(),app.address.get()),('', '127.0.0.1:7555'))
        self.assertEqual((app.saved,app.connected),(1,1))
    def test_save_without_diagnosis_does_not_start_work(self):
        app=self.app();self.ui.apply_connection(app,'','')
        self.assertEqual((app.saved,app.connected),(1,0))
    def test_failed_save_rolls_back_connection_and_preserves_safety_stop(self):
        app=self.app()
        def fail():
            app.config.update(adb_path='changed',address='changed',game_watch=False)
            raise OSError('disk full')
        app.save=fail
        with self.assertRaises(OSError):self.ui.apply_connection(app,'','7555',reconnect=True)
        self.assertEqual((app.adb_path.get(),app.address.get()),('old.exe','127.0.0.1:1'))
        self.assertEqual((app.config['adb_path'],app.config['address']),('old.exe','127.0.0.1:1'))
        self.assertFalse(app.config['game_watch']);self.assertEqual(app.connected,0)
    def test_failure_does_not_create_absent_config_keys(self):
        app=self.app();app.config={}
        def fail():app.config.update(adb_path='new',address='new');raise OSError('full')
        app.save=fail
        with self.assertRaises(OSError):self.ui.apply_connection(app,'','')
        self.assertEqual(app.config,{})
    def test_active_work_recovery_and_updates_cannot_change_settings(self):
        for attr,value in [('busy',lambda:True),('worker_pending',2),('worker',SimpleNamespace(is_alive=lambda:True)),
                           ('watch_thread',SimpleNamespace(is_alive=lambda:True)),
                           ('update_thread',SimpleNamespace(is_alive=lambda:True)),('update_applying',True),('closing',True)]:
            app=self.app();setattr(app,attr,value)
            with self.subTest(attr=attr),self.assertRaises(RuntimeError):self.ui.apply_connection(app,'','',reconnect=True)
            self.assertEqual((app.adb_path.get(),app.saved,app.connected),('old.exe',0,0))
        app=self.app();app.update_pending.set()
        with self.assertRaises(RuntimeError):self.ui.apply_connection(app,'','')
    def test_device_lane_in_use_is_not_changed(self):
        app=self.app();app.device_lane=threading.Lock();app.device_lane.acquire()
        try:
            with self.assertRaises(RuntimeError):self.ui.apply_connection(app,'','')
        finally:app.device_lane.release()
        self.assertEqual((app.saved,app.connected),(0,0))
    def test_diagnostic_stages_are_honest_without_evidence(self):
        stages=self.ui.connection_stages({},'')
        self.assertEqual(len(stages),4)
        self.assertTrue(all('미확인' in detail for title,detail in stages))
    def test_diagnostic_separates_capture_success_from_wrong_foreground(self):
        report={'package':'com.android.launcher','state':'unknown','image':SimpleNamespace(shape=(540,960,3)),
                'model':'MuMu','instance_id':'player1'}
        stages=self.ui.connection_stages({'127.0.0.1:7555':report},'127.0.0.1:7555')
        self.assertIn('게임',stages[2][1]);self.assertIn('열어',stages[2][1])
        self.assertIn('16:9',stages[3][1]);self.assertIn('미인식',stages[3][1])
    def test_diagnostic_reports_package_query_and_capture_failures_separately(self):
        report={'package_error':'focus unavailable','image':None,'error':'PNG unavailable'}
        stages=self.ui.connection_stages({'127.0.0.1:7555':report},'127.0.0.1:7555')
        self.assertIn('focus unavailable',stages[2][1]);self.assertIn('PNG unavailable',stages[3][1])
    def test_non_widescreen_reports_required_correction(self):
        report={'package':'com.nns.genesis','state':'unknown','image':SimpleNamespace(shape=(600,800,3))}
        stages=self.ui.connection_stages({'127.0.0.1:7555':report},'127.0.0.1:7555')
        self.assertIn('16:9로',stages[3][1])
    def test_multiple_reports_require_selection_for_game_and_capture(self):
        stages=self.ui.connection_stages({'a':{},'b':{}},'')
        self.assertIn('선택',stages[2][1]);self.assertIn('선택',stages[3][1])


if __name__=='__main__':unittest.main()
