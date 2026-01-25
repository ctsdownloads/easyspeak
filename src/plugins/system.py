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


def setup(c):
    global core
    core = c


def volume_up(core):
    core.host_run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "10%+"])


def volume_down(core):
    core.host_run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "10%-"])


def volume_mute(core):
    core.host_run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"])


def brightness_up(core):
    core.host_run(
        [
            "gdbus",
            "call",
            "--session",
            "--dest",
            "org.gnome.SettingsDaemon.Power",
            "--object-path",
            "/org/gnome/SettingsDaemon/Power",
            "--method",
            "org.gnome.SettingsDaemon.Power.Screen.StepUp",
        ]
    )


def brightness_down(core):
    core.host_run(
        [
            "gdbus",
            "call",
            "--session",
            "--dest",
            "org.gnome.SettingsDaemon.Power",
            "--object-path",
            "/org/gnome/SettingsDaemon/Power",
            "--method",
            "org.gnome.SettingsDaemon.Power.Screen.StepDown",
        ]
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
    # Volume
    if "volume" in cmd or "sound" in cmd:
        if "up" in cmd or "louder" in cmd:
            volume_up(core)
            core.speak("Volume up.")
            return True
        elif "down" in cmd or "quieter" in cmd or "softer" in cmd:
            volume_down(core)
            core.speak("Volume down.")
            return True
        elif "mute" in cmd or "unmute" in cmd:
            volume_mute(core)
            core.speak("Toggled mute.")
            return True

    if "mute" in cmd:
        volume_mute(core)
        core.speak("Toggled mute.")
        return True

    # Brightness
    if "brightness" in cmd or "screen" in cmd:
        if "up" in cmd or "brighter" in cmd:
            brightness_up(core)
            core.speak("Brighter.")
            return True
        elif "down" in cmd or "dimmer" in cmd or "darker" in cmd:
            brightness_down(core)
            core.speak("Dimmer.")
            return True

    # Do Not Disturb
    if "do not disturb" in cmd or "dnd" in cmd or "notifications" in cmd:
        if "on" in cmd or "enable" in cmd:
            dnd_on(core)
            core.speak("Do not disturb on.")
            return True
        elif "off" in cmd or "disable" in cmd:
            dnd_off(core)
            core.speak("Do not disturb off.")
            return True

    return None  # Not handled
