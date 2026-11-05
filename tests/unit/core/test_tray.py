"""Tests for the GNOME panel-indicator bridge (core.tray)."""

import itertools
import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, call, patch

import pytest
from easyspeak.core import log
from easyspeak.core.about import DOCS_URL
from easyspeak.core.tray import (
    ABOUT_HELPER,
    COMMAND_ABOUT,
    COMMAND_HELP,
    COMMAND_PRESENT,
    COMMAND_PRESENT_VERBOSE,
    COMMAND_QUIT,
    STATE_LISTENING,
    STATE_MUTED,
    TRAY_HELPER,
    Tray,
    TrayAction,
    notify,
)
from jeepney import HeaderFields, MessageType


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
        assert list(tmp_path.iterdir()) == []

    def test_keeps_a_command_written_while_reading(self, tmp_path):
        """A command that arrives between reading the file and deleting it, such
        as a second launch's request, is kept for the next poll, not deleted."""
        control = tmp_path / "control"
        control.write_text("about")
        tray = Tray(control_file=control)
        real_read = Path.read_text

        def read_then_a_request_arrives(path, *args, **kwargs):
            text = real_read(path, *args, **kwargs)
            control.write_text(COMMAND_PRESENT)
            return text

        with patch.object(Path, "read_text", read_then_a_request_arrives):
            assert tray.take_command() == COMMAND_ABOUT

        assert tray.take_command() == COMMAND_PRESENT

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
        """A 'help' command opens the docs URL via xdg-open and carries on.

        The browser runs in its own session, so Ctrl+C in EasySpeak's terminal
        doesn't close it.
        """
        self._started(mock_popen)
        tray = self._tray([COMMAND_HELP])

        assert tray.poll(Mock(), Mock()) is TrayAction.CONTINUE
        assert mock_popen.call_args.args[0] == ["xdg-open", DOCS_URL]
        assert mock_popen.call_args.kwargs["start_new_session"] is True

    @patch.dict("easyspeak.core.tray.os.environ", {}, clear=True)
    @patch("easyspeak.core.tray.on_gnome", return_value=True)
    @patch("easyspeak.core.tray.subprocess.Popen")
    def test_about_opens_once_and_closes(self, mock_popen, _gnome):
        """Showing an open About dialog again reopens it, so it comes to the front,
        and there is only ever one; closing ends just it.
        """
        self._started(mock_popen)
        mock_popen.return_value.poll.return_value = None  # the window stays up
        tray = self._tray([])

        tray.open_about()
        tray.open_about()

        assert mock_popen.call_count == 2
        mock_popen.return_value.terminate.assert_called_once()
        mock_popen.return_value.terminate.reset_mock()
        assert tray.about_open() is True
        assert tray.close_about() is True
        mock_popen.return_value.terminate.assert_called_once()
        assert tray.about_open() is False
        assert tray.close_about() is False

    @patch.dict("easyspeak.core.tray.os.environ", {}, clear=True)
    @patch("easyspeak.core.tray.on_gnome", return_value=True)
    @patch("easyspeak.core.tray.subprocess.Popen")
    def test_about_closed_by_hand_counts_as_closed(self, mock_popen, _gnome):
        """Once the user closed the dialog, closing it again has nothing to do."""
        self._started(mock_popen)
        mock_popen.return_value.poll.return_value = 0  # the window is gone
        tray = self._tray([])

        tray.open_about()

        assert tray.about_open() is False
        assert tray.close_about() is False
        mock_popen.return_value.terminate.assert_not_called()

    @patch("easyspeak.core.tray.shutil.which", return_value="/usr/bin/kdialog")
    @patch("easyspeak.core.tray.on_gnome", return_value=False)
    @patch("easyspeak.core.tray.subprocess.Popen")
    def test_about_uses_kdialog_outside_gnome(self, mock_popen, _gnome, _which):
        """Outside GNOME, kdialog shows the About information in the native look."""
        self._started(mock_popen)
        tray = self._tray([COMMAND_ABOUT])

        tray.poll(Mock(), Mock())

        assert mock_popen.call_count == 1
        cmd = mock_popen.call_args.args[0]
        assert cmd[:3] == ["kdialog", "--title", "About EasySpeak"]
        assert "--msgbox" in cmd

    @patch.dict("easyspeak.core.tray.os.environ", {}, clear=True)
    @patch("easyspeak.core.tray.shutil.which", return_value="/usr/bin/kdialog")
    @patch("easyspeak.core.tray.on_gnome", return_value=False)
    @patch("easyspeak.core.tray.subprocess.Popen")
    def test_about_falls_back_from_a_failing_kdialog(self, mock_popen, _gnome, _which):
        """When kdialog can't show it, the libadwaita dialog is tried next."""
        failing, opened = Mock(), Mock()
        failing.wait.return_value = 1
        opened.wait.side_effect = subprocess.TimeoutExpired(cmd="about", timeout=1.5)
        mock_popen.side_effect = [failing, opened]
        tray = self._tray([COMMAND_ABOUT])

        tray.poll(Mock(), Mock())

        launched = [c.args[0][0] for c in mock_popen.call_args_list]
        assert launched == ["kdialog", sys.executable]
        tray._speak.assert_not_called()

    @patch.dict("easyspeak.core.tray.os.environ", {}, clear=True)
    @patch("easyspeak.core.tray.shutil.which", return_value="/usr/bin/kdialog")
    @patch("easyspeak.core.tray.on_gnome", return_value=True)
    @patch("easyspeak.core.tray.subprocess.Popen")
    def test_about_keeps_libadwaita_on_gnome(self, mock_popen, _gnome, _which):
        """On GNOME the libadwaita dialog stays, even with kdialog installed."""
        self._started(mock_popen)
        tray = self._tray([COMMAND_ABOUT])

        tray.poll(Mock(), Mock())

        assert mock_popen.call_args.args[0] == [sys.executable, ABOUT_HELPER]

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
        """The About dialog needs GTK4/libadwaita, so it reuses the PyGObject
        interpreter the AT-SPI helper runs in when EASYSPEAK_ATSPI_PYTHON is set.
        """
        self._started(mock_popen)
        tray = self._tray([COMMAND_ABOUT])

        assert tray.poll(Mock(), Mock()) is TrayAction.CONTINUE
        cmd = mock_popen.call_args.args[0]
        assert cmd == ["/usr/bin/gtk-python", ABOUT_HELPER]

    @patch("easyspeak.core.tray.app_version", return_value="1.2.3")
    @patch("easyspeak.core.tray.notify", return_value=True)
    @patch("easyspeak.core.tray.subprocess.run")
    @patch("easyspeak.core.tray.subprocess.Popen")
    def test_about_without_gtk_tells_about_easyspeak(
        self, mock_popen, mock_run, mock_notify, mock_version, caplog
    ):
        """Without GTK 4/libadwaita the dialog can't open, so the user hears who
        EasySpeak is and finds the details in a notification instead.

        The cause is logged in one line; the helper's full stderr, traceback
        included, is kept for debug logging only.
        """
        caplog.set_level(logging.DEBUG)
        proc = mock_popen.return_value
        proc.wait.return_value = 1
        with tempfile.TemporaryFile() as errlog:
            errlog.write(
                b"Traceback (most recent call last):\n"
                b"ValueError: Namespace Gtk not available\n"
            )
            errlog.seek(0)
            tray = self._tray([COMMAND_ABOUT])

            with patch(
                "easyspeak.core.tray.tempfile.TemporaryFile", return_value=errlog
            ):
                assert tray.poll(Mock(), Mock()) is TrayAction.CONTINUE

        warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
        assert warnings == [
            "The About dialog couldn't open: ValueError: Namespace Gtk not available"
        ]
        assert "Traceback" in caplog.text
        assert mock_notify.call_args.args[0] == "EasySpeak 1.2.3"
        assert "GPL-3.0" in mock_notify.call_args.args[1]
        tray._speak.assert_called_once_with(
            "This is EasySpeak 1.2.3. The details are in the desktop notification."
        )
        mock_run.assert_not_called()  # no error chime: the user got what they asked

    @patch("easyspeak.core.tray.app_version", return_value="1.2.3")
    @patch("easyspeak.core.tray.notify", return_value=False)
    @patch("easyspeak.core.tray.subprocess.Popen", side_effect=OSError("no python"))
    def test_about_without_gtk_or_notifications_still_says_the_version(
        self, mock_popen, mock_notify, mock_version
    ):
        """Without a notification service either, the spoken summary remains."""
        tray = self._tray([COMMAND_ABOUT])

        assert tray.poll(Mock(), Mock()) is TrayAction.CONTINUE
        tray._speak.assert_called_once_with("This is EasySpeak 1.2.3.")

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
        tray._speak.assert_called_once_with(
            "Sorry, I couldn't open the documentation page."
        )


class TestNotify:
    """Desktop notifications over the freedesktop Notifications D-Bus API."""

    @staticmethod
    def _service(mock_open, capabilities):
        """A notification service with `capabilities` that accepts the call."""
        conn = mock_open.return_value.__enter__.return_value
        accepted = Mock(body=())
        accepted.header.message_type = MessageType.method_return
        conn.send_and_get_reply.side_effect = [Mock(body=(capabilities,)), accepted]
        return conn

    @patch("jeepney.io.blocking.open_dbus_connection")
    def test_shows_a_notification(self, mock_open):
        """The notification service accepting the call means it was shown, with
        the markup kept where the service takes it."""
        conn = self._service(mock_open, ["body", "body-markup"])

        assert notify("EasySpeak 1.2.3", "<b>Voice</b> control &amp; more") is True
        message = conn.send_and_get_reply.call_args.args[0]
        assert message.header.fields[HeaderFields.member] == "Notify"
        assert message.body[3:5] == (
            "EasySpeak 1.2.3",
            "<b>Voice</b> control &amp; more",
        )

    @patch("jeepney.io.blocking.open_dbus_connection")
    def test_takes_markup_out_where_the_service_shows_plain_text(self, mock_open):
        """A service without markup gets plain text, not tags and entities."""
        conn = self._service(mock_open, ["body"])

        assert notify("EasySpeak", "<b>Voice</b> control &amp; more") is True
        message = conn.send_and_get_reply.call_args.args[0]
        assert message.body[4] == "Voice control & more"

    @patch("jeepney.io.blocking.open_dbus_connection", side_effect=KeyError("bus"))
    def test_without_a_session_bus(self, mock_open):
        """No session bus to talk to means no notification, not a crash."""
        assert notify("EasySpeak", "Voice control") is False

    @patch("jeepney.io.blocking.open_dbus_connection")
    def test_refused_by_the_service(self, mock_open):
        """An error reply, e.g. no notification service running, means not shown."""
        conn = mock_open.return_value.__enter__.return_value
        refused = Mock(body=())
        refused.header.message_type = MessageType.error
        conn.send_and_get_reply.side_effect = [refused, refused]

        assert notify("EasySpeak", "Voice control") is False


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

    @pytest.mark.parametrize(
        ("pending", "details"),
        [(COMMAND_PRESENT_VERBOSE, True), (COMMAND_PRESENT, False), (None, False)],
    )
    @patch("easyspeak.core.tray.subprocess.run")
    def test_started_keeps_a_request_for_details(self, mock_run, pending, details):
        """A second launch with `-v` while the first copy still loads is answered
        by the startup greeting, details included."""
        mock_run.return_value = Mock(returncode=0)
        tray = Tray(speak=Mock())
        tray.take_command = Mock(return_value=pending)
        tray.greet = Mock()

        tray.started()

        tray.greet.assert_called_once_with(details=details)

    @patch("easyspeak.core.tray.subprocess.run")
    def test_started_discards_a_stale_command(self, mock_run):
        """A command left in the control file before startup is dropped, so it
        can't fire (e.g. pop the About dialog) the moment polling begins.
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


class TestOtherDesktops:
    """Outside GNOME a StatusNotifierItem helper serves the indicator."""

    @patch("easyspeak.core.tray.subprocess.run")
    def test_pushes_state_to_the_tray_helper(self, mock_run, monkeypatch):
        """On KDE Plasma the state goes to the helper instead of GNOME Shell."""
        monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
        mock_run.return_value = Mock(returncode=0)

        Tray().set_state(STATE_MUTED)

        cmd = mock_run.call_args.args[0]
        assert "org.easyspeak.Tray" in cmd
        assert "org.gnome.Shell" not in cmd

    @patch("easyspeak.core.tray.subprocess.run")
    def test_ubuntu_counts_as_gnome(self, mock_run, monkeypatch):
        """Ubuntu's "ubuntu:GNOME" desktop still uses the Shell extension."""
        monkeypatch.setenv("XDG_CURRENT_DESKTOP", "ubuntu:GNOME")
        mock_run.return_value = Mock(returncode=0)

        Tray().set_state(STATE_MUTED)

        assert "org.gnome.Shell" in mock_run.call_args.args[0]

    @patch("easyspeak.core.tray.subprocess.run")
    @patch("easyspeak.core.tray.subprocess.Popen")
    def test_started_launches_the_helper(self, mock_popen, mock_run, monkeypatch):
        """Startup runs the helper with our interpreter and the control file.

        It runs in its own session, so Ctrl+C in the terminal doesn't reach it.
        """
        monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
        mock_run.return_value = Mock(returncode=0)
        tray = Tray(control_file="/tmp/control")

        tray.started()

        cmd = mock_popen.call_args.args[0]
        assert cmd == [sys.executable, TRAY_HELPER, "/tmp/control"]
        assert mock_popen.call_args.kwargs["start_new_session"] is True

    @patch("easyspeak.core.tray.subprocess.run")
    @patch("easyspeak.core.tray.subprocess.Popen")
    def test_started_skips_the_helper_on_gnome(self, mock_popen, mock_run):
        """On GNOME the Shell extension is the tray, so no helper is started."""
        mock_run.return_value = Mock(returncode=0)

        Tray().started()

        mock_popen.assert_not_called()

    @patch("easyspeak.core.tray.subprocess.run")
    @patch("easyspeak.core.tray.subprocess.Popen")
    def test_stopped_ends_the_helper(self, mock_popen, mock_run, monkeypatch):
        """Quitting takes the tray icon down with the daemon."""
        monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
        mock_run.return_value = Mock(returncode=0)
        tray = Tray()
        tray.started()

        tray.stopped()

        mock_popen.return_value.terminate.assert_called_once()

    @patch("easyspeak.core.tray.subprocess.run")
    @patch("easyspeak.core.tray.subprocess.Popen", side_effect=OSError("gone"))
    def test_helper_failing_to_start_is_not_fatal(
        self, mock_popen, mock_run, monkeypatch
    ):
        """The daemon still starts listening when the helper can't be launched."""
        monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
        mock_run.return_value = Mock(returncode=0)
        tray = Tray(speak=Mock())

        tray.started()
        tray.stopped()

        tray._speak.assert_called_once_with("Welcome! I'm ready.")


class TestGreeting:
    """The ready greeting is spoken and shown, with details when verbose."""

    @pytest.fixture(autouse=True)
    def _session(self, monkeypatch):
        monkeypatch.delenv("EASYSPEAK_LOG_LEVEL", raising=False)
        monkeypatch.setenv("XDG_CURRENT_DESKTOP", "X-Cinnamon")
        monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
        monkeypatch.setattr("easyspeak.core.tray.app_version", lambda: "1.2.3")
        monkeypatch.setattr("easyspeak.core.tray.LANGUAGE", "en")

    @patch("easyspeak.core.tray.notify", return_value=True)
    def test_greet_shows_the_greeting(self, mock_notify):
        """Not verbose, the notification just repeats the greeting, problems or not."""
        log.problems.append((logging.ERROR, "Speech unavailable"))
        tray = Tray(speak=Mock())

        tray.greet()

        mock_notify.assert_called_once_with("EasySpeak", "Welcome! I'm ready.")
        tray._speak.assert_called_once_with("Welcome! I'm ready.")

    @patch("easyspeak.core.tray.notify", return_value=True)
    def test_greet_verbose_shows_the_details(self, mock_notify, monkeypatch):
        """Verbose, the greeting stays the first line, as the pop-up shows little
        more; the version, desktop and language follow, then the problems one per
        line, labelled in bold and escaped for the notification's markup. The lines
        are split by Unicode's line separator, as GNOME turns newlines into spaces.
        An error is a problem."""
        monkeypatch.setenv("EASYSPEAK_LOG_LEVEL", "DEBUG")
        log.problems.extend(
            [
                (logging.WARNING, "No readable keyboard"),
                (logging.ERROR, "Speech unavailable (no <voice> & no player)"),
            ]
        )
        tray = Tray(speak=Mock())

        tray.greet()

        mock_notify.assert_called_once_with(
            "EasySpeak",
            "Welcome! I'm ready.\u2028"
            "<b>Version</b> 1.2.3, <b>desktop</b> X-Cinnamon (x11), <b>language</b> en.\u2028"
            "<b>Warning:</b> No readable keyboard\u2028"
            "<b>Error:</b> Speech unavailable (no &lt;voice&gt; &amp; no player)",
        )
        assert tray._speak.call_args_list == [
            call("Welcome! I'm ready."),
            call("I ran into problems. The details are in the desktop notification."),
        ]

    @patch("easyspeak.core.tray.notify", return_value=True)
    def test_greet_with_only_warnings_says_so(self, mock_notify):
        """Warnings alone, such as no keyboard for the hotkey, aren't announced as
        problems."""
        log.problems.append((logging.WARNING, "No readable keyboard"))
        tray = Tray(speak=Mock())

        tray.greet(details=True)

        assert tray._speak.call_args_list == [
            call("Welcome! I'm ready."),
            call("There were warnings. The details are in the desktop notification."),
        ]

    @patch("easyspeak.core.tray.notify", return_value=True)
    def test_greet_details_without_problems(self, mock_notify, monkeypatch):
        """Asked for details, an unknown desktop is named so, and without problems
        nothing more is said."""
        monkeypatch.delenv("XDG_CURRENT_DESKTOP")
        monkeypatch.delenv("XDG_SESSION_TYPE")
        tray = Tray(speak=Mock())

        tray.greet(details=True)

        assert mock_notify.call_args.args[1] == (
            "Welcome! I'm ready.\u2028"
            "<b>Version</b> 1.2.3, <b>desktop</b> unknown, <b>language</b> en."
        )
        tray._speak.assert_called_once_with("Welcome! I'm ready.")

    @patch("easyspeak.core.tray.notify", return_value=False)
    def test_greet_without_notifications_doesnt_point_to_one(self, mock_notify):
        """Without a notification service, the greeting doesn't mention one."""
        log.problems.append((logging.ERROR, "Speech unavailable"))
        tray = Tray(speak=Mock())

        tray.greet(details=True)

        tray._speak.assert_called_once_with("Welcome! I'm ready.")

    @pytest.mark.parametrize(
        ("command", "details"),
        [(COMMAND_PRESENT, False), (COMMAND_PRESENT_VERBOSE, True)],
    )
    def test_poll_presents_for_a_second_launch(self, command, details):
        """A second launch makes the running copy greet, while it keeps listening,
        and tells the audio loop it spoke, so it doesn't record the greeting."""
        tray = Tray(speak=Mock())
        tray.take_command = Mock(return_value=command)
        tray.present = Mock()
        release, acquire = Mock(), Mock()

        assert tray.poll(release, acquire) is TrayAction.SPOKE
        tray.present.assert_called_once_with(details=details)
        release.assert_not_called()

    def test_second_launch_overrides_a_pending_sleep(self):
        """A second launch right after "go to sleep" keeps EasySpeak listening,
        as the later request wins."""
        tray = Tray(speak=Mock())
        tray.take_command = Mock(side_effect=[COMMAND_PRESENT, None, COMMAND_QUIT])
        tray.set_state = Mock(return_value=True)
        tray.present = Mock()
        tray.request_sleep()
        release, acquire = Mock(), Mock()

        assert tray.poll(release, acquire) is TrayAction.SPOKE
        assert tray.poll(release, acquire) is TrayAction.CONTINUE
        release.assert_not_called()

    def test_second_launch_wakes_a_sleeping_copy(self):
        """Asleep, a second launch reopens the mic and greets, as starting
        EasySpeak means wanting it to listen."""
        tray = Tray(speak=Mock())
        tray.take_command = Mock(side_effect=["mute", COMMAND_PRESENT_VERBOSE])
        tray.set_state = Mock(return_value=True)
        tray.present = Mock()
        release, acquire = Mock(), Mock()

        assert tray.poll(release, acquire) is TrayAction.RESUME
        acquire.assert_called_once_with()
        tray.set_state.assert_called_with(STATE_LISTENING)
        tray.present.assert_called_once_with(details=True)

    @patch("easyspeak.core.tray.notify", return_value=True)
    def test_present_brings_the_about_dialog_forward(self, mock_notify):
        """An open About dialog is opened again, which brings it to the front."""
        tray = Tray(speak=Mock())
        tray.about_open = Mock(return_value=True)
        tray.open_about = Mock()

        tray.present()

        tray.open_about.assert_called_once_with()
        tray._speak.assert_called_once_with("Welcome! I'm ready.")

    @patch("easyspeak.core.tray.notify", return_value=True)
    def test_present_without_a_window_only_greets(self, mock_notify):
        """With no About dialog showing, none is opened."""
        tray = Tray(speak=Mock())
        tray.open_about = Mock()

        tray.present()

        tray.open_about.assert_not_called()
        mock_notify.assert_called_once()
