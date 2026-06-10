"""Replay multimedia keys through GNOME (Mutter) so the desktop renders its own
native feedback — the volume OSD and the chime — rather than imitating them.

Pressing a volume key does not run any command: gnome-settings-daemon grabs the
raw evdev key and handles the volume change, OSD and chime itself. The only way
to reproduce that exactly is to replay the key. We inject it through Mutter's
RemoteDesktop interface, which needs no special privileges. A RemoteDesktop
session lives only as long as the D-Bus connection that created it, so the whole
CreateSession -> Start -> NotifyKeyboardKeycode -> Stop sequence runs on one
connection.
"""

from jeepney import DBusAddress, new_method_call
from jeepney.io.blocking import open_dbus_connection

_BUS = "org.gnome.Mutter.RemoteDesktop"

_REMOTE_DESKTOP = DBusAddress(
    "/org/gnome/Mutter/RemoteDesktop",
    bus_name=_BUS,
    interface=_BUS,
)


def tap_key(keycode):
    """Press and release one evdev keycode via Mutter RemoteDesktop.

    Raises if RemoteDesktop is unavailable (e.g. a non-GNOME session) so the
    caller can fall back to a silent change.
    """
    conn = open_dbus_connection(bus="SESSION")
    try:
        reply = conn.send_and_get_reply(
            new_method_call(_REMOTE_DESKTOP, "CreateSession")
        )
        session = DBusAddress(
            reply.body[0],
            bus_name=_BUS,
            interface=f"{_BUS}.Session",
        )
        conn.send_and_get_reply(new_method_call(session, "Start"))
        # Synchronous replies guarantee Mutter has processed each event before
        # we move on, so no settling delay is needed before Stop.
        for pressed in (True, False):
            conn.send_and_get_reply(
                new_method_call(
                    session, "NotifyKeyboardKeycode", "ub", (keycode, pressed)
                )
            )
        conn.send_and_get_reply(new_method_call(session, "Stop"))
    finally:
        conn.close()
