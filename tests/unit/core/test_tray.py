"""Tests for the GNOME panel-indicator bridge (core.tray)."""

import itertools
import subprocess
import sys
import tempfile
from unittest.mock import Mock, call, patch

from easyspeak.core.about import DOCS_URL
from easyspeak.core.tray import (
    ABOUT_HELPER,
    COMMAND_ABOUT,
    COMMAND_HELP,
    COMMAND_QUIT,
    STATE_LISTENING,
    STATE_MUTED,
    Tray,
    TrayAction,
)


class TestSetState:
    """Tests for pushing display state to the panel indicator over D-Bus."""

    @patch("easyspeak.core.tray.subprocess.run")
    def test_issues_gdbus_setstate_call(self, mock_run):
        """set_state calls SetState on the extension's object with the state arg."""
        mock_run.return_value = Mock(returncode=0)

        assert Tray().set_state(STATE_LISTENING) is True

        cmd = mock_run.call_args.args[0]
        assert cmd[0] == "gdbus"
        assert "org.gnome.Shell" in cmd
        assert "/org/easyspeak/Desktop" in cmd
        assert "org.easyspeak.Desktop.SetState" in cmd
        assert cmd[-1] == STATE_LISTENING

    @patch("easyspeak.core.tray.subprocess.run")
    def test_returns_false_when_call_fails(self, mock_run):
        """A non-zero gdbus exit (e.g. extension not running) reports failure."""
        mock_run.return_value = Mock(returncode=1)

        assert Tray().set_state(STATE_LISTENING) is False

    @patch("easyspeak.core.tray.subprocess.run", side_effect=OSError("no gdbus"))
    def test_swallows_missing_gdbus(self, mock_run):
        """On a non-GNOME desktop (no gdbus) set_state degrades to a no-op."""
        assert Tray().set_state(STATE_LISTENING) is False

    @patch(
        "easyspeak.core.tray.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="gdbus", timeout=5),
    )
    def test_reports_failure_on_timeout(self, mock_run):
        """A wedged session bus times out and reports failure instead of hanging
        the audio loop."""
        assert Tray().set_state(STATE_LISTENING) is False


class TestTakeCommand:
    """Tests for consuming one-shot menu commands from the control file."""

    def test_reads_and_clears_command(self, tmp_path):
        """A pending command is returned and the file removed (fires once)."""
        control = tmp_path / "control"
        control.write_text("quit\n")
        tray = Tray(control_file=control)

        assert tray.take_command() == COMMAND_QUIT
        assert not control.exists()

    def test_returns_none_when_absent(self, tmp_path):
        """No control file (the common idle case) yields None and no error."""
        tray = Tray(control_file=tmp_path / "control")

        assert tray.take_command() is None

    def test_returns_none_for_blank_file(self, tmp_path):
        """A blank command is treated as none, and the file is still cleared."""
        control = tmp_path / "control"
        control.write_text("   \n")
        tray = Tray(control_file=control)

        assert tray.take_command() is None
        assert not control.exists()

    def test_swallows_oserror_reading_control_file(self, tmp_path):
        """An unreadable control file (here a directory, so read_text raises
        OSError) yields None rather than crashing the poll loop."""
        control = tmp_path / "control"
        control.mkdir()  # exists() is True, but read_text() raises OSError
        tray = Tray(control_file=control)

        assert tray.take_command() is None

    def test_returns_command_even_when_unlink_fails(self, tmp_path):
        """A command read successfully isn't dropped if the delete fails (e.g.
        the file vanished in a race between read and unlink)."""
        control = tmp_path / "control"
        control.write_text("unmute\n")
        tray = Tray(control_file=control)

        with patch("easyspeak.core.tray.Path.unlink", side_effect=OSError("gone")):
            assert tray.take_command() == "unmute"


class TestPoll:
    """Tests for the per-iteration command dispatch and asleep lifecycle.

    ``take_command``/``set_state`` are replaced on the instance so the sequence
    of commands is fully controlled without touching the filesystem or gdbus.
    """

    def _tray(self, commands):
        tray = Tray(speak=Mock())
        tray.take_command = Mock(side_effect=commands)
        tray.set_state = Mock()
        return tray

    def test_continue_when_nothing_pending(self):
        """No command and no queued sleep means carry on reading audio."""
        tray = self._tray([None])

        assert tray.poll(Mock(), Mock()) is TrayAction.CONTINUE

    def test_quit_command(self):
        """A 'quit' menu command asks the loop to exit; the mic is untouched."""
        tray = self._tray([COMMAND_QUIT])
        release, acquire = Mock(), Mock()

        assert tray.poll(release, acquire) is TrayAction.QUIT
        release.assert_not_called()
        acquire.assert_not_called()

    def test_mute_releases_then_reactivate_reopens(self):
        """A 'mute' releases the mic, shows muted, then 'unmute' reopens it and
        resumes."""
        tray = self._tray(["mute", "unmute"])
        release, acquire = Mock(), Mock()

        with patch("easyspeak.core.tray.time.sleep"):
            action = tray.poll(release, acquire)

        assert action is TrayAction.RESUME
        release.assert_called_once()
        acquire.assert_called_once()
        tray.set_state.assert_any_call(STATE_MUTED)
        tray.set_state.assert_any_call(STATE_LISTENING)
        # A button mute confirms the deactivation; reactivation greets.
        tray._speak.assert_any_call("Voice control turned off.")
        tray._speak.assert_any_call("Welcome! I'm ready.")

    def test_idle_loop_sleeps_until_a_command_arrives(self):
        """While asleep, empty polls sleep and loop; a later 'unmute' wakes it."""
        tray = self._tray(["mute", None, None, "unmute"])
        release, acquire = Mock(), Mock()

        with patch("easyspeak.core.tray.time.sleep") as mock_sleep:
            action = tray.poll(release, acquire)

        assert action is TrayAction.RESUME
        # Two empty iterations idled before the unmute command.
        assert mock_sleep.call_count == 2
        acquire.assert_called_once()

    def test_quit_while_asleep(self):
        """Quitting from the menu while asleep exits without reopening the mic."""
        tray = self._tray(["mute", COMMAND_QUIT])
        release, acquire = Mock(), Mock()

        with patch("easyspeak.core.tray.time.sleep"):
            action = tray.poll(release, acquire)

        assert action is TrayAction.QUIT
        release.assert_called_once()
        acquire.assert_not_called()

    def test_request_sleep_triggers_sleep_without_a_command(self):
        """A queued deactivate (request_sleep) sleeps even with no menu command,
        and stays silent: the sleep plugin already announced this voice path."""
        tray = self._tray([None, COMMAND_QUIT])  # poll reads None, then sleep
        tray.request_sleep()
        release, acquire = Mock(), Mock()

        with patch("easyspeak.core.tray.time.sleep"):
            action = tray.poll(release, acquire)

        assert action is TrayAction.QUIT
        release.assert_called_once()
        # Voice path: no spoken confirmation (the plugin already spoke).
        assert call("Voice control turned off.") not in tray._speak.call_args_list

    def test_sleep_request_is_consumed_once(self):
        """After waking, a single request_sleep doesn't re-trigger on next poll."""
        tray = self._tray([None, "unmute", None])
        tray.request_sleep()
        release, acquire = Mock(), Mock()

        with patch("easyspeak.core.tray.time.sleep"):
            first = tray.poll(release, acquire)  # sleeps, then unmute -> RESUME
        second = tray.poll(release, acquire)  # flag cleared -> CONTINUE

        assert first is TrayAction.RESUME
        assert second is TrayAction.CONTINUE

    def test_refuses_to_sleep_when_indicator_unavailable(self):
        """If the muted state can't be pushed (no working indicator), stay awake
        rather than release the mic with no menu to reactivate from."""
        tray = self._tray(["mute"])
        tray.set_state = Mock(return_value=False)
        release, acquire = Mock(), Mock()

        action = tray.poll(release, acquire)

        assert action is TrayAction.CONTINUE
        release.assert_not_called()
        acquire.assert_not_called()
        # Sleep couldn't engage, so explain rather than leave the user guessing.
        tray._speak.assert_any_call(
            "I couldn't turn voice control off, so I'll keep listening."
        )

    def test_repushes_muted_state_while_asleep(self):
        """The muted state is re-asserted periodically so the indicator recovers
        after a GNOME Shell / extension reload."""
        tray = self._tray(["mute", None, None, "unmute"])
        release, acquire = Mock(), Mock()

        # monotonic jumps far past MUTED_REPUSH_INTERVAL each call, so the
        # threshold is crossed on every idle iteration.
        with (
            patch("easyspeak.core.tray.time.sleep"),
            patch(
                "easyspeak.core.tray.time.monotonic",
                side_effect=itertools.count(0, 100),
            ),
        ):
            action = tray.poll(release, acquire)

        assert action is TrayAction.RESUME
        muted_pushes = [
            c for c in tray.set_state.call_args_list if c.args == (STATE_MUTED,)
        ]
        # Entry push + at least one periodic re-push while idling.
        assert len(muted_pushes) >= 2


class TestMenuActions:
    """Tests for the fire-and-forget Help/About menu commands.

    Both spawn a detached helper; ``subprocess.Popen`` is patched so nothing
    is actually launched.
    """

    def _tray(self, commands):
        tray = Tray(speak=Mock())
        tray.take_command = Mock(side_effect=commands)
        tray.set_state = Mock()
        return tray

    @staticmethod
    def _started(mock_popen):
        """Make the patched Popen behave like a helper that opened its window.

        A real GUI keeps running, so its wait() times out within the startup
        grace; mirror that so the success path is exercised rather than the
        failure path (a bare Mock's wait() would read as a non-zero exit).
        """
        mock_popen.return_value.wait.side_effect = subprocess.TimeoutExpired(
            cmd="helper", timeout=1.5
        )

    @patch("easyspeak.core.tray.subprocess.Popen")
    def test_help_opens_docs_in_default_browser(self, mock_popen):
        """A 'help' command opens the docs URL via xdg-open and carries on."""
        self._started(mock_popen)
        tray = self._tray([COMMAND_HELP])

        assert tray.poll(Mock(), Mock()) is TrayAction.CONTINUE
        assert mock_popen.call_args.args[0] == ["xdg-open", DOCS_URL]

    @patch.dict("easyspeak.core.tray.os.environ", {}, clear=True)
    @patch("easyspeak.core.tray.subprocess.Popen")
    def test_about_falls_back_to_own_interpreter(self, mock_popen):
        """With no PyGObject interpreter configured, About runs in our own."""
        self._started(mock_popen)
        tray = self._tray([COMMAND_ABOUT])

        assert tray.poll(Mock(), Mock()) is TrayAction.CONTINUE
        cmd = mock_popen.call_args.args[0]
        assert cmd == [sys.executable, ABOUT_HELPER]

    @patch.dict(
        "easyspeak.core.tray.os.environ",
        {"EASYSPEAK_ATSPI_PYTHON": "/usr/bin/gtk-python"},
        clear=True,
    )
    @patch("easyspeak.core.tray.subprocess.Popen")
    def test_about_uses_the_pygobject_interpreter_when_set(self, mock_popen):
        """The About window needs GTK4/libadwaita, so it reuses the PyGObject
        interpreter the AT-SPI helper runs in when EASYSPEAK_ATSPI_PYTHON is set.
        """
        self._started(mock_popen)
        tray = self._tray([COMMAND_ABOUT])

        assert tray.poll(Mock(), Mock()) is TrayAction.CONTINUE
        cmd = mock_popen.call_args.args[0]
        assert cmd == ["/usr/bin/gtk-python", ABOUT_HELPER]

    @patch("easyspeak.core.tray.subprocess.run")
    @patch("easyspeak.core.tray.subprocess.Popen")
    def test_failed_helper_is_reported_not_swallowed(self, mock_popen, mock_run):
        """A helper that exits non-zero at startup logs its stderr, plays the
        error chime, and speaks an apology, rather than failing silently."""
        proc = mock_popen.return_value
        proc.wait.return_value = 1
        with tempfile.TemporaryFile() as errlog:
            errlog.write(b"ModuleNotFoundError: No module named 'gi'\n")
            errlog.seek(0)
            tray = self._tray([COMMAND_ABOUT])

            with patch(
                "easyspeak.core.tray.tempfile.TemporaryFile", return_value=errlog
            ):
                assert tray.poll(Mock(), Mock()) is TrayAction.CONTINUE

        assert mock_run.call_args.args[0][0] == "paplay"
        tray._speak.assert_called_once()
        assert "About window" in tray._speak.call_args.args[0]

    @patch("easyspeak.core.tray.subprocess.Popen")
    def test_help_does_not_release_the_mic(self, mock_popen):
        """Help is a side effect only; it never touches the sleep lifecycle."""
        self._started(mock_popen)
        tray = self._tray([COMMAND_HELP])
        release, acquire = Mock(), Mock()

        tray.poll(release, acquire)

        release.assert_not_called()
        acquire.assert_not_called()

    @patch.dict("easyspeak.core.tray.os.environ", {}, clear=True)
    @patch("easyspeak.core.tray.subprocess.Popen")
    def test_menu_actions_work_while_asleep(self, mock_popen):
        """Help/About fire from the idle loop (where the menu is actually
        shown), then a later 'unmute' wakes the daemon.
        """
        self._started(mock_popen)
        tray = self._tray(["mute", COMMAND_HELP, COMMAND_ABOUT, "unmute"])
        release, acquire = Mock(), Mock()

        with patch("easyspeak.core.tray.time.sleep"):
            action = tray.poll(release, acquire)

        assert action is TrayAction.RESUME
        spawned = [c.args[0][0] for c in mock_popen.call_args_list]
        assert spawned == ["xdg-open", sys.executable]
        acquire.assert_called_once()

    @patch("easyspeak.core.tray.subprocess.run")
    @patch("easyspeak.core.tray.subprocess.Popen", side_effect=OSError("no xdg-open"))
    def test_missing_helper_binary_is_reported(self, mock_popen, mock_run):
        """A helper that can't even launch (missing binary) chimes and speaks
        an apology but doesn't disturb the audio loop.
        """
        tray = self._tray([COMMAND_HELP])

        assert tray.poll(Mock(), Mock()) is TrayAction.CONTINUE
        assert mock_run.call_args.args[0][0] == "paplay"
        tray._speak.assert_called_once()


class TestLifecycleHooks:
    """started()/stopped() both hide the indicator (only 'muted' shows it)."""

    @patch("easyspeak.core.tray.subprocess.run")
    def test_started_hides_indicator(self, mock_run):
        mock_run.return_value = Mock(returncode=0)
        Tray().started()

        assert mock_run.call_args.args[0][-1] == STATE_LISTENING

    @patch("easyspeak.core.tray.subprocess.run")
    def test_started_greets(self, mock_run):
        """Startup speaks the ready greeting, same as reactivation."""
        mock_run.return_value = Mock(returncode=0)
        tray = Tray(speak=Mock())

        tray.started()

        tray._speak.assert_called_once_with("Welcome! I'm ready.")

    @patch("easyspeak.core.tray.subprocess.run")
    def test_started_discards_a_stale_command(self, mock_run):
        """A command left in the control file before startup is dropped, so it
        can't fire (e.g. pop the About window) the moment polling begins.
        """
        mock_run.return_value = Mock(returncode=0)
        tray = Tray()
        tray.take_command = Mock()

        tray.started()

        tray.take_command.assert_called_once()

    @patch("easyspeak.core.tray.subprocess.run")
    def test_stopped_hides_indicator(self, mock_run):
        mock_run.return_value = Mock(returncode=0)
        Tray().stopped()

        assert mock_run.call_args.args[0][-1] == STATE_LISTENING
