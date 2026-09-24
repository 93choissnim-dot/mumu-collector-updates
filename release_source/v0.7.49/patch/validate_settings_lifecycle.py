"""Do not update an old settings window while a replacement is being built."""
from types import SimpleNamespace
from unittest.mock import Mock
import unittest
from fleet_ui import FleetUI
from ui_player_settings import PlayerSettings


class SettingsLifecycleTests(unittest.TestCase):
    def editor(self):
        e=PlayerSettings.__new__(PlayerSettings)
        e.window=Mock();e.window.winfo_exists.return_value=True
        e.ready=True;e.last_running=None;e._updating_state=False
        e.controls=[Mock()];e.save_button=Mock();e.copy_button=Mock();e.note=Mock()
        e.draft={'a':{}}
        return e

    def test_reentrant_redraw_and_unchanged_poll_do_not_reconfigure(self):
        e=self.editor();e.controls[0].configure.side_effect=lambda **_:e.set_running(False)
        e.set_running(False);e.set_running(False)
        e.controls[0].configure.assert_called_once_with(state='normal')
        self.assertFalse(e._updating_state)
        e.controls[0].configure.side_effect=None;e.set_running(True)
        e.controls[0].configure.assert_called_with(state='disabled')

    def test_destroyed_window_has_no_widget_updates(self):
        e=self.editor();e.window.winfo_exists.return_value=False;e.set_running(True)
        e.controls[0].configure.assert_not_called()

    def test_poll_ignores_old_editor_and_incomplete_controls(self):
        e=self.editor();app=SimpleNamespace(render_roster=Mock(),busy=Mock(return_value=True),
                                           fleet_window=Mock(),settings_editor=e)
        app.fleet_window.winfo_exists.return_value=True
        FleetUI.render_fleet_status(app);e.controls[0].configure.assert_not_called()
        e.window=app.fleet_window;e.ready=False
        FleetUI.render_fleet_status(app);e.controls[0].configure.assert_not_called()
        e.ready=True;FleetUI.render_fleet_status(app)
        e.controls[0].configure.assert_called_once_with(state='disabled')


if __name__=='__main__':unittest.main()
