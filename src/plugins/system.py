"""
System Plugin - Volume, brightness, do not disturb
"""

NAME = "system"
DESCRIPTION = "System controls"

COMMANDS = [
    "volume up/down - adjust volume",
    "mute - toggle mute",
    "brightness up/down - adjust screen brightness",
    "do not disturb on/off - toggle notifications",
]

core = None


# evdev keycodes for the multimedia keys (stable Linux input ABI). Replaying these
# lets gnome-settings-daemon produce its own change and native OSD (plus the chime
# for volume) -- identical to pressing the keys, because it *is* the keys.
KEY_MUTE = 113
KEY_VOLUME_DOWN = 114
KEY_VOLUME_UP = 115
KEY_BRIGHTNESS_DOWN = 224
KEY_BRIGHTNESS_UP = 225

# gdbus invocation for org.gnome.SettingsDaemon.Power.Screen, minus the method name.
_POWER_SCREEN = [
    "gdbus",
    "call",
    "--session",
    "--dest",
    "org.gnome.SettingsDaemon.Power",
    "--object-path",
    "/org/gnome/SettingsDaemon/Power",
    "--method",
]


def setup(c):
    global core
    core = c


def _media_key(core, keycode, fallback):
    """Replay a multimedia key for the desktop's native OSD (and chime for volume).

    Falls back to the given command if key injection is unavailable (e.g. a
    non-GNOME session); the setting still changes, just without the feedback.
    """
    if not core.tap_key(keycode):
        core.host_run(fallback)


def volume_up(core):
    _media_key(
        core, KEY_VOLUME_UP, ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "10%+"]
    )


def volume_down(core):
    _media_key(
        core, KEY_VOLUME_DOWN, ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "10%-"]
    )


def volume_mute(core):
    _media_key(core, KEY_MUTE, ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"])


def brightness_up(core):
    _media_key(
        core,
        KEY_BRIGHTNESS_UP,
        [*_POWER_SCREEN, "org.gnome.SettingsDaemon.Power.Screen.StepUp"],
    )


def brightness_down(core):
    _media_key(
        core,
        KEY_BRIGHTNESS_DOWN,
        [*_POWER_SCREEN, "org.gnome.SettingsDaemon.Power.Screen.StepDown"],
    )


def dnd_on(core):
    core.host_run(
        ["gsettings", "set", "org.gnome.desktop.notifications", "show-banners", "false"]
    )


def dnd_off(core):
    core.host_run(
        ["gsettings", "set", "org.gnome.desktop.notifications", "show-banners", "true"]
    )


def handle(cmd, core):
    # Volume -- "louder"/"quieter" etc. work on their own, without "volume"/"sound".
    # Match whole words so "silent" doesn't fire on "silently", "softer" on "softest"...
    words = cmd.split()
    louder = "louder" in words
    quieter = any(word in words for word in ("quieter", "softer", "silent"))
    # No spoken feedback for volume/mute: GNOME's native OSD and chime already
    # acknowledge the change (and a spoken reply would be inaudible once muted).
    if "volume" in cmd or "sound" in cmd or louder or quieter:
        if "up" in cmd or louder:
            volume_up(core)
            return True
        elif "down" in cmd or quieter:
            volume_down(core)
            return True
        elif "mute" in cmd or "unmute" in cmd:
            volume_mute(core)
            return True

    if "mute" in cmd:
        volume_mute(core)
        return True

    # Brightness
    if "brightness" in cmd or "screen" in cmd:
        if "up" in cmd or "brighter" in cmd:
            core.speak("Brighter.")
            brightness_up(core)
            return True
        elif "down" in cmd or "dimmer" in cmd or "darker" in cmd:
            core.speak("Dimmer.")
            brightness_down(core)
            return True

    # Do Not Disturb
    if "do not disturb" in cmd or "dnd" in cmd or "notifications" in cmd:
        if "on" in cmd or "enable" in cmd:
            core.speak("Do not disturb on.")
            dnd_on(core)
            return True
        elif "off" in cmd or "disable" in cmd:
            core.speak("Do not disturb off.")
            dnd_off(core)
            return True

    return None  # Not handled
