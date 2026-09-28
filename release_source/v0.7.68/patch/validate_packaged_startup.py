"""Keep legacy updater startup bounded while retaining packaged regression gates."""
from pathlib import Path
import tempfile,unittest
from unittest.mock import patch
from frozen_entry import health_check

class StartupUIReached(Exception):pass
class RegressionEntered(Exception):pass

class PackagedStartupTests(unittest.TestCase):
    def run_to_boundary(self,full_ui):
        with tempfile.TemporaryDirectory() as tmp, \
             patch('customtkinter.CTk',side_effect=StartupUIReached), \
             patch('unittest.TestSuite.run',side_effect=RegressionEntered):
            # Real packaged vision/assets checks execute before the UI boundary.
            health_check(Path(tmp)/'health.json',full_ui=full_ui)

    def test_legacy_update_startup_reaches_ui_without_running_release_test_suites(self):
        with self.assertRaises(StartupUIReached):self.run_to_boundary(False)

    def test_release_health_still_runs_packaged_regression_suites(self):
        with self.assertRaises(RegressionEntered):self.run_to_boundary(True)

if __name__=='__main__':unittest.main()
