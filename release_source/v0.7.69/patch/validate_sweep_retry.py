"""Revisit only repaired native-sweep recognition failures after upgrade."""
import unittest
from unittest.mock import Mock
import validate_dungeon_confirmation as cases

class SweepRetryTests(unittest.TestCase):
    def test_repaired_blocked_sweep_rechecks_current_state(self):
        for reason in ('일일 작업 버튼 확인 시간 초과: sweep_action',
                       '무료 열쇠 수령 후 소탕 화면과 버튼 확인 시간 초과'):
            with self.subTest(reason=reason):
                case=cases.DungeonConfirmationTests();case.setUp()
                try:
                    c=case.c;c.daily_step='equipment'
                    c.daily_checkpoint('blocked',reason=reason,failures=2)
                    c.daily_run_step('equipment','장비 보급소',lambda:c.daily_mark('equipment'))
                    self.assertTrue(c.daily_done('equipment'))
                finally:case.doCleanups()
    def test_unrelated_block_stays_blocked(self):
        case=cases.DungeonConfirmationTests();case.setUp()
        try:
            c=case.c;c.daily_step='equipment'
            c.daily_checkpoint('blocked',reason='unrelated',failures=2)
            c.daily_run_step('equipment','장비 보급소',lambda:c.daily_mark('equipment'))
            self.assertFalse(c.daily_done('equipment'))
        finally:case.doCleanups()

if __name__=='__main__':unittest.main()
