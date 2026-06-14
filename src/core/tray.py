"""GNOME panel-indicator bridge and asleep-state lifecycle for the daemon.

The daemon is voice-first and otherwise headless; this module gives it a
top-panel microphone icon (served by the bundled ``easyspeak-grid@local`` GNOME
Shell extension) and owns everything about it so the audio loop in ``core.main``
stays about audio. It runs without a D-Bus server of its own via two
one-directional channels:

* daemon -> icon: state is pushed for display via a one-shot ``gdbus call``
  (the same path the mouse-grid plugin uses to drive the extension).
* icon -> daemon: the extension's menu writes a single command to a control
  file; the controller consumes it. The audio loop already wakes every ~80ms on
  a read, so a cheap file probe per iteration is enough — no GLib loop needed.

The indicator is shown only while the assistant is asleep (deactivated); while
running it stays hidden because GNOME's own microphone privacy icon already
signals the open mic.
"""

import contextlib
import enum
import logging
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Display states pushed to the indicator. The extension owns the icon/label
# mapping; it shows the indicator only for "muted" and hides it otherwise.
STATE_LISTENING = "listening"
STATE_MUTED = "muted"

# Menu commands the extension writes into the control file for the daemon.
COMMAND_QUIT = "quit"
COMMAND_MUTE = "mute"
COMMAND_UNMUTE = "unmute"

# Shared with the extension's ScreenshotManager, which creates ~/.cache/easyspeak.
CONTROL_FILE = Path.home() / ".cache" / "easyspeak" / "control"

# How long to idle between control-file probes while the assistant is asleep.
SLEEP_POLL_INTERVAL = 0.2

# How often to re-assert the muted state while asleep, so the indicator recovers
# if GNOME Shell or the extension reloads (which leaves it hidden by default).
MUTED_REPUSH_INTERVAL = 5.0

# Cap the gdbus call so a wedged session bus can't hang the audio loop.
GDBUS_TIMEOUT = 5.0


class TrayAction(enum.Enum):
    """What ``Tray.poll`` is telling the audio loop to do next."""

    CONTINUE = "continue"  # nothing happened; read audio as usual
    RESUME = "resume"  # woke from sleep; restart the listen iteration
    QUIT = "quit"  # exit the daemon


class Tray:
    """Owns the EasySpeak panel indicator and the asleep (deactivated) lifecycle.

    The audio loop calls :meth:`poll` once per iteration; the controller pushes
    display state, consumes menu commands, and — when deactivated — runs the
    idle loop itself, using caller-supplied callbacks to release and reacquire
    the microphone. It never touches audio directly.

    Best-effort throughout: on a non-GNOME desktop (no ``gdbus``/extension) the
    state pushes simply fail and the daemon carries on, mirroring how the
    mouse-grid plugin tolerates a missing extension.
    """

    def __init__(self, control_file=CONTROL_FILE, speak=None):
        """Set up the controller, optionally with a spoken-feedback callback.

        ``speak`` defaults to a no-op so the tray works headless and in tests.
        """
        self._control_file = Path(control_file)
        self._sleep_requested = False
        # Spoken feedback callback (core.speak). The plugin only announces the
        # *attempt* ("Going to sleep."); the tray confirms or, when it can't
        # actually sleep, explains — since only it knows whether sleep engaged.
        # Defaults to a no-op so the tray works headless and in tests.
        self._speak = speak or (lambda _text: None)

    # --- lifecycle hooks called by the daemon ---

    def started(self):
        """Daemon is up and listening; ensure the indicator is hidden."""
        self.set_state(STATE_LISTENING)

    def stopped(self):
        """Daemon is exiting; hide the indicator so no stale icon is left."""
        self.set_state(STATE_LISTENING)

    def request_sleep(self):
        """Queue a deactivate (e.g. the "go to sleep" voice command).

        The mic is released at the audio loop's next :meth:`poll`, after the
        current command finishes.
        """
        self._sleep_requested = True

    def poll(self, release_mic, acquire_mic):
        """Act on any pending menu command or queued sleep request.

        ``release_mic`` / ``acquire_mic`` are zero-arg callbacks that close and
        reopen the input stream; the controller calls them around the asleep
        idle loop so this module stays out of the audio internals. Returns a
        :class:`TrayAction` for the audio loop to dispatch on.
        """
        command = self.take_command()
        if command == COMMAND_QUIT:
            return TrayAction.QUIT
        if command == COMMAND_MUTE or self._sleep_requested:
            self._sleep_requested = False
            return self._sleep(release_mic, acquire_mic)
        return TrayAction.CONTINUE

    # --- internals ---

    def _sleep(self, release_mic, acquire_mic):
        """Release the mic and idle until the tray asks to resume or quit.

        Pushes the muted state first and refuses to sleep unless it lands:
        reactivation only ever arrives via the extension's menu, so releasing
        the mic while the indicator is missing (no GNOME/extension) would strand
        the daemon with no way back. While asleep the muted state is re-asserted
        every ``MUTED_REPUSH_INTERVAL`` seconds so the icon recovers if GNOME
        Shell or the extension reloads (it would otherwise come back hidden).

        Freeing the stream also clears GNOME's privacy microphone indicator, an
        OS-level 'not listening' cue alongside our own muted glyph.
        """
        if not self.set_state(STATE_MUTED):
            logger.warning(
                "Tray indicator unavailable; staying awake so you keep a way to "
                "reactivate."
            )
            self._speak(
                "I couldn't reach the tray, so I'll stay awake and keep listening."
            )
            return TrayAction.CONTINUE
        release_mic()
        logger.info("Muted; microphone released. Waiting for reactivation...")
        self._speak("Reactivate me from the tray when you need me.")
        next_repush = time.monotonic() + MUTED_REPUSH_INTERVAL
        while True:
            command = self.take_command()
            if command == COMMAND_QUIT:
                return TrayAction.QUIT
            if command == COMMAND_UNMUTE:
                acquire_mic()
                self.set_state(STATE_LISTENING)
                return TrayAction.RESUME
            if time.monotonic() >= next_repush:
                self.set_state(STATE_MUTED)
                next_repush = time.monotonic() + MUTED_REPUSH_INTERVAL
            time.sleep(SLEEP_POLL_INTERVAL)

    def set_state(self, state):
        """Push the current display state to the panel indicator (best-effort)."""
        cmd = [
            "gdbus",
            "call",
            "--session",
            "--dest",
            "org.gnome.Shell",
            "--object-path",
            "/org/easyspeak/Grid",
            "--method",
            "org.easyspeak.Grid.SetState",
            str(state),
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=GDBUS_TIMEOUT
            )
            return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False  # gdbus missing (non-GNOME) or a wedged bus

    def take_command(self):
        """Return and clear the latest menu command, or None if none is pending.

        Reads the one-shot control file the extension writes, then deletes it so
        each menu click fires exactly once. A missing file is the common case
        (every idle iteration), so it's checked cheaply first. The delete is
        best-effort and kept separate from the read: a command that was read
        successfully is returned even if the unlink fails (e.g. the file vanished
        in a race), rather than being silently dropped.
        """
        try:
            if not self._control_file.exists():
                return None
            command = self._control_file.read_text().strip()
        except OSError:
            return None
        # already gone or a transient error; the command still stands
        with contextlib.suppress(OSError):
            self._control_file.unlink()
        return command or None
