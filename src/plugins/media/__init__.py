"""Media Plugin - Playback controls via MPRIS."""

from easyspeak.core.i18n import translator

_ = translator(__file__)

NAME = "media"
DESCRIPTION = "Media playback controls"

COMMANDS = [
    _("play/resume - resume playback"),
    _("pause - pause playback"),
    _("stop the music - pause playback"),
    _("next/skip - next track"),
    _("previous - previous track"),
]

# Playback verbs and the MPRIS action each maps to.
ACTIONS = {
    "play": "play",
    "resume": "play",
    "unpause": "play",
    "pause": "pause",
    "stop": "pause",
    "next": "next",
    "skip": "next",
    "previous": "previous",
    "back": "previous",
}

NEEDS_NOUN = {"stop", "back"}

# Words naming what is being played. Ignored when picking the verb, so "pause the
# music" and "pause" are the same command, and present to satisfy NEEDS_NOUN.
MEDIA_NOUNS = {
    "music",
    "song",
    "songs",
    "track",
    "tracks",
    "playback",
    "player",
    "media",
    "video",
    "audio",
    "playing",
}

# Words that carry no meaning for this plugin.
FILLER = {"the", "a", "an", "my", "this", "that", "it", "please"}

# What to say once the action has actually reached a player.
FEEDBACK = {
    "play": _("Playing."),
    "pause": _("Paused."),
    "next": _("Next."),
    "previous": _("Previous."),
}

core = None


def setup(c):
    """Store the core reference for use by the plugin's handlers."""
    global core
    core = c


def get_media_players(core):
    """Return the bus names of all running MPRIS media players."""
    result = core.host_run(
        [
            "dbus-send",
            "--session",
            "--dest=org.freedesktop.DBus",
            "--type=method_call",
            "--print-reply",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus.ListNames",
        ]
    )
    return [
        line.split('"')[1]
        for line in result.stdout.split("\n")
        if "org.mpris.MediaPlayer2." in line
    ]


def media_control(action, core):
    """Send an MPRIS action (play/pause/next/previous) to every running player.

    Returns False if no player is running or the action is unknown.
    """
    players = get_media_players(core)
    if not players:
        return False

    method = {
        "play": "Play",
        "pause": "Pause",
        "next": "Next",
        "previous": "Previous",
    }.get(action)

    if not method:
        return False

    for player in players:
        core.host_run(
            [
                "dbus-send",
                "--session",
                "--type=method_call",
                f"--dest={player}",
                "/org/mpris/MediaPlayer2",
                f"org.mpris.MediaPlayer2.Player.{method}",
            ]
        )
    return True


def _action_for(cmd):
    """Return the MPRIS action a command asks for, or None if it isn't ours.

    Matching is on whole words after filler and media nouns are removed, and what
    is left has to be exactly one playback verb. Substring matching used to make
    this plugin answer for anything containing a verb -- "make the display brighter"
    was caught by the "play" inside "display" and swallowed with a cheery
    "Playing." -- and requiring a lone verb also keeps "next tab" with the browser.
    """
    words = [word.strip(".,!?") for word in cmd.lower().split()]
    words = [word for word in words if word]
    has_noun = any(word in MEDIA_NOUNS for word in words)
    verbs = [word for word in words if word not in FILLER and word not in MEDIA_NOUNS]
    if len(verbs) != 1:
        return None
    verb = verbs[0]
    if verb in NEEDS_NOUN and not has_noun:
        return None
    return ACTIONS.get(verb)


def handle(cmd, core):
    """Map a playback command to an MPRIS action; return None if not media.

    The reply now follows the action rather than preceding it: this used to
    announce "Playing." and return handled even when no player was running, so a
    command that did nothing at all sounded like it had worked.
    """
    action = _action_for(cmd)
    if action is None:
        return None  # Not handled

    if not media_control(action, core):
        core.speak(_("No media player is running."))
        return True

    core.speak(FEEDBACK[action])
    return True
