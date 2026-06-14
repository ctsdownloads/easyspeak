"""Media Plugin - Playback controls via MPRIS."""

NAME = "media"
DESCRIPTION = "Media playback controls"

COMMANDS = [
    "play - resume playback",
    "pause - pause playback",
    "next/skip - next track",
    "previous/back - previous track",
]

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


def handle(cmd, core):
    """Map a playback command to an MPRIS action; return None if not media."""
    # "stop the music"/"stop playing" mean pause; bare "stop" isn't a media command.
    # Whole-word match so "stop tracking" (eye tracking) isn't caught by "track".
    words = cmd.split()
    stop_music = "stop" in words and any(
        word in words
        for word in ("music", "song", "playback", "track", "player", "playing", "play")
    )

    if "pause" in cmd or stop_music:
        core.speak("Paused.")
        media_control("pause", core)
        return True

    if "play" in cmd and "pause" not in cmd:
        core.speak("Playing.")
        media_control("play", core)
        return True

    if "next" in cmd or "skip" in cmd:
        core.speak("Next.")
        media_control("next", core)
        return True

    if "previous" in cmd or "back" in cmd:
        core.speak("Previous.")
        media_control("previous", core)
        return True

    return None  # Not handled
