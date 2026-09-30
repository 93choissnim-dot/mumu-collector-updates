"""Persist release-test progress and Python stacks before any GUI is created."""
import json
from pathlib import Path
import sys
import threading
import time
import traceback
import unittest


def run_suite(suite,output):
    output=Path(output);stop=threading.Event();started={}
    class Result(unittest.TestResult):
        def startTest(self,test):
            super().startTest(test);started['at']=time.monotonic()
            self.progress(test,'running')
        def progress(self,test,phase,elapsed=None):
            output.with_suffix('.progress.json').write_text(json.dumps({
                'stage':'packaged_regression','test':test.id(),'phase':phase,
                'elapsed_seconds':elapsed,'successful':self.wasSuccessful() if phase=='finished' else None}),encoding='utf-8')
        def stopTest(self,test):
            elapsed=round(time.monotonic()-started['at'],3)
            self.progress(test,'finished',elapsed)
            with output.with_suffix('.tests.log').open('a',encoding='utf-8') as stream:
                stream.write(json.dumps({'test':test.id(),'seconds':elapsed},ensure_ascii=False)+'\n')
            super().stopTest(test)
    def sample():
        while not stop.wait(20):
            with output.with_suffix('.regression-threads.log').open('a',encoding='utf-8') as stream:
                stream.write('Regression thread snapshot\n')
                for ident,stack in sys._current_frames().items():
                    stream.write('Thread '+str(ident)+'\n');traceback.print_stack(stack,file=stream)
    worker=threading.Thread(target=sample,name='regression-trace',daemon=True);worker.start()
    try:
        result=Result();suite.run(result);return result
    finally:
        stop.set();worker.join(timeout=2)
