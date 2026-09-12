"""Sleep Plugin - Deactivate the assistant by voice.

"Go to sleep" (or "stop listening") releases the microphone and stops wake-word
detection until the user reactivates EasySpeak from the GNOME tray indicator or
the Quick Settings toggle — whichever the extension is showing, the one way back
since voice control is off until reactivated.
"""

from easyspeak.core.i18n import translator

_ = translator(__file__)

NAME = "sleep"
DESCRIPTION = "Deactivate (sleep) until reactivated from the tray or Quick Settings"

COMMANDS = [
    "go to sleep / stop listening - release the mic (reactivate from the tray icon)",
]

SLEEP_PHRASES = ("go to sleep", "goto sleep", "stop listening")


def handle(cmd, core):
    """Deactivate the assistant on a sleep phrase; return None otherwise."""
    cmd_lower = cmd.lower().strip()
    if any(phrase in cmd_lower for phrase in SLEEP_PHRASES):
        core.speak(_("Voice control turned off."))
        core.deactivate()
        return True
    return None
