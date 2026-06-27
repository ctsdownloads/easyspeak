"""Sleep Plugin - Deactivate the assistant by voice.

"Go to sleep" (or "stop listening") releases the microphone and stops wake-word
detection until the user reactivates EasySpeak from the GNOME tray indicator or
the Quick Settings toggle — whichever the extension is showing, the one way back
since voice control is off until reactivated.
"""

NAME = "sleep"
DESCRIPTION = "Deactivate (sleep) until reactivated from the tray or Quick Settings"

COMMANDS = [
    "go to sleep / stop listening - release the mic (reactivate from the tray icon)",
]

# Matched as substrings against the wake-stripped command. Kept tight so they
# don't swallow unrelated phrases; "goto" covers a common transcription of
# "go to", and "stop listening" also covers "stop listening now". Bare "stop"
# is deliberately excluded — too ambiguous to mean sleep.
SLEEP_PHRASES = ("go to sleep", "goto sleep", "stop listening")


def handle(cmd, core):
    """Deactivate the assistant on a sleep phrase; return None otherwise."""
    cmd_lower = cmd.lower().strip()
    if any(phrase in cmd_lower for phrase in SLEEP_PHRASES):
        # Speaking also ends the command session promptly (core marks the round
        # as having spoken, so it stops listening for follow-ups). The tray stays
        # silent on this voice path to avoid repeating it, but still explains if
        # it can't actually engage sleep (no indicator to reactivate from).
        core.speak("Voice control turned off.")
        core.deactivate()
        return True
    return None
