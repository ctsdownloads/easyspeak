"""Panel-indicator bridge and asleep-state lifecycle for the daemon.

The daemon is voice-first and otherwise headless; this module gives it a
top-panel microphone icon and owns everything about it so the audio loop in
`core.main` stays about audio. On GNOME the bundled `gnome@easyspeak.dev` Shell
extension serves the icon; on other desktops, such as KDE Plasma, a
StatusNotifierItem helper process ([`core.statusnotifier`][core.statusnotifier])
does. Either way the daemon runs without a D-Bus server of its own, via two
one-directional channels:

* daemon -> icon: state is pushed for display via a one-shot `gdbus call`
  (the same path the mouse-grid plugin uses to drive the extension).
* icon -> daemon: the extension's menu writes a single command to a control
  file; the controller consumes it. The audio loop already wakes every ~80ms on
  a read, so a cheap file probe per iteration is enough, with no GLib loop needed.

The indicator is shown only while the assistant is asleep (deactivated); while
running it stays hidden because GNOME's own microphone privacy icon already
signals the open mic.
"""

import contextlib
import enum
import html
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import log
from .about import (
    APPLICATION_ICON,
    APPLICATION_NAME,
    COMMENTS,
    COPYRIGHT,
    DOCS_URL,
    about_html,
    app_version,
)
from .config import ERROR_SOUND, LANGUAGE
from .control import (
    COMMAND_ABOUT,
    COMMAND_HELP,
    COMMAND_MUTE,
    COMMAND_PRESENT,
    COMMAND_PRESENT_VERBOSE,
    COMMAND_QUIT,
    COMMAND_UNMUTE,
    CONTROL_FILE,
)
from .i18n import _

logger = logging.getLogger(__name__)

# Display states pushed to the indicator. The extension owns the icon/label
# mapping; it shows the indicator only for "muted" and hides it otherwise.
STATE_LISTENING = "listening"
STATE_MUTED = "muted"

ABOUT_HELPER = str(Path(__file__).with_name("about.py"))
TRAY_HELPER = str(Path(__file__).with_name("statusnotifier.py"))

# Who serves the indicator's SetState: the GNOME Shell extension, or the tray helper.
SHELL_SERVICE = "org.gnome.Shell"
TRAY_SERVICE = "org.easyspeak.Tray"

# How long to idle between control-file probes while the assistant is asleep.
SLEEP_POLL_INTERVAL = 0.2

# How often to re-assert the muted state while asleep, so the indicator recovers
# if GNOME Shell or the extension reloads (which leaves it hidden by default).
MUTED_REPUSH_INTERVAL = 5.0

# Cap the gdbus call so a wedged session bus can't hang the audio loop.
GDBUS_TIMEOUT = 5.0

HELPER_STARTUP_GRACE = 1.5


def on_gnome():
    """Return whether the session is GNOME, where the Shell extension is the tray."""
    return "GNOME" in os.environ.get("XDG_CURRENT_DESKTOP", "").split(":")


def notify(summary, body):
    """Show a desktop notification; False if no notification service took it.

    Speaks the freedesktop Notifications protocol over D-Bus, which every desktop's
    notification service implements. jeepney is imported lazily so the dependency
    isn't needed to load this module.

    `body` is markup, so escape its text: `<b>`, `<i>` and `<u>` show where the
    service takes markup, as GNOME's, KDE's and most others do, and are taken out
    where it doesn't. Separate its lines with
    [`LINE_BREAK`][core.tray.LINE_BREAK], not a newline.
    """
    from jeepney import DBusAddress, MessageType, new_method_call
    from jeepney.io.blocking import open_dbus_connection

    service = "org.freedesktop.Notifications"
    address = DBusAddress(
        "/org/freedesktop/Notifications", bus_name=service, interface=service
    )
    try:
        with open_dbus_connection(bus="SESSION") as conn:
            capabilities = conn.send_and_get_reply(
                new_method_call(address, "GetCapabilities"), timeout=GDBUS_TIMEOUT
            ).body
            if not capabilities or "body-markup" not in capabilities[0]:
                body = html.unescape(re.sub(r"</?[biu]>", "", body))
            message = new_method_call(
                address,
                "Notify",
                "susssasa{sv}i",
                (APPLICATION_NAME, 0, APPLICATION_ICON, summary, body, [], {}, -1),
            )
            reply = conn.send_and_get_reply(message, timeout=GDBUS_TIMEOUT)
    except Exception as exc:
        logger.debug("No desktop notification: %s", exc)
        return False
    return reply.header.message_type is MessageType.method_return


LINE_BREAK = "\u2028"
"""Unicode's line separator, for line breaks in a notification body.

GNOME Shell turns each newline in a body into a space, but this character passes
and its text layout breaks the line there, as other desktops' do.
"""


def escape(text):
    """Escape `text` for a notification's markup body."""
    return html.escape(text, quote=False)


class TrayAction(enum.Enum):
    """What `Tray.poll` is telling the audio loop to do next."""

    CONTINUE = "continue"  # nothing happened; read audio as usual
    SPOKE = "spoke"  # said something; let it finish before recording again
    RESUME = "resume"  # woke from sleep; restart the listen iteration
    QUIT = "quit"  # exit the daemon


class Tray:
    """Owns the EasySpeak panel indicator and the asleep (deactivated) lifecycle.

    The audio loop calls [`poll`][core.tray.Tray.poll] once per iteration; the
    controller pushes display state, consumes menu commands, and, when deactivated,
    runs the idle loop itself, using caller-supplied callbacks to release and reacquire
    the microphone. It never touches audio directly.

    Best-effort throughout: without a tray (no `gdbus`, extension or panel to show
    the icon) the state pushes simply fail and the daemon carries on, mirroring how
    the mouse-grid plugin tolerates a missing extension.
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
        self._service = SHELL_SERVICE if on_gnome() else TRAY_SERVICE
        self._helper = None
        self._about = None
        self._sleep_requested = False
        self._speak = speak or (lambda _text: None)

    # --- lifecycle hooks called by the daemon ---

    def started(self):
        """Daemon is up and listening; ensure the indicator is hidden.

        Also drop any command left in the control file from before startup. It's a
        one-shot channel for *live* menu clicks, so a stale 'about'/'help'/ 'quit'
        written during a previous session (or before the daemon was running to consume
        it) must not fire the moment polling begins, which otherwise pops the About
        window open on launch. Only a second launch's request for details is kept, as
        the startup greeting fulfils it.

        Greets the user once startup reaches a listening state, the spoken
        counterpart of the wake chime, and the same greeting reactivation gives,
        also in a notification (see [`greet`][core.tray.Tray.greet]).

        Outside GNOME it starts the tray helper first.
        """
        details = self.take_command() == COMMAND_PRESENT_VERBOSE
        if self._service == TRAY_SERVICE:
            self._start_helper()
        self.set_state(STATE_LISTENING)
        self.greet(details=details)

    def greet(self, details=False):
        """Say that EasySpeak is ready, aloud and in a desktop notification.

        Verbose, or with `details` (a second launch with `-v` asks for them), the
        notification also tells the version, desktop and language, then the latest
        warnings and errors, one per line with a bold label. The greeting stays its
        first line, as the desktop's pop-up shows little more. If there are any,
        the greeting says so, too, so they're noticed without looking at a terminal;
        it speaks of problems only for errors.
        """
        greeting = _("Welcome! I'm ready.")
        self._speak(greeting)
        details = details or log.verbose()
        lines = [escape(greeting)]
        if details:
            desktop = os.environ.get("XDG_CURRENT_DESKTOP") or "unknown"
            if session := os.environ.get("XDG_SESSION_TYPE"):
                desktop = f"{desktop} ({session})"
            lines.append(
                f"<b>Version</b> {escape(app_version())}, "
                f"<b>desktop</b> {escape(desktop)}, <b>language</b> {LANGUAGE}."
            )
            lines += [
                f"<b>{logging.getLevelName(level).capitalize()}:</b> {escape(message)}"
                for level, message in log.problems
            ]
        shown = notify(APPLICATION_NAME, LINE_BREAK.join(lines))
        if details and log.problems and shown:
            if any(level >= logging.ERROR for level, _message in log.problems):
                summary = _(
                    "I ran into problems. The details are in the desktop notification."
                )
            else:
                summary = _(
                    "There were warnings. The details are in the desktop notification."
                )
            self._speak(summary)

    def present(self, details=False):
        """Come forward for a second launch: raise the About dialog, then greet."""
        if self.about_open():
            self.open_about()
        self.greet(details=details)

    def stopped(self):
        """Daemon is exiting; hide the indicator so no stale icon is left."""
        self.set_state(STATE_LISTENING)
        if self._helper:
            self._helper.terminate()
            self._helper = None

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
        if command in (COMMAND_PRESENT, COMMAND_PRESENT_VERBOSE):
            self._sleep_requested = False  # the later launch wants it listening
            self.present(details=command == COMMAND_PRESENT_VERBOSE)
            return TrayAction.SPOKE
        if self._run_menu_action(command):
            return TrayAction.CONTINUE
        if command == COMMAND_MUTE or self._sleep_requested:
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
        handles them too so the path isn't lifecycle-dependent.
        """
        if command == COMMAND_HELP:
            if not self._spawn(["xdg-open", DOCS_URL], "documentation page"):
                self._report_failure(
                    _("Sorry, I couldn't open the documentation page.")
                )
            return True
        if command == COMMAND_ABOUT:
            self.open_about()
            return True
        return False

    def open_about(self):
        """Open the About dialog, from the menu or by voice.

        The dialog needs PyGObject + GTK4/libadwaita, which aren't in the daemon's
        own (uv) venv. Reuse the PyGObject-equipped interpreter the dictation AT-SPI
        helper already runs in, falling back to our own interpreter when it isn't set
        (e.g. a plain pip install). GTK 4 and libadwaita are optional, so without them
        the user still hears who they're talking to, with the details in a notification.

        Outside GNOME, KDE's `kdialog` shows the information first where it's
        installed, in the desktop's own look. An About dialog that is already
        showing is closed and opened again, which brings it to the front: Wayland
        desktops don't let one program raise another one's window.
        """
        self.close_about()
        if not on_gnome() and shutil.which("kdialog"):
            kdialog = ["kdialog", "--title", "About EasySpeak"]
            kdialog += ["--icon", APPLICATION_ICON, "--msgbox", about_html()]
            self._about = self._spawn(kdialog, "About dialog (kdialog)")
            if self._about:
                return
        python = os.environ.get("EASYSPEAK_ATSPI_PYTHON", sys.executable)
        self._about = self._spawn([python, ABOUT_HELPER], "About dialog")
        if not self._about:
            self._tell_about()

    def about_open(self):
        """Whether an About dialog EasySpeak opened is still showing."""
        return self._about is not None and self._about.poll() is None

    def close_about(self):
        """Close the About dialog EasySpeak opened; False if none is showing."""
        if not self.about_open():
            return False
        self._about.terminate()
        self._about = None
        return True

    def _tell_about(self):
        """Present EasySpeak without the About dialog: spoken, plus a notification."""
        name = f"{APPLICATION_NAME} {app_version()}".strip()
        about = (COMMENTS, COPYRIGHT, f"GPL-3.0 · {DOCS_URL}")
        if notify(name, LINE_BREAK.join(map(escape, about))):
            self._speak(
                _(
                    "This is {name}. The details are in the desktop notification."
                ).format(name=name)
            )
        else:
            self._speak(_("This is {name}.").format(name=name))

    def _start_helper(self):
        """Start the StatusNotifierItem tray helper for desktops other than GNOME.

        It runs in its own session, so Ctrl+C in the terminal doesn't reach it: it
        leaves on its own once the daemon is gone, without a stack trace.
        """
        try:
            self._helper = subprocess.Popen(
                [sys.executable, TRAY_HELPER, str(self._control_file)],
                stdout=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            logger.warning("Couldn't start the tray icon.", exc_info=True)

    def _spawn(self, cmd, what):
        """Launch a helper process and return it; None if it fails to start.

        Fire-and-forget for the success case: a helper whose window opens keeps running
        and is left detached (never waited on or reaped). But a helper that *can't*
        start (a bad interpreter, missing GTK/libadwaita, no display, no `xdg-open`
        handler) exits within [`HELPER_STARTUP_GRACE`][core.tray.HELPER_STARTUP_GRACE];
        that's caught here so the caller can tell the user, and the menu click isn't
        silently lost.

        The helper runs in its own session, so Ctrl+C in the terminal quits EasySpeak
        without killing an open About dialog or browser. stderr is captured to an
        anonymous temp file rather than a pipe: a long-lived
        helper keeps writing to it (GTK logs to stderr) without ever blocking on a full
        pipe buffer we've stopped draining, and the file is reclaimed by the OS once the
        helper exits.
        """
        with tempfile.TemporaryFile() as errlog:
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=errlog,
                    start_new_session=True,
                )
            except OSError:
                logger.warning("Couldn't open the %s.", what, exc_info=True)
                return None
            returncode = self._await_startup(proc)
            if returncode not in (None, 0):
                errlog.seek(0)
                detail = errlog.read().decode(errors="replace").strip()
                reason = (
                    detail.splitlines()[-1] if detail else f"exit code {returncode}"
                )
                logger.warning("The %s couldn't open: %s", what, reason)
                if detail:
                    logger.debug(
                        "The %s exited with code %s:\n%s", what, returncode, detail
                    )
                return None
        return proc

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

    def _report_failure(self, apology):
        """Tell the user a helper couldn't open.

        Error chime and a spoken apology (voice-first equivalent of GTK's error bell).
        """
        with contextlib.suppress(OSError):
            subprocess.run(["paplay", ERROR_SOUND], capture_output=True)
        self._speak(apology)

    def sleep(self, release_mic, acquire_mic, announce=True):
        """Release the mic and idle until reactivated, then greet and resume.

        Pushes the muted state first and refuses to sleep unless it lands:
        reactivation arrives via the tray (its menu or the Quick Settings
        toggle), so releasing the mic while the indicator is missing (no
        extension, or no panel to show the icon) would strand the daemon with no
        way back. While asleep the muted state is re-asserted every
        `MUTED_REPUSH_INTERVAL` seconds so the icon recovers if the panel or the
        extension reloads (it would otherwise come back hidden).

        `announce` says whether to speak the deactivation confirmation: True for
        a button mute, False for a voice "go to sleep" (the sleep plugin already
        spoke, so speaking again would just repeat it). Reactivation always
        greets, matching the startup greeting. A second launch of EasySpeak
        reactivates it, too, as starting it means wanting it to listen.

        Freeing the stream also clears GNOME's privacy microphone indicator, an
        OS-level 'not listening' cue alongside our own muted glyph.
        """
        if not self.set_state(STATE_MUTED):
            logger.warning(
                "Tray indicator unavailable; staying awake so you keep a way to "
                "reactivate."
            )
            self._speak(_("I couldn't turn voice control off, so I'll keep listening."))
            return TrayAction.CONTINUE
        release_mic()
        logger.info("Muted; microphone released. Waiting for reactivation...")
        if announce:
            self._speak(_("Voice control turned off."))
        next_repush = time.monotonic() + MUTED_REPUSH_INTERVAL
        while True:
            command = self.take_command()
            if command == COMMAND_QUIT:
                return TrayAction.QUIT
            if command == COMMAND_UNMUTE:
                acquire_mic()
                self.set_state(STATE_LISTENING)
                self._speak(_("Welcome! I'm ready."))
                return TrayAction.RESUME
            if command in (COMMAND_PRESENT, COMMAND_PRESENT_VERBOSE):
                acquire_mic()
                self.set_state(STATE_LISTENING)
                self.present(details=command == COMMAND_PRESENT_VERBOSE)
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
            self._service,
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
            return False  # gdbus missing or a wedged bus

    def take_command(self):
        """Return and clear the latest menu command, or None if none is pending.

        Claims the one-shot control file the extension writes by renaming it, then
        reads and deletes the claimed copy, so each menu click fires exactly once.
        A command written meanwhile lands in a new control file, for the next poll,
        instead of being deleted unread. A missing file is the common case (every
        idle iteration), so it's checked cheaply first. The delete is best-effort
        and kept separate from the read: a command that was read successfully is
        returned even if the unlink fails, rather than being silently dropped.
        """
        claimed = self._control_file.with_name(f".{self._control_file.name}.taken")
        try:
            if not self._control_file.exists():
                return None
            self._control_file.rename(claimed)
            command = claimed.read_text().strip()
        except OSError:
            return None
        # already gone or a transient error; the command still stands
        with contextlib.suppress(OSError):
            claimed.unlink()
        return command or None
