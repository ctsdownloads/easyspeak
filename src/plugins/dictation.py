"""Dictation Plugin - Voice to text via AT-SPI."""

import ast
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from easyspeak.core import mediakeys
from easyspeak.core.config import LANGUAGE

logger = logging.getLogger(__name__)

NAME = "dictation"
DESCRIPTION = "Voice dictation into any text field"

MAX_RECORD_SECONDS = 20.0
SILENCE_DURATION = 0.7

COMMANDS = [
    "notes - start dictation mode (say 'stop notes' to end)",
    "Punctuation: comma, period, question mark, exclamation mark, colon, semicolon",
    "Editing: backspace, backspace five, scratch that",
    "Keys: enter, tab, escape, page up, page down, press down five",
    "Structure: new sentence, new line, new paragraph",
    "Symbols: apostrophe, quote, dash, hyphen, at sign, hashtag, percent, asterisk",
]

core = None

# Prompt to bias Whisper toward recognizing punctuation commands
DICTATION_PROMPT = (
    "comma, period, new sentence, new paragraph, new line, question mark, "
    "exclamation mark, colon, semicolon, stop notes, backspace, scratch that, "
    "enter, tab, escape, space, apostrophe, quote, dash, hyphen, at sign, "
    "hashtag, percent"
)


def ensure_gnome_accessibility():
    """Enable GNOME's toolkit-accessibility for the AT-SPI bridge.

    Silently skipped if gsettings isn't on PATH or the schema isn't installed (i.e. user
    isn't on GNOME). Warns if it's present but the flip fails. Tells the user to
    re-login when newly enabled.
    """
    if shutil.which("gsettings") is None:
        return
    schema, key = "org.gnome.desktop.interface", "toolkit-accessibility"
    try:
        current = subprocess.run(
            ["gsettings", "get", schema, key],
            capture_output=True,
            text=True,
            check=False,
        )
        if current.returncode != 0:
            return  # schema missing — not really on GNOME
        if current.stdout.strip() == "true":
            return
        result = subprocess.run(
            ["gsettings", "set", schema, key, "true"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            logger.info(
                "enabled GNOME toolkit-accessibility — "
                "log out and back in for dictation to work"
            )
        else:
            logger.warning(
                "could not enable GNOME toolkit-accessibility; dictation will not work"
            )
    except OSError:
        pass


def setup(c):
    """Store the core reference and enable the GNOME accessibility bridge."""
    global core
    core = c
    c.dictation_last_length = 0
    ensure_gnome_accessibility()
    # Offer dictation to the keyboard (silent) activation path too: core runs
    # this while the hotkey combo is held, with no wake word spoken.
    if hasattr(c, "register_push_to_talk"):
        c.register_push_to_talk(
            lambda should_continue: run_push_to_talk(c, should_continue)
        )


INSERTED = "inserted"
NO_FOCUS = "no_focus"
BACKEND_ERROR = "backend_error"

ATSPI_HELPER = str(Path(__file__).with_name("_atspi_insert.py"))


EXIT_VERBS = ("stop", "close", "closed", "end", "exit", "done", "finish", "quit")
EXIT_NOUNS = (
    "notes",
    "note",
    "nots",
    "nurts",
    "nuts",
    "knots",
    "notice",
)
EXIT_PHRASES = frozenset(
    f"{verb} {noun}" for verb in EXIT_VERBS for noun in EXIT_NOUNS
) | frozenset(f"{verb}{noun}" for verb in EXIT_VERBS for noun in EXIT_NOUNS)


def is_exit_phrase(text):
    """Whether a dictated utterance asks to leave dictation mode."""
    return any(phrase in text for phrase in EXIT_PHRASES)


# --- Insertion ---------------------------------------------------------------
#

# evdev keycodes for the paste chord (stable Linux input ABI).
KEYCODES = {
    "ctrl": 29,
    "shift": 42,
    "alt": 56,
    "super": 125,
    "insert": 110,
    "v": 47,
}

DEFAULT_PASTE_CHORD = "ctrl+v"

# Terminals paste with Ctrl+Shift+V, since Ctrl+V is a control character there.
# A short, stable list -- unlike the toolkit table this design replaced.
TERMINAL_PASTE_CHORD = "ctrl+shift+v"
TERMINAL_WM_CLASSES = frozenset(
    {
        "alacritty",
        "com.raggesilver.blackbox",
        "contour",
        "foot",
        "ghostty",
        "gnome-terminal-server",
        "guake",
        "kitty",
        "konsole",
        "org.gnome.console",
        "org.gnome.terminal",
        "org.wezfurlong.wezterm",
        "terminator",
        "tilix",
        "xterm",
    }
)

# How long a clipboard tool gets before it is treated as broken.
CLIPBOARD_TIMEOUT = 2.0

# How long to let the paste land before the previous clipboard is put back. Long
# enough for a local paste, short enough not to be felt between utterances.
CLIPBOARD_SETTLE = 0.15

# Sentinel for "the caller didn't look up the focused window", so None can still
# mean "looked, and there wasn't one".
UNKNOWN = object()

# Bumped on every insertion. The background restore checks it so a slow restore
# can't overwrite text a later utterance has since put on the clipboard.
_clipboard_generation = 0

# Reading the focused window costs a gdbus round trip, so cap it rather than let
# a wedged session bus stall every utterance.
WINDOW_QUERY_TIMEOUT = 2.0


def focused_wm_class():
    """Return the focused window's WM class, or None if it can't be read.

    Asks the bundled GNOME extension, the same way the mouse grid asks it for the
    screen size. Only used to pick the paste chord, so any failure simply means
    the default one.
    """
    try:
        result = subprocess.run(
            [
                "gdbus",
                "call",
                "--session",
                "--dest",
                "org.gnome.Shell",
                "--object-path",
                "/org/easyspeak/Desktop",
                "--method",
                "org.easyspeak.Desktop.GetWindows",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=WINDOW_QUERY_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        # gdbus wraps the reply in GVariant tuple syntax: ('<json>',)
        payload = ast.literal_eval(result.stdout.strip())[0]
        windows = json.loads(payload)
    except (SyntaxError, ValueError, IndexError, TypeError):
        return None
    focused = next((w for w in windows if w.get("focused")), None)
    return focused.get("wm_class") if focused else None


def paste_chord(wm_class=UNKNOWN):
    """Return the evdev keycodes for the paste chord to send.

    `wm_class` is the focused window if the caller already looked it up; reading it
    again costs a gdbus round trip on the path between speaking and seeing text.

    `EASYSPEAK_PASTE_KEYS` overrides it outright (e.g. `shift+insert`); otherwise
    terminals get Ctrl+Shift+V and everything else Ctrl+V. An unknown key name in
    the override is reported and the default used, rather than silently sending a
    chord that does nothing.
    """
    override = os.environ.get("EASYSPEAK_PASTE_KEYS", "").strip().lower()
    if override:
        codes = [KEYCODES.get(part.strip()) for part in override.split("+")]
        if all(codes):
            return codes
        logger.warning(
            "Ignoring EASYSPEAK_PASTE_KEYS=%r: unknown key. Known keys: %s.",
            override,
            ", ".join(sorted(KEYCODES)),
        )
    if wm_class is UNKNOWN:
        wm_class = focused_wm_class()
    chord = (
        TERMINAL_PASTE_CHORD if wm_class in TERMINAL_WM_CLASSES else DEFAULT_PASTE_CHORD
    )
    return [KEYCODES[part] for part in chord.split("+")]


def clipboard_tools():
    """Return the (copy, paste) commands, or (None, None) if wl-clipboard is absent.

    EasySpeak targets Wayland, so wl-clipboard is the only supported tool. Without
    it there is no way to put text on the clipboard.
    """
    if shutil.which("wl-copy") and shutil.which("wl-paste"):
        return ["wl-copy"], ["wl-paste", "--no-newline"]
    return None, None


def read_clipboard(paste_cmd):
    """Return the current clipboard text, or None if there isn't any.

    Read as bytes and decoded here rather than by `subprocess`, because the
    clipboard often isn't text at all -- a copied image arrives as PNG bytes, and
    decoding those as UTF-8 raised straight out of the middle of an insertion and
    killed dictation mid-sentence.

    Non-text content simply isn't preserved: the dictated text still gets pasted,
    but whatever was on the clipboard is gone afterwards. Restoring arbitrary
    binary would mean tracking MIME types through both tools, which is a lot of
    machinery for something a user rarely notices.
    """
    try:
        result = subprocess.run(
            paste_cmd, capture_output=True, check=False, timeout=CLIPBOARD_TIMEOUT
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        return result.stdout.decode("utf-8")
    except UnicodeDecodeError:
        logger.debug("clipboard holds non-text data; it won't be restored")
        return None


def write_clipboard(copy_cmd, text):
    """Put text on the clipboard; False if that failed.

    Output goes to /dev/null rather than a pipe. `wl-copy` forks a daemon to hold
    the selection for as long as it owns it, and that daemon inherits whatever
    pipes we hand the parent -- so capturing output makes `subprocess.run` wait on
    a process that never exits (CPython bpo-37424). Every copy timed out, and
    dictation reported that it couldn't reach the clipboard.
    """
    try:
        result = subprocess.run(
            copy_cmd,
            input=text,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=CLIPBOARD_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        logger.warning("%s did not finish within %ss", copy_cmd[0], CLIPBOARD_TIMEOUT)
        return False
    except OSError as exc:
        logger.warning("could not run %s: %s", copy_cmd[0], exc)
        return False
    if result.returncode != 0:
        logger.warning("%s exited with code %s", copy_cmd[0], result.returncode)
        return False
    return True


# Browsers that need to be told to accept keystrokes as text. qutebrowser is
# modal; most applications are not.
BROWSER_WM_CLASSES = ("org.qutebrowser.qutebrowser", "qutebrowser")


# Set once a paste has put qutebrowser into insert mode, so the mode can be handed
# back when dictation ends.
_left_browser_in_insert_mode = False


def _qb_command(command):
    """Send one command to qutebrowser, best-effort."""
    try:
        subprocess.run(
            ["qutebrowser", f":{command}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=CLIPBOARD_TIMEOUT,
        )
        return True
    except (OSError, subprocess.TimeoutExpired):
        logger.debug("could not reach qutebrowser for :%s", command)
        return False


def _enter_browser_insert_mode():
    """Put qutebrowser where a keystroke reaches the page rather than the browser."""
    global _left_browser_in_insert_mode
    if _qb_command("mode-enter insert"):
        _left_browser_in_insert_mode = True


def leave_browser_insert_mode():
    """Hand qutebrowser back in normal mode once dictation is over.

    Insert mode is entered so a paste reaches the page, but leaving the browser in
    it means every later keystroke is treated as text: hinting and scrolling both
    misbehave, which looked like dictation breaking the browser on its way out.
    """
    global _left_browser_in_insert_mode
    if not _left_browser_in_insert_mode:
        return
    _left_browser_in_insert_mode = False
    _qb_command("mode-leave")


def has_focused_text_field():
    """Whether anything is focused that could receive text.

    Chromium-based apps accept an AT-SPI insertion and quietly discard it, which
    is why text goes in by clipboard and paste instead. They do still report which
    element holds focus, though, so the helper is run with an empty string purely
    as a question: it finds the insertion point, writes nothing, and says whether
    there was one.

    Any failure answers yes. A probe that can't run is no reason to refuse to
    paste -- the old behaviour, blind but willing, is the better fallback.
    """
    return insert_via_atspi("") != NO_FOCUS


def insert_text(text):
    """Insert text into the focused application by pasting it.

    The clipboard is put back afterwards, so dictating doesn't quietly cost the
    user whatever they had copied. Falls back to AT-SPI when no clipboard tool is
    installed, which is the only case where the old path was ever the better one.
    """
    if not has_focused_text_field():
        return NO_FOCUS

    copy_cmd, paste_cmd = clipboard_tools()
    if copy_cmd is None:
        logger.warning(
            "wl-clipboard is not installed, so dictation is falling back to "
            "AT-SPI, which Chromium-based apps accept and ignore. Install "
            "wl-clipboard for text to reach the browser."
        )
        return insert_via_atspi(text)

    global _clipboard_generation

    target = focused_wm_class()

    saved = read_clipboard(paste_cmd)
    if not write_clipboard(copy_cmd, text):
        logger.warning("Could not put the dictated text on the clipboard.")
        return BACKEND_ERROR

    _clipboard_generation += 1
    chord = paste_chord(target)

    if target in BROWSER_WM_CLASSES:
        _enter_browser_insert_mode()
    logger.info(
        "⌨️  pasting %d chars into %s with %s",
        len(text),
        target or "an unknown window",
        "+".join(
            next(key for key, code in KEYCODES.items() if code == part)
            for part in chord
        ),
    )

    try:
        mediakeys.tap_chord(chord)
    except Exception:
        logger.warning(
            "Could not send the paste keystroke. Dictation needs GNOME's "
            "RemoteDesktop interface, which this session doesn't provide.",
            exc_info=True,
        )
        return BACKEND_ERROR

    logger.debug("pasted into %s", target or "an unknown window")

    _restore_clipboard_later(copy_cmd, saved, _clipboard_generation)
    return INSERTED


def _restore_clipboard_later(copy_cmd, saved, generation):
    """Put the previous clipboard back once the paste has had time to land."""
    if saved is None:
        return  # nothing was there to preserve

    def _restore():
        time.sleep(CLIPBOARD_SETTLE)
        if generation == _clipboard_generation:
            write_clipboard(copy_cmd, saved)

    threading.Thread(target=_restore, daemon=True).start()


ATSPI_CANDIDATES = ("python3", "/usr/bin/python3", "/usr/bin/python")

# Exactly what the helper does on startup, so a candidate is only accepted if the
# real import chain works -- PyGObject alone isn't enough without the typelib.
ATSPI_PROBE = (
    "import gi; gi.require_version('Atspi', '2.0'); from gi.repository import Atspi"
)

# Resolved once and remembered; False means "looked and found nothing".
_atspi_python = None


def atspi_python():
    """Path to an interpreter that can actually run the AT-SPI helper, or None.

    The helper needs PyGObject and the AT-SPI typelib, which the app's own venv
    usually lacks. `EASYSPEAK_ATSPI_PYTHON` lets the packaging point straight at an
    interpreter that has them (the Nix flake sets it). Otherwise each candidate is
    probed with the helper's own import chain and the first that works is kept.

    Falling back to a bare `python3` used to be enough, but only until the daemon
    was run from an activated virtualenv: `python3` then resolves to the venv's
    interpreter, which has no PyGObject, and dictation transcribed perfectly and
    inserted nothing.
    """
    global _atspi_python
    if _atspi_python is None:
        _atspi_python = _find_atspi_python() or False
    return _atspi_python or None


def _find_atspi_python():
    """Return the first interpreter that can import AT-SPI, or None."""
    override = os.environ.get("EASYSPEAK_ATSPI_PYTHON")
    if override:
        return override
    for candidate in ATSPI_CANDIDATES:
        try:
            probe = subprocess.run(
                [candidate, "-c", ATSPI_PROBE], capture_output=True, check=False
            )
        except OSError:
            continue  # no such interpreter; try the next
        if probe.returncode == 0:
            logger.debug("dictation will use %s for AT-SPI", candidate)
            return candidate
    return None


def insert_via_atspi(text):
    """Insert text via AT-SPI.

    Returns one of INSERTED, NO_FOCUS or BACKEND_ERROR so the caller can give feedback
    that matches the real cause instead of always blaming focus.
    """
    python = atspi_python()
    logger.info("⌨️  inserting %d chars via AT-SPI (%s)", len(text), python)
    if python is None:
        logger.warning(
            "Dictation needs PyGObject and the AT-SPI typelib, and no interpreter "
            "on this system has both. Install them (Fedora: sudo dnf install "
            "python3-gobject at-spi2-core; Debian/Ubuntu: sudo apt install "
            "python3-gi gir1.2-atspi-2.0), or point EASYSPEAK_ATSPI_PYTHON at an "
            "interpreter that already does."
        )
        return BACKEND_ERROR

    cmd = [python, ATSPI_HELPER, text]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError as exc:
        logger.warning("dictation backend could not start: %s", exc)
        return BACKEND_ERROR

    if "OK" in result.stdout:
        return INSERTED
    if "NO_BACKEND" in result.stdout or result.returncode != 0:
        logger.warning(
            "dictation backend unavailable (PyGObject/AT-SPI missing): %s",
            result.stderr.strip() or "no detail",
        )
        return BACKEND_ERROR
    return NO_FOCUS


def format_text(text):
    """Convert spoken punctuation to actual punctuation."""
    text = text.strip()

    # Strip ALL punctuation Whisper auto-adds; only explicit commands add it back
    text = re.sub(r"[.,!?;:]+", "", text)
    text = text.strip()

    # Punctuation replacements - order matters!
    replacements = [
        # Editing commands
        (r"\s*\bspace\b\s*", " "),
        # Sentence breaks - add space after
        (r"\s*,?\s*\bnew sentence\b\s*", ". "),
        (r"\s*,?\s*\bnext sentence\b\s*", ". "),
        (r"\s*,?\s*\bnew paragraph\b\s*", "\n\n"),
        (r"\s*,?\s*\bnext paragraph\b\s*", "\n\n"),
        (r"\s*,?\s*\bnew para\b\s*", "\n\n"),
        (r"\s*,?\s*\bnew line\b\s*", "\n"),
        (r"\s*,?\s*\bnewline\b\s*", "\n"),
        (r"\s*,?\s*\byou line\b\s*", "\n"),
        (r"\s*,?\s*\bline break\b\s*", "\n"),
        # Punctuation - include common mishearings
        (r"\s*,?\s*\bcomma\b\s*", ", "),
        (r"\s*,?\s*\bkarma\b\s*", ", "),
        (r"\s*,?\s*\bkama\b\s*", ", "),
        (r"\s*,?\s*\bcarma\b\s*", ", "),
        (r"\s*,?\s*\bcalm a\b\s*", ", "),
        (r"\s*,?\s*\bcalm him\b\s*", ", "),
        (r"\s*,?\s*\bcalm up\b\s*", ", "),
        (r"\s*,?\s*\bcome a\b\s*", ", "),
        (r"\s*,?\s*\bcoma\b\s*", ", "),
        (r"\s*,?\s*\bcalmer\b\s*", ", "),
        (r",\s*\.", ","),  # Fix comma followed by period
        (r"\s*,?\s*\bperiod\b\s*", ". "),
        (r"\s*,?\s*\bfull stop\b\s*", ". "),
        (r"\s*,?\s*\.\s*\.+", "."),  # Multiple periods to one
        (r"\s*,?\s*\bquestion mark\b\s*", "? "),
        (r"\s*,?\s*\bexclamation mark\b\s*", "! "),
        (r"\s*,?\s*\bexclamation point\b\s*", "! "),
        (r"\s*,?\s*\bsemicolon\b\s*", "; "),
        (r"\s*,?\s*\bsemi colon\b\s*", "; "),
        (r"\s*,?\s*\bcolon\b\s*", ": "),
        (r"\s*,?\s*\bdash\b\s*", " - "),
        (r"\s*,?\s*\bhyphen\b\s*", "-"),
        (r"\s*,?\s*\bapostrophe\b\s*", "'"),
        (r"\s*,?\s*\bopen quote\b\s*", ' "'),
        (r"\s*,?\s*\bclose quote\b\s*", '" '),
        (r"\s*,?\s*\bquote\b\s*", '"'),
        (r"\s*,?\s*\bopen paren\b\s*", " ("),
        (r"\s*,?\s*\bclose paren\b\s*", ") "),
        # Common words/symbols
        (r"\s*,?\s*\bat sign\b\s*", "@"),
        (r"\s*,?\s*\bampersand\b\s*", "&"),
        (r"\s*,?\s*\bdollar sign\b\s*", "$"),
        (r"\s*,?\s*\bpercent sign\b\s*", "%"),
        (r"\s*,?\s*\bpercent\b\s*", "%"),
        (r"\s*,?\s*\bhashtag\b\s*", "#"),
        (r"\s*,?\s*\bhash\b\s*", "#"),
        (r"\s*,?\s*\basterisk\b\s*", "*"),
        (r"\s*,?\s*\bstar\b\s*", "*"),
        (r"\s*,?\s*\bunderscore\b\s*", "_"),
        (r"\s*,?\s*\bslash\b\s*", "/"),
        (r"\s*,?\s*\bbackslash\b\s*", "\\\\"),
    ]

    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    # Capitalize after sentence endings
    def capitalize_after(match):
        return match.group(1) + match.group(2).upper()

    text = re.sub(r"([.!?]\s+)([a-z])", capitalize_after, text)

    # Capitalize first letter
    if text:
        text = text[0].upper() + text[1:]

    # Clean up extra spaces
    text = re.sub(r" +", " ", text)
    text = re.sub(r" ([.,!?:;])", r"\1", text)

    # Fix double periods
    text = re.sub(r"\.+", ".", text)

    return text.strip()


UNDO_PHRASES = frozenset({"scratch that", "scratch this", "undo that", "undo this"})

# Bare "up" or "right" is ordinary speech, so the arrows need "press" in front.
BARE_KEYS = frozenset(mediakeys.KEYS) - {"up", "down", "left", "right"}


def _handle_keystroke(core, text):
    """Run a keystroke command if that is what was said; True when it was.

    A backspace shortens what "scratch that" still has to remove rather than
    discarding it, so the two can be used in either order on one utterance.
    """
    request = mediakeys.parse_key_request(text.split(), BARE_KEYS)
    scratching = request is None and text in UNDO_PHRASES
    if scratching:
        pending = core.dictation_last_length
        if not pending:
            core.speak("Nothing to scratch")
            return True
        request = (mediakeys.KEYS["backspace"], pending)
    if request is None:
        return False
    keycode, repeats = request
    if not mediakeys.press_key(keycode, repeats):
        core.speak("Dictation isn't set up on this system.")
        return True
    if scratching:
        core.dictation_last_length = 0
    elif keycode == mediakeys.KEYS["backspace"]:
        core.dictation_last_length = max(core.dictation_last_length - repeats, 0)
    else:
        core.dictation_last_length = 0
    return True


def _dictate_utterance(core, text):
    """Format one transcribed utterance, insert it, and give error feedback.

    Shared by the voice `notes` flow and the push-to-talk hotkey. Returns True when
    dictation should stop because insertion failed and the user was told why (no focused
    field, or the backend isn't set up); False to keep going. Text that formats to
    nothing is a silent no-op.
    """
    formatted = format_text(text)
    if not formatted:
        return False
    logger.info("📝 %s", formatted)
    # Add a leading space before words, but not before punctuation.
    if formatted[0].isalpha():
        formatted = " " + formatted
    status = insert_text(formatted)
    if status == INSERTED:
        core.dictation_last_length = len(formatted)
    if status == NO_FOCUS:
        core.speak("No text field focused.")
        return True
    if status == BACKEND_ERROR:
        core.speak("Dictation isn't set up on this system.")
        return True
    return False


# How long each push-to-talk listen waits before looping; kept short so a key
# release ends dictation promptly (the wait also re-checks the held state).
PTT_LISTEN_TIMEOUT = 2


def run_push_to_talk(core, should_continue):
    """Dictate while the activation keys are held (the silent-activation path).

    Mirrors the voice `notes` loop but is gated on `should_continue` — a predicate that
    is True while the keys remain held — instead of a spoken "stop notes": each
    utterance captured from `core` is formatted and inserted until the keys are
    released. The capture waits re-check `should_continue` so releasing stops dictation
    promptly.
    """
    logger.info("🎙️ Push-to-talk dictation — release to end")
    while should_continue():
        core.flush_stream()
        first = core.wait_for_speech(
            timeout=PTT_LISTEN_TIMEOUT, should_continue=should_continue
        )
        if not first:
            continue
        audio = first + core.record_until_silence(should_continue=should_continue)
        text = core.transcribe(audio, prompt=DICTATION_PROMPT, language=LANGUAGE)
        if not text:
            continue
        if _dictate_utterance(core, text.strip().lower()):
            return


def handle(cmd, core):
    """Enter dictation mode on a whole-word "note"/"notes"; return None otherwise.

    Matching whole words (not substrings) keeps unrelated words like "notebook" or
    "noted" from triggering it. While in dictation mode core drives the listening
    (see [`listen_modal`][core.main.EasySpeak.listen_modal]), transcribing speech and
    inserting it into the focused field until "stop notes" is heard — or until the
    mode ends on its own, so an open microphone can't be left dictating unattended.
    """
    words = cmd.split()
    if ("notes" in words or "note" in words) and "stop" not in words:
        core.speak("Dictation")

        logger.info("🎙️ Dictation mode - say 'stop notes' to end")

        try:
            return _dictation_session(core)
        finally:
            # However the session ended -- "stop notes", an idle timeout, the
            # tray -- the browser must not be left in insert mode.
            leave_browser_insert_mode()

    return None


def _dictation_session(core):
    """Transcribe and insert until the user stops; see handle().

    Sentence-length recording, not command-length: the command defaults cut the
    recording off during a mid-sentence pause and truncated anyone who kept going.
    """
    for text in core.listen_modal(
        "dictation",
        prompt=DICTATION_PROMPT,
        timeout=30,
        idle_timeout=60,
        max_record_seconds=MAX_RECORD_SECONDS,
        silence_duration=SILENCE_DURATION,
        wake_gated=False,
        language=LANGUAGE,
    ):
        logger.debug("   Raw: %s", text)

        if is_exit_phrase(text):
            core.speak("Done")
            return True

        if _handle_keystroke(core, text):
            continue

        if _dictate_utterance(core, text):
            return True

    return True
