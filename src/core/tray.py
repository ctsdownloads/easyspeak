"""GNOME panel-indicator bridge and asleep-state lifecycle for the daemon.

The daemon is voice-first and otherwise headless; this module gives it a
top-panel microphone icon (served by the bundled `easyspeak@local` GNOME
Shell extension) and owns everything about it so the audio loop in `core.main`
stays about audio. It runs without a D-Bus server of its own via two
one-directional channels:

* daemon -> icon: state is pushed for display via a one-shot `gdbus call`
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
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .about import DOCS_URL

logger = logging.getLogger(__name__)

# Display states pushed to the indicator. The extension owns the icon/label
# mapping; it shows the indicator only for "muted" and hides it otherwise.
STATE_LISTENING = "listening"
STATE_MUTED = "muted"

# Menu commands the extension writes into the control file for the daemon.
COMMAND_QUIT = "quit"
COMMAND_MUTE = "mute"
COMMAND_UNMUTE = "unmute"
COMMAND_HELP = "help"  # open the documentation page in the default browser
COMMAND_ABOUT = "about"  # open the libadwaita About window

# The About window is its own process: the indicator lives in a GNOME Shell
# extension that can't host GTK, so the daemon spawns this script instead. It's
# run by file path (not `-m`) because the PyGObject interpreter it runs in (see
# _run_menu_action) doesn't have the `easyspeak` package installed; about.py is
# self-contained, so a plain path works there and in our own interpreter alike.
ABOUT_HELPER = str(Path(__file__).with_name("about.py"))

# Shared with the extension's ScreenshotManager, which creates ~/.cache/easyspeak.
CONTROL_FILE = Path.home() / ".cache" / "easyspeak" / "control"

# Desktop "something failed" sound, played alongside the spoken apology when a
# menu helper can't open. FHS path (from sound-theme-freedesktop); the flake
# sed-replaces this directory with the Nix store one at sync time, mirroring the
# wake chime in core.main.
ERROR_SOUND = "/usr/share/sounds/freedesktop/stereo/dialog-error.oga"

# How long to idle between control-file probes while the assistant is asleep.
SLEEP_POLL_INTERVAL = 0.2

# How often to re-assert the muted state while asleep, so the indicator recovers
# if GNOME Shell or the extension reloads (which leaves it hidden by default).
MUTED_REPUSH_INTERVAL = 5.0

# Cap the gdbus call so a wedged session bus can't hang the audio loop.
GDBUS_TIMEOUT = 5.0

# How long to watch a launched helper before assuming its window opened. A
# helper that can't start (bad interpreter, missing GTK/libadwaita, no display)
# exits within this window; a working GUI keeps running, so we stop watching and
# leave it detached. Only paid when a helper is actually launched, and only in
# full while one succeeds — a failure returns as soon as the process dies.
HELPER_STARTUP_GRACE = 1.5


class TrayAction(enum.Enum):
    """What `Tray.poll` is telling the audio loop to do next."""

    CONTINUE = "continue"  # nothing happened; read audio as usual
    RESUME = "resume"  # woke from sleep; restart the listen iteration
    QUIT = "quit"  # exit the daemon


class Tray:
    """Owns the EasySpeak panel indicator and the asleep (deactivated) lifecycle.

    The audio loop calls [`poll`][core.tray.Tray.poll] once per iteration; the
    controller pushes display state, consumes menu commands, and — when deactivated —
    runs the idle loop itself, using caller-supplied callbacks to release and reacquire
    the microphone. It never touches audio directly.

    Best-effort throughout: on a non-GNOME desktop (no `gdbus`/extension) the state
    pushes simply fail and the daemon carries on, mirroring how the mouse-grid plugin
    tolerates a missing extension.
    """

    def __init__(self, control_file=CONTROL_FILE, speak=None):
        """Set up the controller, optionally with a spoken-feedback callback.

        `speak` (core.speak) voices the asleep/awake lifecycle: the deactivation
        confirmation for a button mute, the reactivation and startup greetings,
        and the explanation when sleep can't engage. A voice "go to sleep" is
        already spoken by the sleep plugin, hence the `announce` flag on
        [`sleep`][core.tray.Tray.sleep]. Defaults to a no-op so the tray works
        headless and in tests.
        """
        self._control_file = Path(control_file)
        self._sleep_requested = False
        self._speak = speak or (lambda _text: None)

    # --- lifecycle hooks called by the daemon ---

    def started(self):
        """Daemon is up and listening; ensure the indicator is hidden.

        Also drop any command left in the control file from before startup. It's a
        one-shot channel for *live* menu clicks, so a stale 'about'/'help'/ 'quit'
        written during a previous session (or before the daemon was running to consume
        it) must not fire the moment we begin polling — which otherwise pops the About
        window open on launch.

        Greets the user once startup reaches a listening state, the spoken
        counterpart of the wake chime — and the same greeting reactivation gives.
        """
        self.take_command()
        self.set_state(STATE_LISTENING)
        self._speak("Welcome! I'm ready.")

    def stopped(self):
        """Daemon is exiting; hide the indicator so no stale icon is left."""
        self.set_state(STATE_LISTENING)

    def request_sleep(self):
        """Queue a deactivate (e.g. the "go to sleep" voice command).

        The mic is released at the audio loop's next [`poll`][core.tray.Tray.poll],
        after the current command finishes.
        """
        self._sleep_requested = True

    def poll(self, release_mic, acquire_mic):
        """Act on any pending menu command or queued sleep request.

        `release_mic` / `acquire_mic` are zero-arg callbacks that close and reopen the
        input stream; the controller calls them around the asleep idle loop so this
        module stays out of the audio internals. Returns a
        [`TrayAction`][core.tray.TrayAction] for the audio loop to dispatch on.
        """
        command = self.take_command()
        if command == COMMAND_QUIT:
            return TrayAction.QUIT
        if self._run_menu_action(command):
            return TrayAction.CONTINUE
        if command == COMMAND_MUTE or self._sleep_requested:
            # A voice "go to sleep" reaches here via _sleep_requested, and the
            # sleep plugin has already spoken; a button mute (COMMAND_MUTE) has
            # not, so only then does the tray announce the deactivation itself.
            announce = command == COMMAND_MUTE
            self._sleep_requested = False
            return self.sleep(release_mic, acquire_mic, announce=announce)
        return TrayAction.CONTINUE

    # --- internals ---

    def _run_menu_action(self, command):
        """Handle a fire-and-forget menu command (Help/About).

        Returns True if it was one of those side-effect actions so callers can carry on
        without touching the sleep/quit lifecycle. The indicator menu is only shown
        while asleep, so in practice these fire from the idle loop in `sleep`; `poll`
        handles them too so the path isn't lifecycle- dependent.

        The About dialog needs PyGObject + GTK4/libadwaita, which aren't in the daemon's
        own (uv) venv. Reuse the PyGObject-equipped interpreter the dictation AT-SPI
        helper already runs in, falling back to our own interpreter when it isn't set
        (e.g. a plain pip install).
        """
        if command == COMMAND_HELP:
            self._spawn(["xdg-open", DOCS_URL], "documentation page")
            return True
        if command == COMMAND_ABOUT:
            python = os.environ.get("EASYSPEAK_ATSPI_PYTHON", sys.executable)
            self._spawn([python, ABOUT_HELPER], "About window")
            return True
        return False

    def _spawn(self, cmd, what):
        """Launch a helper process, reporting it if it fails to start.

        Fire-and-forget for the success case: a helper whose window opens keeps running
        and is left detached (never waited on or reaped). But a helper that *can't*
        start — a bad interpreter, missing GTK/libadwaita, no display, no `xdg-open`
        handler — exits within [`HELPER_STARTUP_GRACE`][core.tray.HELPER_STARTUP_GRACE];
        that's caught here so the menu click isn't silently lost, with the cause logged
        and an audible apology spoken.

        stderr is captured to an anonymous temp file rather than a pipe: a long-lived
        helper keeps writing to it (GTK logs to stderr) without ever blocking on a full
        pipe buffer we've stopped draining, and the file is reclaimed by the OS once the
        helper exits.
        """
        with tempfile.TemporaryFile() as errlog:
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=errlog)
            except OSError:
                logger.warning("Couldn't open the %s.", what, exc_info=True)
                self._report_failure(what)
                return
            returncode = self._await_startup(proc)
            if returncode not in (None, 0):
                errlog.seek(0)
                detail = errlog.read().decode(errors="replace").strip()
                logger.error(
                    "The %s exited with code %s.%s",
                    what,
                    returncode,
                    f"\n{detail}" if detail else "",
                )
                self._report_failure(what)

    def _await_startup(self, proc):
        """Return the helper's exit code if it dies during startup, else None.

        Waits up to [`HELPER_STARTUP_GRACE`][core.tray.HELPER_STARTUP_GRACE]; a helper
        still running past that is taken to have opened its window, so this returns None
        ("started, leave it") rather than reaping a GUI that may stay up for minutes.
        """
        try:
            return proc.wait(timeout=HELPER_STARTUP_GRACE)
        except subprocess.TimeoutExpired:
            return None

    def _report_failure(self, what):
        """Tell the user a helper couldn't open.

        Error chime and a spoken apology (voice-first equivalent of GTK's error bell).
        """
        with contextlib.suppress(OSError):
            subprocess.run(["paplay", ERROR_SOUND], capture_output=True)
        self._speak(f"Sorry, I couldn't open the {what}.")

    def sleep(self, release_mic, acquire_mic, announce=True):
        """Release the mic and idle until reactivated, then greet and resume.

        Pushes the muted state first and refuses to sleep unless it lands:
        reactivation arrives via the extension (tray menu or Quick Settings
        toggle), so releasing the mic while the indicator is missing (no
        GNOME/extension) would strand the daemon with no way back. While asleep
        the muted state is re-asserted every `MUTED_REPUSH_INTERVAL` seconds so
        the icon recovers if GNOME Shell or the extension reloads (it would
        otherwise come back hidden).

        `announce` says whether to speak the deactivation confirmation: True for
        a button mute, False for a voice "go to sleep" (the sleep plugin already
        spoke, so speaking again would just repeat it). Reactivation always
        greets, matching the startup greeting.

        Freeing the stream also clears GNOME's privacy microphone indicator, an
        OS-level 'not listening' cue alongside our own muted glyph.
        """
        if not self.set_state(STATE_MUTED):
            logger.warning(
                "Tray indicator unavailable; staying awake so you keep a way to "
                "reactivate."
            )
            self._speak("I couldn't turn voice control off, so I'll keep listening.")
            return TrayAction.CONTINUE
        release_mic()
        logger.info("Muted; microphone released. Waiting for reactivation...")
        if announce:
            self._speak("Voice control turned off.")
        next_repush = time.monotonic() + MUTED_REPUSH_INTERVAL
        while True:
            command = self.take_command()
            if command == COMMAND_QUIT:
                return TrayAction.QUIT
            if command == COMMAND_UNMUTE:
                acquire_mic()
                self.set_state(STATE_LISTENING)
                self._speak("Welcome! I'm ready.")
                return TrayAction.RESUME
            self._run_menu_action(command)
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
            "/org/easyspeak/Desktop",
            "--method",
            "org.easyspeak.Desktop.SetState",
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
