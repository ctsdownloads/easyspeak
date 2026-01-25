"""
Dictation Plugin - Voice to text via AT-SPI
"""

NAME = "dictation"
DESCRIPTION = "Voice dictation into any text field"

COMMANDS = [
    "notes - start dictation mode (say 'stop notes' to end)",
    "Punctuation: comma, period, question mark, exclamation mark, colon, semicolon",
    "Editing: backspace, space, tab",
    "Structure: new sentence, new line, new paragraph, enter",
    "Symbols: apostrophe, quote, dash, hyphen, at sign, hashtag, percent, asterisk",
]

import subprocess
import os
import re

core = None

# Prompt to bias Whisper toward recognizing punctuation commands
DICTATION_PROMPT = "comma, period, new sentence, new paragraph, new line, question mark, exclamation mark, colon, semicolon, stop notes, backspace, space, tab, enter, apostrophe, quote, dash, hyphen, at sign, hashtag, percent"


def setup(c):
    global core
    core = c


ATSPI_INSERT_SCRIPT = """
import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi
import sys

text = sys.argv[1] if len(sys.argv) > 1 else ""

def find_focused_editable(obj, depth=0):
    if depth > 25:
        return None
    try:
        state = obj.get_state_set()
        if state.contains(Atspi.StateType.FOCUSED) and state.contains(Atspi.StateType.EDITABLE):
            return obj
        for i in range(obj.get_child_count()):
            result = find_focused_editable(obj.get_child_at_index(i), depth+1)
            if result:
                return result
    except:
        pass
    return None

desktop = Atspi.get_desktop(0)
for i in range(desktop.get_child_count()):
    app = desktop.get_child_at_index(i)
    result = find_focused_editable(app)
    if result:
        try:
            pos = result.get_caret_offset()
        except:
            pos = -1
        
        # Handle special characters
        for char in text:
            if char == chr(8):  # backspace
                if pos > 0:
                    result.delete_text(pos - 1, pos)
                    pos -= 1
            else:
                result.insert_text(pos, char, len(char.encode('utf-8')))
                pos += 1
        
        print("OK")
        sys.exit(0)

print("NO_FOCUS")
"""


def insert_text(text):
    """Insert text via AT-SPI"""
    cmd = ["python3", "-c", ATSPI_INSERT_SCRIPT, text]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return "OK" in result.stdout


def format_text(text):
    """Convert spoken punctuation to actual punctuation"""
    text = text.strip()

    # Strip ALL punctuation Whisper auto-adds - only explicit commands create punctuation
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


def handle(cmd, core):
    if ("notes" in cmd or "note" in cmd) and "stop" not in cmd:
        core.speak("Dictation")

        print("🎙️ Dictation mode - say 'stop notes' to end")

        while True:
            # Clear buffer and wait for speech
            core.stream.read(
                core.stream.get_read_available(), exception_on_overflow=False
            )
            first = core.wait_for_speech(timeout=30)

            if not first:
                print("   (waiting...)")
                continue

            audio = first + core.record_until_silence()
            text = core.transcribe(audio, prompt=DICTATION_PROMPT)

            if not text:
                continue

            text = text.strip().lower()
            print(f"   Raw: {text}")

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
            formatted = format_text(text)
            print(f"📝 {formatted}")

            if formatted:
                # Add space before words, not before punctuation
                if formatted[0].isalpha():
                    formatted = " " + formatted

                if not insert_text(formatted):
                    core.speak("No text field focused.")
                    return True

        return True

    return None
