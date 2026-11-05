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
        """A notification service with `capabilities` that shows it as number 7."""
        conn = mock_open.return_value
        accepted = Mock(body=(7,))
        accepted.header.message_type = MessageType.method_return
        conn.send_and_get_reply.side_effect = [Mock(body=(capabilities,)), accepted]
        return conn

    @patch("jeepney.io.blocking.open_dbus_connection")
    def test_shows_a_notification(self, mock_open):
        """The notification service accepting the call means it was shown, as the
        number it returns, with the markup kept where the service takes it."""
        conn = self._service(mock_open, ["body", "body-markup"])

        assert notify("EasySpeak 1.2.3", "<b>Voice</b> control &amp; more") == 7
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

        assert notify("EasySpeak", "<b>Voice</b> control &amp; more") == 7
        message = conn.send_and_get_reply.call_args.args[0]
        assert message.body[4] == "Voice control & more"

    @patch("jeepney.io.blocking.open_dbus_connection")
    def test_names_the_desktop_entry(self, mock_open):
        """The desktop entry lets the desktop keep EasySpeak's notifications
        together, under its name and icon."""
        conn = self._service(mock_open, ["body"])

        notify("EasySpeak", "Voice control")

        hints = conn.send_and_get_reply.call_args.args[0].body[6]
        assert hints == {"desktop-entry": ("s", "easyspeak")}

    @patch("jeepney.io.blocking.open_dbus_connection")
    def test_takes_the_place_of_an_earlier_one(self, mock_open):
        """Given an earlier notification's number, the service updates that one."""
        conn = self._service(mock_open, ["body"])

        notify("Dictation", "Warning: no keyboard", replaces=5)

        assert conn.send_and_get_reply.call_args.args[0].body[1] == 5

    @patch("jeepney.io.blocking.open_dbus_connection")
    def test_a_click_only_dismisses_it(self, mock_open):
        """A default action takes the click, so the desktop doesn't start
        EasySpeak again, which would greet once more."""
        conn = self._service(mock_open, ["body", "actions"])

        notify("EasySpeak", "Voice control")

        actions = conn.send_and_get_reply.call_args.args[0].body[5]
        assert actions == ["default", ""]

    @patch("jeepney.io.blocking.open_dbus_connection")
    def test_keeps_the_connection_open(self, mock_open):
        """All notifications go through one connection, which stays open, as the
        desktop removes an app's notifications once their connection is gone."""
        conn = mock_open.return_value
        capabilities = Mock(body=(["body"],))
        accepted = Mock(body=(7,))
        accepted.header.message_type = MessageType.method_return
        conn.send_and_get_reply.side_effect = [capabilities, accepted] * 2

        assert notify("EasySpeak", "one") == 7
        assert notify("EasySpeak", "two") == 7

        mock_open.assert_called_once_with(bus="SESSION")
        conn.close.assert_not_called()

    @patch("jeepney.io.blocking.open_dbus_connection")
    def test_opens_a_broken_connection_anew(self, mock_open):
        """A connection that broke, e.g. as the session bus restarted, is closed
        and replaced, so the notification still shows."""
        broken, fresh = Mock(), Mock()
        broken.send_and_get_reply.side_effect = ConnectionResetError("bus gone")
        accepted = Mock(body=(7,))
        accepted.header.message_type = MessageType.method_return
        fresh.send_and_get_reply.side_effect = [Mock(body=(["body"],)), accepted]
        mock_open.side_effect = [broken, fresh]

        assert notify("EasySpeak", "Voice control") == 7
        broken.close.assert_called_once_with()

    @patch("jeepney.io.blocking.open_dbus_connection", side_effect=KeyError("bus"))
    def test_without_a_session_bus(self, mock_open):
        """No session bus to talk to means no notification, not a crash."""
        assert notify("EasySpeak", "Voice control") == 0

    @patch("jeepney.io.blocking.open_dbus_connection")
    def test_refused_by_the_service(self, mock_open):
        """An error reply, e.g. no notification service running, means not shown."""
        conn = mock_open.return_value
        refused = Mock(body=())
        refused.header.message_type = MessageType.error
        conn.send_and_get_reply.side_effect = [refused, refused]

        assert notify("EasySpeak", "Voice control") == 0


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
        ("pending", "verbose"),
        [(COMMAND_PRESENT_VERBOSE, True), (COMMAND_PRESENT, False), (None, False)],
    )
    @patch("easyspeak.core.tray.subprocess.run")
    def test_started_keeps_a_request_for_details(self, mock_run, pending, verbose):
        """A second launch with `-v` while the first copy still loads turns on what
        `-v` does, before the greeting and the startup messages are reported."""
        mock_run.return_value = Mock(returncode=0)
        tray = Tray(speak=Mock())
        tray.take_command = Mock(return_value=pending)
        tray.greet = Mock()
        tray.report = Mock()

        tray.started()

        assert tray._verbose is verbose
        tray.greet.assert_called_once_with()
        tray.report.assert_called_once_with()

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
    """The ready greeting is spoken and shown; a second launch is greeted, too."""

    @patch("easyspeak.core.tray.notify", return_value=7)
    def test_greet_says_and_shows_it(self, mock_notify):
        """The greeting is spoken and shown, nothing more."""
        tray = Tray(speak=Mock())

        tray.greet()

        mock_notify.assert_called_once_with("EasySpeak", "Welcome! I'm ready.")
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


class TestReport:
    """With `-v`, each message logged becomes a notification, and its source is
    said."""

    @pytest.fixture(autouse=True)
    def _verbose(self):
        log.configure(logging.WARNING, verbose=True)

    @pytest.fixture
    def mock_notify(self):
        with patch("easyspeak.core.tray.notify", side_effect=itertools.count(1)) as m:
            yield m

    def test_shows_each_message_and_says_where_it_came_from(
        self, mock_notify, monkeypatch
    ):
        """Each message gets a notification titled with its source, a plugin
        named by its label; each source of a warning or error is said, then where
        the details are, once."""
        monkeypatch.setitem(sys.modules, "plugins.grid", Mock(LABEL="Mouse grid"))
        logging.getLogger("easyspeak.core.hotkey").warning("No readable keyboard")
        logging.getLogger("plugins.grid").error("Grid failed")
        tray = Tray(speak=Mock())

        assert tray.report() is True

        assert mock_notify.call_args_list == [
            call("Hold-to-dictate", "<b>Warning:</b> No readable keyboard", replaces=0),
            call("Mouse grid", "<b>Error:</b> Grid failed", replaces=0),
        ]
        tray._speak.assert_called_once_with(
            "Hold-to-dictate: there was a warning. Mouse grid: something went "
            "wrong. The details are in the desktop notification."
        )

    def test_shows_a_marked_message_without_saying_it(self, mock_notify):
        """Information meant for the desktop, such as the version line, is shown
        as it is, under EasySpeak's name, and not spoken."""
        logging.getLogger("easyspeak.core.main").info(
            "EasySpeak 1.2.3 on <GNOME>", extra=log.NOTIFY
        )
        tray = Tray(speak=Mock())

        assert tray.report() is False

        mock_notify.assert_called_once_with(
            "EasySpeak", "EasySpeak 1.2.3 on &lt;GNOME&gt;", replaces=0
        )
        tray._speak.assert_not_called()

    def test_counts_a_message_logged_several_times(self, mock_notify):
        """The same message in one go is one notification with a count, and one
        sentence."""
        for _ in range(3):
            logging.getLogger("easyspeak.core.noisefilter").warning("Filter stopped")
        tray = Tray(speak=Mock())

        tray.report()

        mock_notify.assert_called_once_with(
            "Noise filter",
            "<b>Warning:</b> Filter stopped (3×)",  # noqa: RUF001
            replaces=0,
        )
        tray._speak.assert_called_once_with(
            "Noise filter: there was a warning. "
            "The details are in the desktop notification."
        )

    def test_updates_the_notification_of_a_message_that_comes_again(self, mock_notify):
        """A message logged again later updates its notification, and isn't said
        once more."""
        noise = logging.getLogger("easyspeak.core.noisefilter")
        tray = Tray(speak=Mock())
        noise.warning("Filter stopped")
        tray.report()
        tray._speak.reset_mock()

        noise.warning("Filter stopped")

        assert tray.report() is False
        assert mock_notify.call_args == call(
            "Noise filter", "<b>Warning:</b> Filter stopped", replaces=1
        )
        tray._speak.assert_not_called()

    def test_without_notifications_still_says_where(self, monkeypatch):
        """Without a notification service, the source is still said, but not
        that the details are in a notification."""
        monkeypatch.setattr("easyspeak.core.tray.notify", Mock(return_value=0))
        logging.getLogger("easyspeak.core.speech").warning("No voice")
        tray = Tray(speak=Mock())

        tray.report()

        tray._speak.assert_called_once_with("Speech: there was a warning.")

    def test_names_an_unknown_source_easyspeak(self, mock_notify, monkeypatch):
        """A core module without a feature name, or a plugin without a label,
        reports as EasySpeak."""
        monkeypatch.setitem(sys.modules, "plugins.bare", Mock(spec=[]))
        logging.getLogger("easyspeak.core.main").warning("Odd")
        logging.getLogger("plugins.bare").warning("Odder")

        Tray(speak=Mock()).report()

        assert [c.args[0] for c in mock_notify.call_args_list] == [
            "EasySpeak",
            "EasySpeak",
        ]

    def test_without_verbose_drops_the_messages(self, mock_notify):
        """Without `-v`, nothing is shown or said, and nothing piles up."""
        log.configure(logging.WARNING)
        logging.getLogger("easyspeak.core.hotkey").warning("No readable keyboard")
        tray = Tray(speak=Mock())

        assert tray.report() is False

        mock_notify.assert_not_called()
        assert not log.pending

    def test_a_second_launch_with_v_shows_the_latest_messages(self, mock_notify):
        """A copy started without `-v` shows the latest messages once a second
        launch asks with `-v`, and reports from then on."""
        log.configure(logging.WARNING)
        tray = Tray(speak=Mock())
        logging.getLogger("easyspeak.core.hotkey").warning("No readable keyboard")
        tray.report()

        tray.present(details=True)

        assert mock_notify.call_args_list[-1] == call(
            "Hold-to-dictate", "<b>Warning:</b> No readable keyboard", replaces=0
        )
        logging.getLogger("easyspeak.core.speech").warning("No voice")
        assert tray.report() is True

    def test_poll_tells_the_loop_when_it_spoke(self, mock_notify):
        """A report that spoke makes the audio loop wait for it."""
        tray = Tray(speak=Mock())
        tray.take_command = Mock(return_value=None)
        logging.getLogger("easyspeak.core.hotkey").warning("No readable keyboard")

        assert tray.poll(Mock(), Mock()) is TrayAction.SPOKE
        assert tray.poll(Mock(), Mock()) is TrayAction.CONTINUE

    def test_a_second_launch_with_v_shows_nothing_twice(self, mock_notify):
        """A copy already reporting doesn't show its earlier messages again."""
        tray = Tray(speak=Mock())
        logging.getLogger("easyspeak.core.hotkey").warning("No readable keyboard")
        tray.report()
        mock_notify.reset_mock()

        tray.present(details=True)

        mock_notify.assert_called_once_with("EasySpeak", "Welcome! I'm ready.")
