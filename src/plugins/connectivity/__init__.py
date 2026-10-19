"""Connectivity Plugin - Wi-Fi, airplane mode, Bluetooth."""

import logging

from easyspeak.core.i18n import translator
from easyspeak.core.vocabulary import Vocabulary

logger = logging.getLogger(__name__)

_ = translator(__file__)
vocab = Vocabulary(__file__)

NAME = "connectivity"
DESCRIPTION = "Wi-Fi, airplane mode and Bluetooth"

ON_OFF = f"{vocab.say('on', limit=1)}/{vocab.say('off', limit=1)}"

COMMANDS = [
    f"{vocab.say('wifi', limit=1)} {ON_OFF} - " + _("turn Wi-Fi on or off"),
    f"{vocab.say('airplane', limit=1)} {ON_OFF} - " + _("turn airplane mode on or off"),
    f"{vocab.say('bluetooth', limit=1)} {ON_OFF} - " + _("turn Bluetooth on or off"),
]

core = None

# gdbus Properties.Set calls, minus the property name and value.
_NETWORK_MANAGER = [
    "gdbus",
    "call",
    "--system",
    "--dest",
    "org.freedesktop.NetworkManager",
    "--object-path",
    "/org/freedesktop/NetworkManager",
    "--method",
    "org.freedesktop.DBus.Properties.Set",
    "org.freedesktop.NetworkManager",
]
_RFKILL = [
    "gdbus",
    "call",
    "--session",
    "--dest",
    "org.gnome.SettingsDaemon.Rfkill",
    "--object-path",
    "/org/gnome/SettingsDaemon/Rfkill",
    "--method",
    "org.freedesktop.DBus.Properties.Set",
    "org.gnome.SettingsDaemon.Rfkill",
]


def setup(c):
    """Store the core reference for use by the plugin's handlers."""
    global core
    core = c


def _set(core, call, prop, *, value):
    """Set one boolean property over D-Bus; False if it was refused."""
    result = core.host_run([*call, prop, "<true>" if value else "<false>"])
    if result.returncode != 0:
        logger.warning("Could not set %s: %s", prop, result.stderr.strip())
        return False
    return True


def set_wifi(core, *, on):
    """Turn the Wi-Fi radio on or off through NetworkManager."""
    return _set(core, _NETWORK_MANAGER, "WirelessEnabled", value=on)


def set_airplane_mode(core, *, on):
    """Turn GNOME's airplane mode on or off."""
    return _set(core, _RFKILL, "AirplaneMode", value=on)


def set_bluetooth(core, *, on):
    """Turn Bluetooth on or off the way GNOME's quick settings do."""
    return _set(core, _RFKILL, "BluetoothAirplaneMode", value=not on)


def _switch(core, setter, *, on, said_on, said_off):
    """Flip a switch and say what happened, or that it couldn't be done."""
    if setter(core, on=on):
        core.speak(said_on if on else said_off)
    else:
        core.speak(_("Sorry, I couldn't change that."))
    return True


def handle(cmd, core):
    """Route a Wi-Fi/airplane/Bluetooth command; return None if none matched.

    A command needs exactly one direction, so "wifi" alone or "wifi on and
    bluetooth off" is left alone rather than guessed at.
    """
    says = lambda key: vocab.says(cmd, key)  # noqa: E731

    on = says("on")
    if on == says("off"):
        return None

    if says("airplane"):
        return _switch(
            core,
            set_airplane_mode,
            on=on,
            said_on=_("Airplane mode on."),
            said_off=_("Airplane mode off."),
        )
    if says("wifi"):
        return _switch(
            core,
            set_wifi,
            on=on,
            said_on=_("Wi-Fi on."),
            said_off=_("Wi-Fi off."),
        )
    if says("bluetooth"):
        return _switch(
            core,
            set_bluetooth,
            on=on,
            said_on=_("Bluetooth on."),
            said_off=_("Bluetooth off."),
        )
    return None
