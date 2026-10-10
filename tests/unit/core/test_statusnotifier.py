"""Tests for the StatusNotifierItem tray icon (core.statusnotifier)."""

import contextlib
from collections import deque
from pathlib import Path

import pytest
from easyspeak.core.statusnotifier import (
    BUS_NAME,
    CONTROL_PATH,
    INTERFACES,
    ITEM_PATH,
    MENU_PATH,
    WATCHER_NAME,
    StatusNotifier,
    menu_command,
    menu_items,
)
from jeepney import (
    DBusAddress,
    HeaderFields,
    MessageType,
    new_error,
    new_method_call,
    new_method_return,
    new_signal,
)
from jeepney.low_level import parse_signature
from lxml import etree

ITEM = "org.kde.StatusNotifierItem"
MENU = "com.canonical.dbusmenu"
PROPERTIES = "org.freedesktop.DBus.Properties"
DESKTOP = "org.easyspeak.Desktop"


class FakeBus:
    """A session bus connection that records what the tray sends.

    `panel` decides how the watcher answers: "shown" (a panel shows the icon),
    "no host" (the watcher runs, but nothing shows icons), "hung" (it never
    answers) or None (no watcher).
    """

    def __init__(self, panel="shown", name_reply=1):
        self.panel = panel
        self.name_reply = name_reply
        self.sent = []
        self.incoming = deque()

    def send(self, msg):
        self.sent.append(msg)

    def send_and_get_reply(self, msg, timeout=None):
        member = msg.header.fields[HeaderFields.member]
        if member == "RequestName":
            return new_method_return(msg, "u", (self.name_reply,))
        if member == "AddMatch":
            return new_method_return(msg)
        if self.panel == "hung":
            raise TimeoutError
        if self.panel is None:
            return new_error(msg, "org.freedesktop.DBus.Error.ServiceUnknown")
        if member == "RegisterStatusNotifierItem":
            return new_method_return(msg)
        return new_method_return(msg, "v", (("b", self.panel == "shown"),))

    def filter(self, rule, queue=None):
        return contextlib.nullcontext(queue)

    def receive(self, timeout=None):
        if not self.incoming:
            raise TimeoutError
        return self.incoming.popleft()

    def replies(self):
        return [m for m in self.sent if m.header.message_type != MessageType.signal]

    def signals(self):
        return [
            m.header.fields[HeaderFields.member]
            for m in self.sent
            if m.header.message_type == MessageType.signal
        ]


def call(path, interface, method, signature=None, body=()):
    """Build an incoming method call, as the panel or the daemon would send it."""
    msg = new_method_call(
        DBusAddress(path, BUS_NAME, interface), method, signature, body
    )
    msg.header.serial = 7
    return msg


@pytest.fixture
def control(tmp_path):
    return tmp_path / "control"


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    """Keep the autostart entries in a throwaway home, away from the real ones."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_DIRS", str(tmp_path / "xdg"))
    return tmp_path


def started(bus, control):
    tray = StatusNotifier(bus, control)
    assert tray.start()
    bus.sent.clear()
    return tray


def answer(tray, bus, msg):
    """Hand the tray one call and return its reply."""
    tray.handle(msg)
    return bus.replies()[-1]


class TestStart:
    """Claiming the bus name and registering with the panel."""

    def test_starts_and_registers(self, control):
        """With a panel present, the tray becomes available."""
        assert StatusNotifier(FakeBus(), control).start()

    def test_refuses_when_another_tray_holds_the_name(self, control):
        """A second tray process gives up rather than queueing for the name."""
        assert not StatusNotifier(FakeBus(name_reply=3), control).start()


class TestSetState:
    """The daemon's state push, and its refusal when no panel would show it."""

    def test_asleep_shows_the_icon(self, control):
        """Asleep moves the icon out of the hidden ones and announces it."""
        bus = FakeBus()
        tray = started(bus, control)

        reply = answer(
            tray, bus, call(CONTROL_PATH, DESKTOP, "SetState", "s", ("muted",))
        )

        assert reply.header.message_type == MessageType.method_return
        assert {"NewStatus", "NewIcon", "NewToolTip", "LayoutUpdated"} <= set(
            bus.signals()
        )
        status = answer(
            tray, bus, call(ITEM_PATH, PROPERTIES, "Get", "ss", (ITEM, "Status"))
        )
        assert status.body == (("s", "Active"),)

    def test_listening_hides_the_icon(self, control):
        """While listening the item is passive, so panels tuck it away."""
        bus = FakeBus()
        tray = started(bus, control)

        tray.handle(call(CONTROL_PATH, DESKTOP, "SetState", "s", ("listening",)))
        status = answer(
            tray, bus, call(ITEM_PATH, PROPERTIES, "Get", "ss", (ITEM, "Status"))
        )

        assert status.body == (("s", "Passive"),)

    def test_repeated_state_sends_no_signals(self, control):
        """The daemon re-asserts "muted" every few seconds; panels see it once."""
        bus = FakeBus()
        tray = started(bus, control)
        tray.handle(call(CONTROL_PATH, DESKTOP, "SetState", "s", ("muted",)))
        bus.sent.clear()

        tray.handle(call(CONTROL_PATH, DESKTOP, "SetState", "s", ("muted",)))

        assert bus.signals() == []

    @pytest.mark.parametrize("panel", ["no host", "hung", None])
    def test_asleep_fails_without_a_panel(self, control, panel):
        """No panel to wake EasySpeak from means the daemon must stay awake."""
        bus = FakeBus(panel=panel)
        tray = started(bus, control)

        reply = answer(
            tray, bus, call(CONTROL_PATH, DESKTOP, "SetState", "s", ("muted",))
        )

        assert reply.header.message_type == MessageType.error

    def test_asleep_fails_when_the_panel_stops_answering(self, control):
        """A panel that hangs after registering can't be trusted to wake us up."""
        bus = FakeBus()
        tray = started(bus, control)
        bus.panel = "hung"

        reply = answer(
            tray, bus, call(CONTROL_PATH, DESKTOP, "SetState", "s", ("muted",))
        )

        assert reply.header.message_type == MessageType.error

    def test_registers_again_when_the_panel_restarts(self, control):
        """A panel that comes (back) later picks the icon up."""
        bus = FakeBus(panel=None)
        tray = started(bus, control)
        bus.panel = "shown"
        owner_changed = new_signal(
            DBusAddress("/org/freedesktop/DBus", interface="org.freedesktop.DBus"),
            "NameOwnerChanged",
            "sss",
            (WATCHER_NAME, "", ":1.42"),
        )

        tray.handle(owner_changed)
        reply = answer(
            tray, bus, call(CONTROL_PATH, DESKTOP, "SetState", "s", ("muted",))
        )

        assert reply.header.message_type == MessageType.method_return


class TestClicks:
    """Clicks on the icon and its menu reach the daemon via the control file."""

    def test_click_on_icon_toggles(self, control):
        """Clicking the icon of a sleeping EasySpeak wakes it up."""
        bus = FakeBus()
        tray = started(bus, control)
        tray.handle(call(CONTROL_PATH, DESKTOP, "SetState", "s", ("muted",)))

        tray.handle(call(ITEM_PATH, ITEM, "Activate", "ii", (0, 0)))

        assert control.read_text() == "unmute"

    def test_menu_click_writes_its_command(self, control):
        """Choosing "Help" in the menu asks the daemon to open the docs."""
        bus = FakeBus()
        tray = started(bus, control)

        tray.handle(
            call(MENU_PATH, MENU, "Event", "isvu", (3, "clicked", ("s", ""), 0))
        )

        assert control.read_text() == "help"

    def test_hovering_a_menu_entry_does_nothing(self, control):
        """Only clicks count; panels also report hovering."""
        bus = FakeBus()
        tray = started(bus, control)

        tray.handle(
            call(MENU_PATH, MENU, "Event", "isvu", (3, "hovered", ("s", ""), 0))
        )

        assert not control.exists()

    def test_event_group_handles_each_event(self, control):
        """Batched menu events are acted on like single ones."""
        bus = FakeBus()
        tray = started(bus, control)

        tray.handle(
            call(
                MENU_PATH,
                MENU,
                "EventGroup",
                "a(isvu)",
                ([(6, "clicked", ("s", ""), 0)],),
            )
        )

        assert control.read_text() == "quit"

    @pytest.mark.parametrize("method", ["ContextMenu", "SecondaryActivate"])
    def test_other_clicks_are_acknowledged(self, control, method):
        """Right and middle clicks need no action, but must get an answer."""
        bus = FakeBus()
        tray = started(bus, control)

        reply = answer(tray, bus, call(ITEM_PATH, ITEM, method, "ii", (0, 0)))

        assert reply.header.message_type == MessageType.method_return
        assert not control.exists()


class TestMenu:
    """The menu panels draw from the dbusmenu calls."""

    def test_layout_lists_every_entry(self, control):
        """The layout holds the root and all seven entries, labels following state."""
        bus = FakeBus()
        tray = started(bus, control)
        tray.handle(call(CONTROL_PATH, DESKTOP, "SetState", "s", ("muted",)))

        reply = answer(
            tray, bus, call(MENU_PATH, MENU, "GetLayout", "iias", (0, -1, []))
        )

        _revision, (root_id, _props, children) = reply.body
        assert root_id == 0
        labels = [child[1][1].get("label") for child in children]
        assert labels[0] == ("s", "Reactivate EasySpeak")
        assert len(children) == 7

    def test_start_at_login_is_a_checkmark(self, control, home):
        """ "Start at Login" shows whether EasySpeak starts at login."""
        entry = home / "xdg" / "autostart" / "easyspeak.desktop"
        entry.parent.mkdir(parents=True)
        entry.write_text("[Desktop Entry]\nName=EasySpeak\n")
        bus = FakeBus()
        tray = started(bus, control)

        reply = answer(
            tray, bus, call(MENU_PATH, MENU, "GetGroupProperties", "aias", ([7], []))
        )

        assert reply.body == (
            [
                (
                    7,
                    {
                        "label": ("s", "Start at Login"),
                        "toggle-type": ("s", "checkmark"),
                        "toggle-state": ("i", 1),
                    },
                )
            ],
        )

    def test_clicking_start_at_login_toggles_it(self, control, home):
        """A click turns starting at login off and back on, and the menu follows."""
        system = home / "xdg" / "autostart" / "easyspeak.desktop"
        system.parent.mkdir(parents=True)
        system.write_text("[Desktop Entry]\nName=EasySpeak\n")
        user = home / "home" / ".config" / "autostart" / "easyspeak.desktop"
        bus = FakeBus()
        tray = started(bus, control)
        click = call(MENU_PATH, MENU, "Event", "isvu", (7, "clicked", ("s", ""), 0))

        tray.handle(click)

        assert "Hidden=true" in user.read_text()
        assert "LayoutUpdated" in [
            m.header.fields.get(HeaderFields.member) for m in bus.sent
        ]
        assert not control.exists()  # the helper switches it; the daemon isn't asked

        tray.handle(click)

        assert "Hidden=false" in user.read_text()

    def test_start_at_login_that_cant_be_changed_is_logged(
        self, control, monkeypatch, readlog
    ):
        """A failure to write the autostart entry is logged, and the menu stays."""

        def read_only(_enabled):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr("easyspeak.core.autostart.set_enabled", read_only)
        bus = FakeBus()
        tray = started(bus, control)
        bus.sent.clear()

        tray.handle(
            call(MENU_PATH, MENU, "Event", "isvu", (7, "clicked", ("s", ""), 0))
        )

        assert "Couldn't change starting at login" in readlog().err
        assert "LayoutUpdated" not in [
            m.header.fields.get(HeaderFields.member) for m in bus.sent
        ]

    def test_group_properties_of_some_entries(self, control):
        """Asking for given ids returns just those entries."""
        bus = FakeBus()
        tray = started(bus, control)

        reply = answer(
            tray, bus, call(MENU_PATH, MENU, "GetGroupProperties", "aias", ([6], []))
        )

        assert reply.body == ([(6, {"label": ("s", "Quit EasySpeak")})],)

    def test_single_property(self, control):
        """A single entry's label can be read on its own."""
        bus = FakeBus()
        tray = started(bus, control)

        reply = answer(
            tray, bus, call(MENU_PATH, MENU, "GetProperty", "is", (3, "label"))
        )

        assert reply.body == (("s", "Help"),)

    @pytest.mark.parametrize(
        ("method", "signature", "body", "expected"),
        [
            ("AboutToShow", "i", (0,), (False,)),
            ("AboutToShowGroup", "ai", ([0],), ([], [])),
        ],
    )
    def test_menu_never_needs_refreshing(
        self, control, method, signature, body, expected
    ):
        """The menu is always up to date, so panels needn't fetch it again."""
        bus = FakeBus()
        tray = started(bus, control)

        assert (
            answer(tray, bus, call(MENU_PATH, MENU, method, signature, body)).body
            == expected
        )

    def test_menu_properties(self, control):
        """Panels check the dbusmenu version they talk to."""
        bus = FakeBus()
        tray = started(bus, control)

        reply = answer(tray, bus, call(MENU_PATH, PROPERTIES, "GetAll", "s", (MENU,)))

        assert reply.body[0]["Version"] == ("u", 3)


class TestProtocol:
    """Odd or unknown requests get proper D-Bus answers."""

    def test_unknown_method_is_an_error(self, control):
        bus = FakeBus()
        tray = started(bus, control)

        reply = answer(tray, bus, call(ITEM_PATH, ITEM, "Explode"))

        assert reply.header.fields[HeaderFields.error_name].endswith("UnknownMethod")

    def test_unknown_property_is_an_error(self, control):
        bus = FakeBus()
        tray = started(bus, control)

        reply = answer(
            tray, bus, call(ITEM_PATH, PROPERTIES, "Get", "ss", (ITEM, "Nope"))
        )

        assert reply.header.fields[HeaderFields.error_name].endswith("UnknownProperty")

    def test_foreign_interface_has_no_properties(self, control):
        bus = FakeBus()
        tray = started(bus, control)

        reply = answer(tray, bus, call(ITEM_PATH, PROPERTIES, "GetAll", "s", ("a.b",)))

        assert reply.body == ({},)

    def test_introspection_describes_the_interfaces(self, control):
        bus = FakeBus()
        tray = started(bus, control)

        reply = answer(
            tray,
            bus,
            call(ITEM_PATH, "org.freedesktop.DBus.Introspectable", "Introspect"),
        )

        assert ITEM in reply.body[0]

    def test_interfaces_follow_the_dbus_format(self):
        """The interfaces match the DTD of the D-Bus introspection format."""
        dtd = etree.DTD(Path(__file__).with_name("dbus-introspect.dtd"))

        assert dtd.validate(etree.fromstring(INTERFACES)), dtd.error_log

    def test_interfaces_use_valid_types(self):
        """Each declared type is exactly one complete D-Bus type."""
        for element in etree.fromstring(INTERFACES).iter():
            if "type" in element.attrib:
                signature = list(element.attrib["type"])
                parse_signature(signature)
                assert signature == [], element.attrib

    def test_replies_are_ignored(self, control):
        """Stray replies to our own calls are not mistaken for requests."""
        bus = FakeBus()
        tray = started(bus, control)

        tray.handle(new_method_return(call(ITEM_PATH, ITEM, "Activate", "ii", (0, 0))))

        assert bus.sent == []

    def test_next_message_prefers_the_backlog(self, control):
        """Calls that came in while the tray waited on the panel are kept."""
        bus = FakeBus()
        tray = StatusNotifier(bus, control)
        early = call(ITEM_PATH, ITEM, "Activate", "ii", (0, 0))
        late = call(ITEM_PATH, ITEM, "ContextMenu", "ii", (0, 0))
        tray._backlog.append(early)
        bus.incoming.append(late)

        assert tray.next_message(0) is early
        assert tray.next_message(0) is late
        assert tray.next_message(0) is None


class TestMenuLogic:
    """Plain menu helpers."""

    def test_toggle_entry_follows_state(self):
        assert menu_items("listening")[0][1]["label"] == "Deactivate EasySpeak"
        assert menu_command(1, "listening") == "mute"

    def test_start_at_login_follows_the_setting(self):
        """The checkmark is ticked exactly when EasySpeak starts at login."""
        ticked = dict(menu_items("listening", starts_at_login=True))[7]
        unticked = dict(menu_items("listening"))[7]
        assert (ticked["toggle-state"], unticked["toggle-state"]) == (1, 0)

    def test_separators_send_nothing(self):
        assert menu_command(2, "muted") is None
