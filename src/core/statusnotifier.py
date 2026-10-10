"""Tray icon for desktops other than GNOME, such as KDE Plasma.

Implements the freedesktop StatusNotifierItem specification and its D-Bus menu, so any
panel with a StatusNotifierItem host shows it: KDE Plasma, Xfce, Cinnamon, Budgie,
waybar, and GNOME with the AppIndicator extension. On GNOME itself the bundled Shell
extension draws the icon instead.

Runs as its own process, started by [`Tray`][core.tray.Tray] with the control file as
its argument, because serving D-Bus means waiting on the bus, which the audio loop
can't do. It talks to the daemon over the same two channels as the GNOME extension: the
daemon pushes its state through `SetState` on `/org/easyspeak/Desktop`, and the menu
writes its commands into the control file. The process exits when the daemon does.

The icon sits in the panel's status area while EasySpeak is asleep ("Active") and
retreats into the hidden icons while it listens ("Passive"), mirroring the GNOME
indicator, which shows only while asleep. Clicking it toggles between the two.
"""

import contextlib
import os
import sys
from collections import deque
from pathlib import Path

from easyspeak.core import autostart
from jeepney import (
    DBusAddress,
    HeaderFields,
    MatchRule,
    MessageType,
    new_error,
    new_method_call,
    new_method_return,
    new_signal,
)
from jeepney.bus_messages import message_bus
from jeepney.io.blocking import open_dbus_connection

BUS_NAME = "org.easyspeak.Tray"
ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"
CONTROL_PATH = "/org/easyspeak/Desktop"
WATCHER_NAME = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"
INTERFACES = Path(__file__).with_name("statusnotifier.xml").read_text()

STATE_MUTED = "muted"

# How often the helper looks up from the bus to check the daemon is still there.
PARENT_CHECK_INTERVAL = 1.0
CALL_TIMEOUT = 2.0

ICON_LISTENING = "audio-input-microphone"
ICON_MUTED = "microphone-sensitivity-muted"

MENU_TOGGLE = 1
MENU_HELP = 3
MENU_ABOUT = 4
MENU_QUIT = 6
MENU_AUTOSTART = 7


def is_muted(state):
    """Return whether the daemon state means EasySpeak is asleep."""
    return state == STATE_MUTED


def status(state):
    """Return the item's StatusNotifierItem status for a daemon state."""
    return "Active" if is_muted(state) else "Passive"


def icon(state):
    """Return the icon name for a daemon state."""
    return ICON_MUTED if is_muted(state) else ICON_LISTENING


def tooltip(state):
    """Return the tooltip's subtitle for a daemon state."""
    return "Asleep — click to reactivate" if is_muted(state) else "Listening"


def toggle_command(state):
    """Return the command that flips between asleep and listening."""
    return "unmute" if is_muted(state) else "mute"


def menu_items(state, starts_at_login=False):
    """Return the menu entries as `(id, properties)` pairs, in display order.

    "Start at Login" is a checkmark entry, ticked when `starts_at_login`.
    """
    toggle = "Reactivate EasySpeak" if is_muted(state) else "Deactivate EasySpeak"
    return [
        (MENU_TOGGLE, {"label": toggle}),
        (2, {"type": "separator"}),
        (
            MENU_AUTOSTART,
            {
                "label": "Start at Login",
                "toggle-type": "checkmark",
                "toggle-state": int(starts_at_login),
            },
        ),
        (MENU_HELP, {"label": "Help"}),
        (MENU_ABOUT, {"label": "About EasySpeak"}),
        (5, {"type": "separator"}),
        (MENU_QUIT, {"label": "Quit EasySpeak"}),
    ]


def menu_command(item_id, state):
    """Return the command a click on a menu entry sends, or None."""
    return {
        MENU_TOGGLE: toggle_command(state),
        MENU_HELP: "help",
        MENU_ABOUT: "about",
        MENU_QUIT: "quit",
    }.get(item_id)


def write_command(control_file, command):
    """Hand a command to the daemon through the one-shot control file."""
    control_file = Path(control_file)
    control_file.parent.mkdir(parents=True, exist_ok=True)
    control_file.write_text(command)


class StatusNotifier:
    """The tray item, its menu and the daemon's `SetState` on one D-Bus connection."""

    def __init__(self, connection, control_file):
        """Serve on `connection`, writing menu commands to `control_file`."""
        self._bus = connection
        self._control_file = control_file
        self._state = None
        self._revision = 1
        self._registered = False
        self._backlog = deque()
        self._handlers = {
            "SetState": self._on_set_state,
            "Activate": self._on_activate,
            "ContextMenu": self._on_context_menu,
            "SecondaryActivate": self._on_context_menu,
            "Scroll": self._on_context_menu,
            "Get": self._on_get,
            "GetAll": self._on_get_all,
            "Introspect": self._on_introspect,
            "GetLayout": self._on_get_layout,
            "GetGroupProperties": self._on_get_group_properties,
            "GetProperty": self._on_get_property,
            "Event": self._on_event,
            "EventGroup": self._on_event_group,
            "AboutToShow": self._on_about_to_show,
            "AboutToShowGroup": self._on_about_to_show_group,
        }
        self._watcher = DBusAddress(WATCHER_PATH, WATCHER_NAME, WATCHER_NAME)
        self._properties = DBusAddress(
            WATCHER_PATH, WATCHER_NAME, "org.freedesktop.DBus.Properties"
        )

    def start(self):
        """Claim the bus name and register with the panel, if there is one.

        Returns False when another tray process already holds the name.
        """
        reply = self._call(message_bus.RequestName(BUS_NAME, 4))  # do not queue
        if reply is None or reply.body[0] != 1:  # not the primary owner
            return False
        rule = MatchRule(
            type="signal",
            interface="org.freedesktop.DBus",
            member="NameOwnerChanged",
        )
        rule.add_arg_condition(0, WATCHER_NAME)
        self._call(message_bus.AddMatch(rule))
        self._register()
        return True

    def next_message(self, timeout):
        """Return the next incoming message, or None when `timeout` passes first."""
        if self._backlog:
            return self._backlog.popleft()
        try:
            return self._bus.receive(timeout=timeout)
        except TimeoutError:
            return None

    def handle(self, msg):
        """Answer a method call, or react to the panel (re)appearing."""
        fields = msg.header.fields
        if msg.header.message_type == MessageType.signal:
            if fields.get(HeaderFields.member) == "NameOwnerChanged" and msg.body[2]:
                self._register()
            return
        if msg.header.message_type != MessageType.method_call:
            return
        method = fields.get(HeaderFields.member)
        handler = self._handlers.get(method)
        if handler is None:
            self._bus.send(
                new_error(
                    msg, "org.freedesktop.DBus.Error.UnknownMethod", "s", (method,)
                )
            )
            return
        handler(msg, *msg.body)

    # --- calls the panel and the daemon make ---

    def _on_set_state(self, msg, state):
        if is_muted(state) and not self._host_shown():
            self._bus.send(
                new_error(
                    msg,
                    "org.easyspeak.Tray.NoHost",
                    "s",
                    ("No panel shows the tray icon, so it couldn't wake EasySpeak.",),
                )
            )
            return
        self._set_state(state)
        self._reply(msg)

    def _on_activate(self, msg, _x, _y):
        write_command(self._control_file, toggle_command(self._state))
        self._reply(msg)

    def _on_context_menu(self, msg, *_args):
        """Acknowledge clicks that need nothing; the panel opens the menu itself."""
        self._reply(msg)

    def _on_get(self, msg, interface, name):
        value = self._properties_of(msg, interface).get(name)
        if value is None:
            self._bus.send(
                new_error(
                    msg, "org.freedesktop.DBus.Error.UnknownProperty", "s", (name,)
                )
            )
            return
        self._reply(msg, "v", (value,))

    def _on_get_all(self, msg, interface):
        self._reply(msg, "a{sv}", (self._properties_of(msg, interface),))

    def _on_introspect(self, msg):
        self._reply(msg, "s", (INTERFACES,))

    def _on_get_layout(self, msg, _parent, _depth, _names):
        children = [
            ("(ia{sv}av)", (item_id, self._variants(props), []))
            for item_id, props in self._menu_items()
        ]
        root = (0, {"children-display": ("s", "submenu")}, children)
        self._reply(msg, "u(ia{sv}av)", (self._revision, root))

    def _on_get_group_properties(self, msg, ids, _names):
        found = [
            (item_id, self._variants(props))
            for item_id, props in self._menu_items()
            if not ids or item_id in ids
        ]
        self._reply(msg, "a(ia{sv})", (found,))

    def _on_get_property(self, msg, item_id, name):
        props = dict(self._menu_items()).get(item_id, {})
        self._reply(msg, "v", (("s", props.get(name, "")),))

    def _on_event(self, msg, item_id, event, _data, _timestamp):
        self._menu_event(item_id, event)
        self._reply(msg)

    def _on_event_group(self, msg, events):
        for item_id, event, _data, _timestamp in events:
            self._menu_event(item_id, event)
        self._reply(msg, "ai", ([],))

    def _on_about_to_show(self, msg, _item_id):
        self._reply(msg, "b", (False,))

    def _on_about_to_show_group(self, msg, _ids):
        self._reply(msg, "aiai", ([], []))

    # --- internals ---

    def _properties_of(self, msg, interface):
        """Return the properties of the menu or the item, as D-Bus variants."""
        if msg.header.fields.get(HeaderFields.path) == MENU_PATH:
            return {
                "Version": ("u", 3),
                "TextDirection": ("s", "ltr"),
                "Status": ("s", "normal"),
                "IconThemePath": ("as", []),
            }
        if interface not in ("", "org.kde.StatusNotifierItem"):
            return {}
        return {
            "Category": ("s", "ApplicationStatus"),
            "Id": ("s", "easyspeak"),
            "Title": ("s", "EasySpeak"),
            "Status": ("s", status(self._state)),
            "WindowId": ("i", 0),
            "IconName": ("s", icon(self._state)),
            "IconPixmap": ("a(iiay)", []),
            "OverlayIconName": ("s", ""),
            "AttentionIconName": ("s", ""),
            "ToolTip": (
                "(sa(iiay)ss)",
                (icon(self._state), [], "EasySpeak", tooltip(self._state)),
            ),
            "ItemIsMenu": ("b", False),
            "Menu": ("o", MENU_PATH),
        }

    def _menu_items(self):
        return menu_items(self._state, autostart.is_enabled())

    def _variants(self, props):
        return {
            key: ("i", value) if isinstance(value, int) else ("s", value)
            for key, value in props.items()
        }

    def _menu_event(self, item_id, event):
        if event != "clicked":
            return
        if item_id == MENU_AUTOSTART:
            self._toggle_autostart()
            return
        command = menu_command(item_id, self._state)
        if command:
            write_command(self._control_file, command)

    def _toggle_autostart(self):
        """Flip "Start at Login" and show the new checkmark."""
        try:
            autostart.set_enabled(not autostart.is_enabled())
        except OSError as exc:
            sys.stderr.write(f"EasySpeak: couldn't change starting at login: {exc}\n")
            return
        self._revision += 1
        menu = DBusAddress(MENU_PATH, interface="com.canonical.dbusmenu")
        self._bus.send(new_signal(menu, "LayoutUpdated", "ui", (self._revision, 0)))

    def _set_state(self, state):
        """Show a new daemon state: status, icon, tooltip and menu labels."""
        if state == self._state:
            return
        self._state = state
        self._revision += 1
        item = DBusAddress(ITEM_PATH, interface="org.kde.StatusNotifierItem")
        menu = DBusAddress(MENU_PATH, interface="com.canonical.dbusmenu")
        self._bus.send(new_signal(item, "NewStatus", "s", (status(state),)))
        self._bus.send(new_signal(item, "NewIcon"))
        self._bus.send(new_signal(item, "NewToolTip"))
        self._bus.send(new_signal(menu, "LayoutUpdated", "ui", (self._revision, 0)))

    def _register(self):
        """Register with the panel's watcher, also after the panel restarts."""
        msg = new_method_call(
            self._watcher, "RegisterStatusNotifierItem", "s", (BUS_NAME,)
        )
        reply = self._call(msg)
        self._registered = (
            reply is not None and reply.header.message_type == MessageType.method_return
        )

    def _host_shown(self):
        """Return whether a panel is there to show the icon."""
        if not self._registered:
            return False
        msg = new_method_call(
            self._properties,
            "Get",
            "ss",
            (WATCHER_NAME, "IsStatusNotifierHostRegistered"),
        )
        reply = self._call(msg)
        if reply is None or reply.header.message_type != MessageType.method_return:
            return False
        return bool(reply.body[0][1])

    def _call(self, msg):
        """Call a method and return its reply, or None if none came in time.

        Messages arriving meanwhile go to the backlog rather than being lost.
        """
        with self._bus.filter(MatchRule(), queue=self._backlog):
            try:
                return self._bus.send_and_get_reply(msg, timeout=CALL_TIMEOUT)
            except TimeoutError:
                return None

    def _reply(self, msg, signature=None, body=()):
        self._bus.send(new_method_return(msg, signature, body))


def main(argv=None):  # pragma: no cover - needs a session bus; run live
    """Serve the tray icon until the daemon that started it goes away."""
    argv = sys.argv[1:] if argv is None else argv
    daemon = os.getppid()
    with open_dbus_connection("SESSION") as connection:
        tray = StatusNotifier(connection, Path(argv[0]))
        if not tray.start():
            return f"EasySpeak: {BUS_NAME} is taken by another tray."
        with contextlib.suppress(ConnectionError):  # the session ended
            while os.getppid() == daemon:
                msg = tray.next_message(PARENT_CHECK_INTERVAL)
                if msg is not None:
                    tray.handle(msg)
    return None


if __name__ == "__main__":
    sys.exit(main())
