"""Interpreter-only process termination tests; Windows source gate runs these."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from daily_state import ManualQuestLedger


class ProcessTerminationTests(unittest.TestCase):
    def test_termination_during_save_preserves_pending_record(self):
        # This module is deliberately source-only: a frozen app is not a Python
        # interpreter. The release workflow runs it before building the EXE.
        script='''
import os,sys
from pathlib import Path
from record_storage import save_json
path=Path(sys.argv[1])
if sys.argv[2]=='flush':
    os.fsync=lambda *args:os._exit(77)
else:
    Path.replace=lambda *args:os._exit(77)
save_json(path,{'replacement':'must never be published'})
'''
        for phase in ('flush','replace'):
            with self.subTest(phase=phase),tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'종료_기록.json'
                ledger=ManualQuestLedger(path)
                ledger.checkpoint('a','daily_guild','donation','uncertain',pending='donate_50')
                before=path.read_bytes();request=ledger.detail('a','daily_guild','donation')['input_request']
                child=subprocess.run([sys.executable,'-c',script,str(path),phase],
                                     cwd=Path(__file__).resolve().parent,capture_output=True,timeout=15)
                self.assertEqual(child.returncode,77,child.stderr.decode(errors='replace'))
                self.assertEqual(path.read_bytes(),before)
                reopened=ManualQuestLedger(path)
                self.assertEqual(reopened.detail('a','daily_guild','donation')['input_request'],request)
                self.assertTrue(list(Path(folder).glob('*.tmp')))


if __name__=='__main__':unittest.main()
