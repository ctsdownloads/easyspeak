"""Sleep Plugin - Deactivate the assistant by voice.

"Go to sleep" (or "stop listening") releases the microphone and stops wake-word
detection until the user reactivates EasySpeak from the GNOME tray indicator. It
pairs with that panel icon, which only appears while the assistant is asleep
(the one way back, since voice control is off until reactivated).
"""

NAME = "sleep"
DESCRIPTION = "Deactivate (sleep) until reactivated from the tray"

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
        # Announce only the attempt. The tray controller confirms once sleep
        # actually engages ("Reactivate me from the tray...") or, if it can't
        # reach the indicator, explains and stays awake — so we never promise a
        # tray that isn't there.
        core.speak("Going to sleep.")
        core.deactivate()
        return True
    return None
