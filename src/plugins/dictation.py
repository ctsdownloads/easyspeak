"""Dictation Plugin - Voice to text via AT-SPI."""

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

NAME = "dictation"
DESCRIPTION = "Voice dictation into any text field"

COMMANDS = [
    "notes - start dictation mode (say 'stop notes' to end)",
    "Punctuation: comma, period, question mark, exclamation mark, colon, semicolon",
    "Editing: backspace, space, tab",
    "Structure: new sentence, new line, new paragraph, enter",
    "Symbols: apostrophe, quote, dash, hyphen, at sign, hashtag, percent, asterisk",
]

core = None

# Prompt to bias Whisper toward recognizing punctuation commands
DICTATION_PROMPT = (
    "comma, period, new sentence, new paragraph, new line, question mark, "
    "exclamation mark, colon, semicolon, stop notes, backspace, space, tab, "
    "enter, apostrophe, quote, dash, hyphen, at sign, hashtag, percent"
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
    ensure_gnome_accessibility()
    # Offer dictation to the keyboard (silent) activation path too: core runs
    # this while the hotkey combo is held, with no wake word spoken.
    if hasattr(c, "register_push_to_talk"):
        c.register_push_to_talk(
            lambda should_continue: run_push_to_talk(c, should_continue)
        )


# insert_text() outcomes — kept distinct so the spoken feedback is accurate:
# the text went in, no editable field was focused, or the AT-SPI backend
# couldn't even start (no PyGObject/typelib, no accessibility bus).
INSERTED = "inserted"
NO_FOCUS = "no_focus"
BACKEND_ERROR = "backend_error"

# The AT-SPI logic lives in a sibling module run as a script in an interpreter
# that has PyGObject (see atspi_python). It's a real file, not an embedded
# string, so it gets linted and unit-tested.
ATSPI_HELPER = str(Path(__file__).with_name("_atspi_insert.py"))


def atspi_python():
    """Path to the interpreter that runs the AT-SPI helper.

    The helper needs PyGObject and the AT-SPI typelib, which the app's own venv usually
    lacks. `EASYSPEAK_ATSPI_PYTHON` lets the packaging point at an interpreter that has
    them (the Nix flake sets it); otherwise we fall back to the system `python3`, where
    distro packages like `python3-gi` typically live.
    """
    return os.environ.get("EASYSPEAK_ATSPI_PYTHON") or "python3"


def insert_text(text):
    """Insert text via AT-SPI.

    Returns one of INSERTED, NO_FOCUS or BACKEND_ERROR so the caller can give feedback
    that matches the real cause instead of always blaming focus.
    """
    cmd = [atspi_python(), ATSPI_HELPER, text]
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
        (r"\s*backspace\s*", "\b"),
        (r"\s*back space\s*", "\b"),
        (r"\s*delete\s*", "\b"),
        (r"\s*space\s*", " "),
        (r"\s*tab\s*", "\t"),
        # Sentence breaks - add space after
        (r"\s*,?\s*new sentence\s*", ". "),
        (r"\s*,?\s*next sentence\s*", ". "),
        (r"\s*,?\s*new paragraph\s*", "\n\n"),
        (r"\s*,?\s*next paragraph\s*", "\n\n"),
        (r"\s*,?\s*new para\s*", "\n\n"),
        (r"\s*,?\s*new line\s*", "\n"),
        (r"\s*,?\s*newline\s*", "\n"),
        (r"\s*,?\s*you line\s*", "\n"),
        (r"\s*,?\s*line break\s*", "\n"),
        (r"\s*,?\s*enter\s*", "\n"),
        # Punctuation - include common mishearings
        (r"\s*,?\s*comma\s*", ", "),
        (r"\s*,?\s*karma\s*", ", "),
        (r"\s*,?\s*kama\s*", ", "),
        (r"\s*,?\s*carma\s*", ", "),
        (r"\s*,?\s*calm a\s*", ", "),
        (r"\s*,?\s*calm him\s*", ", "),
        (r"\s*,?\s*calm up\s*", ", "),
        (r"\s*,?\s*come a\s*", ", "),
        (r"\s*,?\s*coma\s*", ", "),
        (r"\s*,?\s*calmer\s*", ", "),
        (r",\s*\.", ","),  # Fix comma followed by period
        (r"\s*,?\s*period\s*", ". "),
        (r"\s*,?\s*full stop\s*", ". "),
        (r"\s*,?\s*\.\s*\.+", "."),  # Multiple periods to one
        (r"\s*,?\s*question mark\s*", "? "),
        (r"\s*,?\s*exclamation mark\s*", "! "),
        (r"\s*,?\s*exclamation point\s*", "! "),
        (r"\s*,?\s*colon\s*", ": "),
        (r"\s*,?\s*semicolon\s*", "; "),
        (r"\s*,?\s*semi colon\s*", "; "),
        (r"\s*,?\s*dash\s*", " - "),
        (r"\s*,?\s*hyphen\s*", "-"),
        (r"\s*,?\s*apostrophe\s*", "'"),
        (r"\s*,?\s*open quote\s*", ' "'),
        (r"\s*,?\s*close quote\s*", '" '),
        (r"\s*,?\s*quote\s*", '"'),
        (r"\s*,?\s*open paren\s*", " ("),
        (r"\s*,?\s*close paren\s*", ") "),
        # Common words/symbols
        (r"\s*,?\s*at sign\s*", "@"),
        (r"\s*,?\s*ampersand\s*", "&"),
        (r"\s*,?\s*dollar sign\s*", "$"),
        (r"\s*,?\s*percent sign\s*", "%"),
        (r"\s*,?\s*percent\s*", "%"),
        (r"\s*,?\s*hashtag\s*", "#"),
        (r"\s*,?\s*hash\s*", "#"),
        (r"\s*,?\s*asterisk\s*", "*"),
        (r"\s*,?\s*star\s*", "*"),
        (r"\s*,?\s*underscore\s*", "_"),
        (r"\s*,?\s*slash\s*", "/"),
        (r"\s*,?\s*backslash\s*", "\\\\"),
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
        text = core.transcribe(audio, prompt=DICTATION_PROMPT)
        if not text:
            continue
        if _dictate_utterance(core, text.strip().lower()):
            return


def handle(cmd, core):
    """Enter dictation mode on a whole-word "note"/"notes"; return None otherwise.

    Matching whole words (not substrings) keeps unrelated words like "notebook" or
    "noted" from triggering it. While in dictation mode it loops, transcribing speech
    and inserting it into the focused field until "stop notes" is heard.
    """
    words = cmd.split()
    if ("notes" in words or "note" in words) and "stop" not in words:
        core.speak("Dictation")

        logger.info("🎙️ Dictation mode - say 'stop notes' to end")

        while True:
            # Clear buffer and wait for speech
            core.stream.read(
                core.stream.get_read_available(), exception_on_overflow=False
            )
            first = core.wait_for_speech(timeout=30)

            if not first:
                logger.debug("   (waiting...)")
                continue

            audio = first + core.record_until_silence()
            text = core.transcribe(audio, prompt=DICTATION_PROMPT)

            if not text:
                continue

            text = text.strip().lower()
            logger.debug("   Raw: %s", text)

            # Check for exit - include mishearings
            if any(
                x in text
                for x in [
                    "stop notes",
                    "stop note",
                    "end notes",
                    "exit notes",
                    "stop nurts",
                    "stop nots",
                    "stop nuts",
                    "stopnotes",
                    "done notes",
                    "finish notes",
                    "close notes",
                    "closed notes",
                ]
            ):
                core.speak("Done")
                return True

            # Format and insert
            if _dictate_utterance(core, text):
                return True

    return None
