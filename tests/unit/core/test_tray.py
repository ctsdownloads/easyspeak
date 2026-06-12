"""Tests for the GNOME panel-indicator bridge (core.tray)."""

import itertools
import sys
from unittest.mock import MagicMock, Mock, patch

# Mirror the other core tests: stub heavy deps so importing the package stays
# light (no model/GPU needed just to reach core.tray).
sys.modules.setdefault("pyaudio", MagicMock())
sys.modules.setdefault("openwakeword", MagicMock())
sys.modules.setdefault("openwakeword.model", MagicMock())
sys.modules.setdefault("faster_whisper", MagicMock())

from easyspeak.core.tray import (  # noqa: E402
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
        assert "/org/easyspeak/Grid" in cmd
        assert "org.easyspeak.Grid.SetState" in cmd
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
        tray = Tray()
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
        """A queued deactivate (request_sleep) sleeps even with no menu command."""
        tray = self._tray([None, COMMAND_QUIT])  # poll reads None, then _sleep
        tray.request_sleep()
        release, acquire = Mock(), Mock()

        with patch("easyspeak.core.tray.time.sleep"):
            action = tray.poll(release, acquire)

        assert action is TrayAction.QUIT
        release.assert_called_once()

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


class TestLifecycleHooks:
    """started()/stopped() both hide the indicator (only 'muted' shows it)."""

    @patch("easyspeak.core.tray.subprocess.run")
    def test_started_hides_indicator(self, mock_run):
        mock_run.return_value = Mock(returncode=0)
        Tray().started()

        assert mock_run.call_args.args[0][-1] == STATE_LISTENING

    @patch("easyspeak.core.tray.subprocess.run")
    def test_stopped_hides_indicator(self, mock_run):
        mock_run.return_value = Mock(returncode=0)
        Tray().stopped()

        assert mock_run.call_args.args[0][-1] == STATE_LISTENING
