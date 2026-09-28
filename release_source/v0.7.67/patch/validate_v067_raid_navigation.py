"""Animation before navigation must re-observe without retrying an input."""
import unittest
from unittest.mock import Mock
import validate_raid_retry as fixture
from collector import Halt
from daily_execution import OutcomeUnknown

class RaidNavigationTests(unittest.TestCase):
    setUp=fixture.RaidRetryTests.setUp

    def test_transient_raid_button_loss_recovers_before_any_input(self):
        c=self.c;capture=c.screen;reads=0
        def animation():
            nonlocal reads
            reads+=1
            if reads==1:return fixture.page('daily_guild_battle')
            return capture()
        c.screen=animation
        c.daily_combat=Mock(return_value=(self.map,True))
        c.daily_guild_raid()
        self.assertEqual(self.clicked,['daily_guild_battle','daily_raid_map','daily_raid_detail'])
        self.assertEqual(c.daily_work_attempts,1)

    def test_missing_navigation_button_times_out_without_input(self):
        c=self.c;self.current=fixture.page('daily_guild_battle')
        with self.assertRaises(Halt):c.daily_guild_raid()
        self.assertEqual(self.clicked,[])
        self.assertIsNone(c.daily_detail().get('pending'))
        self.assertLess(self.clock,35)

    def test_transport_failure_is_never_retried(self):
        c=self.c;c.device.click=Mock(side_effect=Halt('transport lost'))
        with self.assertRaisesRegex(Halt,'transport lost'):c.daily_guild_raid()
        self.assertEqual(c.device.click.call_count,1)
        self.assertIsNone(c.daily_detail().get('pending'))

    def test_repeated_preinput_loss_is_bounded(self):
        c=self.c;c.daily_ready=Mock(return_value=self.guild)
        c.screen=lambda:fixture.page('daily_guild_battle')
        with self.assertRaises(Halt):c.daily_guild_raid()
        self.assertEqual(self.clicked,[])
        self.assertLessEqual(c.daily_ready.call_count,4)

if __name__=='__main__':unittest.main()
