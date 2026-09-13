"""System Plugin - Volume, brightness, do not disturb."""

from easyspeak.core.i18n import translator
from easyspeak.core.vocabulary import Vocabulary

_ = translator(__file__)
vocab = Vocabulary(__file__)

NAME = "system"
DESCRIPTION = "System controls"

COMMANDS = [
    _("volume up/down - adjust volume"),
    _("mute - toggle mute"),
    _("brightness up/down - adjust screen brightness"),
    _("do not disturb on/off - toggle notifications"),
]

core = None


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
    """Store the core reference for use by the plugin's handlers."""
    global core
    core = c


def _media_key(core, keycode, fallback):
    """Replay a multimedia key for the desktop's native OSD (and chime for volume).

    Falls back to the given command if key injection is unavailable (e.g. a non-GNOME
    session); the setting still changes, just without the feedback.
    """
    if not core.tap_key(keycode):
        core.host_run(fallback)


def volume_up(core):
    """Raise the volume one step."""
    _media_key(
        core, KEY_VOLUME_UP, ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "10%+"]
    )


def volume_down(core):
    """Lower the volume one step."""
    _media_key(
        core, KEY_VOLUME_DOWN, ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "10%-"]
    )


def volume_mute(core):
    """Toggle mute on the default audio sink."""
    _media_key(core, KEY_MUTE, ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"])


def volume_max(core):
    """Jump near the top (85%, not a blast); no media key does this."""
    core.host_run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "85%"])


def volume_min(core):
    """Drop low (15%, still audible — not a mute), set directly like volume_max."""
    core.host_run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "15%"])


def brightness_up(core):
    """Raise screen brightness one step."""
    _media_key(
        core,
        KEY_BRIGHTNESS_UP,
        [*_POWER_SCREEN, "org.gnome.SettingsDaemon.Power.Screen.StepUp"],
    )


def brightness_down(core):
    """Lower screen brightness one step."""
    _media_key(
        core,
        KEY_BRIGHTNESS_DOWN,
        [*_POWER_SCREEN, "org.gnome.SettingsDaemon.Power.Screen.StepDown"],
    )


def dnd_on(core):
    """Enable do-not-disturb by hiding notification banners."""
    core.host_run(
        ["gsettings", "set", "org.gnome.desktop.notifications", "show-banners", "false"]
    )


def dnd_off(core):
    """Disable do-not-disturb by showing notification banners again."""
    core.host_run(
        ["gsettings", "set", "org.gnome.desktop.notifications", "show-banners", "true"]
    )


def handle(cmd, core):
    """Route a volume/brightness/DND command; return None if none matched.

    Every word comes from the vocabulary table and is matched whole, so "silent"
    doesn't fire on "silently", "softer" on "softest", and "screenshot" isn't read
    as a screen command.
    """
    says = lambda key: vocab.says(cmd, key)  # noqa: E731

    # Volume -- "louder"/"quieter" etc. work on their own, without "volume"/"sound".
    if says("very"):
        if says("loud"):
            volume_max(core)
            return True
        if says("quiet"):
            volume_min(core)
            return True
    louder, quieter = says("louder"), says("quieter")
    # No spoken feedback for volume/mute: GNOME's native OSD and chime already
    # acknowledge the change (and a spoken reply would be inaudible once muted).
    if says("volume") or louder or quieter:
        if says("up") or louder:
            volume_up(core)
            return True
        if says("down") or quieter:
            volume_down(core)
            return True
        if says("mute"):
            volume_mute(core)
            return True

    if says("mute"):
        volume_mute(core)
        return True

    if says("brightness"):
        if says("up") or says("brighter"):
            core.speak(_("Brighter."))
            brightness_up(core)
            return True
        if says("down") or says("dimmer"):
            core.speak(_("Dimmer."))
            brightness_down(core)
            return True

    dnd_named = says("dnd")
    if dnd_named or says("notifications"):
        turning_on, turning_off = says("on"), says("off")
        if not (turning_on or turning_off):
            return None  # a bare "notifications" says nothing about direction
        # Silencing notifications is do-not-disturb ON, so the notifications
        # vocabulary maps the other way round.
        if turning_on if dnd_named else turning_off:
            core.speak(_("Do not disturb on."))
            dnd_on(core)
        else:
            core.speak(_("Do not disturb off."))
            dnd_off(core)
        return True

    return None  # Not handled
