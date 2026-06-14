"""Tests for the hold-to-dictate keyboard listener (core.hotkey)."""

import logging
import sys
import types
from unittest.mock import MagicMock, Mock, patch

import pytest

# Mirror the other core tests: stub heavy deps so importing the package stays
# light. core.hotkey itself imports evdev only lazily, so it needs no stub.
sys.modules["pyaudio"] = MagicMock()
sys.modules["openwakeword"] = MagicMock()
sys.modules["openwakeword.model"] = MagicMock()
sys.modules["faster_whisper"] = MagicMock()

from easyspeak.core.hotkey import HotkeyListener, parse_combo  # noqa: E402

# evdev key codes used by the fakes below (the real values).
LEFTCTRL, RIGHTCTRL = 29, 97
LEFTSHIFT, RIGHTSHIFT = 42, 54
KEY_A = 30
ALIASED = 100  # a code whose name is a list, to exercise the alias branch


def _event(type_, code, value):
    return types.SimpleNamespace(type=type_, code=code, value=value)


class _FakeDevice:
    """Stand-in for an evdev InputDevice."""

    def __init__(self, fd=1, caps=(1,), events=(), read_error=False):
        self.fd = fd
        self._caps = caps
        self._events = list(events)
        self._read_error = read_error
        self.closed = False

    def capabilities(self):
        return {code: [] for code in self._caps}

    def read(self):
        if self._read_error:
            raise OSError("device gone")
        return list(self._events)

    def close(self):
        self.closed = True


@pytest.fixture
def fake_evdev(monkeypatch):
    """Inject a minimal fake ``evdev`` module for the I/O-touching code paths."""
    module = types.ModuleType("evdev")
    module.ecodes = types.SimpleNamespace(
        EV_KEY=1,
        KEY={
            LEFTCTRL: "KEY_LEFTCTRL",
            RIGHTCTRL: "KEY_RIGHTCTRL",
            LEFTSHIFT: "KEY_LEFTSHIFT",
            RIGHTSHIFT: "KEY_RIGHTSHIFT",
            KEY_A: "KEY_A",
            ALIASED: ["KEY_ALIASED", "KEY_OTHER"],
        },
    )
    module.list_devices = list
    module.InputDevice = lambda path: _FakeDevice()
    monkeypatch.setitem(sys.modules, "evdev", module)
    return module


class TestParseCombo:
    """Tests for translating a combo string into groups of accepted keys."""

    def test_ctrl_shift_accepts_left_or_right(self):
        groups = parse_combo("ctrl+shift")

        assert groups == (
            frozenset({"KEY_LEFTCTRL", "KEY_RIGHTCTRL"}),
            frozenset({"KEY_LEFTSHIFT", "KEY_RIGHTSHIFT"}),
        )

    def test_unknown_name_becomes_literal_evdev_key(self):
        """A name that isn't an alias falls through as a single KEY_ literal."""
        assert parse_combo("rightctrl") == (frozenset({"KEY_RIGHTCTRL"}),)

    def test_already_prefixed_name_is_kept(self):
        assert parse_combo("KEY_F13") == (frozenset({"KEY_F13"}),)

    def test_blank_parts_are_ignored(self):
        assert parse_combo("ctrl++") == (frozenset({"KEY_LEFTCTRL", "KEY_RIGHTCTRL"}),)

    def test_empty_spec_is_empty(self):
        assert parse_combo("") == ()


class TestState:
    """Tests for the held/activation state machine (no evdev needed)."""

    def test_full_combo_arms_activation_once(self):
        h = HotkeyListener("ctrl+shift")

        h._process("KEY_LEFTCTRL", 1)
        assert h.is_held() is False
        assert h.take_activation() is False

        h._process("KEY_LEFTSHIFT", 1)
        assert h.is_held() is True
        assert h.take_activation() is True
        # The edge is consumed; a second poll without a new press is False.
        assert h.take_activation() is False

    def test_release_ends_held(self):
        h = HotkeyListener("ctrl+shift")
        h._process("KEY_LEFTCTRL", 1)
        h._process("KEY_LEFTSHIFT", 1)

        h._process("KEY_LEFTCTRL", 0)

        assert h.is_held() is False

    def test_right_hand_variants_satisfy_the_combo(self):
        h = HotkeyListener("ctrl+shift")

        h._process("KEY_RIGHTCTRL", 1)
        h._process("KEY_RIGHTSHIFT", 1)

        assert h.is_held() is True

    def test_autorepeat_counts_as_pressed(self):
        h = HotkeyListener("ctrl+shift")

        h._process("KEY_LEFTCTRL", 1)
        h._process("KEY_LEFTSHIFT", 2)  # value 2 == key repeat

        assert h.is_held() is True

    def test_keys_outside_the_combo_are_ignored(self):
        h = HotkeyListener("ctrl+shift")

        h._process("KEY_A", 1)

        assert h.is_held() is False
        assert h.take_activation() is False

    def test_releasing_already_up_key_is_a_noop(self):
        h = HotkeyListener("ctrl+shift")

        h._process("KEY_LEFTCTRL", 0)  # never pressed

        assert h.is_held() is False


class TestStart:
    """Tests for start()'s gating and thread spawn."""

    def test_disabled_listener_does_nothing(self, caplog):
        h = HotkeyListener("ctrl+shift", enabled=False)

        with patch.object(h, "_grab_devices") as grab:
            h.start()

        grab.assert_not_called()
        assert h._thread is None

    def test_empty_combo_disables_the_feature(self):
        h = HotkeyListener("", enabled=True)

        with patch.object(h, "_grab_devices") as grab:
            h.start()

        grab.assert_not_called()

    def test_no_devices_starts_no_thread(self):
        h = HotkeyListener("ctrl+shift")

        with patch.object(h, "_grab_devices", return_value=[]):
            h.start()

        assert h._thread is None

    def test_with_devices_spawns_a_daemon_thread(self):
        h = HotkeyListener("ctrl+shift")
        device = _FakeDevice()

        with (
            patch.object(h, "_grab_devices", return_value=[device]),
            patch("easyspeak.core.hotkey.threading.Thread") as thread_cls,
        ):
            h.start()

        thread_cls.assert_called_once()
        assert thread_cls.call_args.kwargs["target"] == h._run
        assert thread_cls.call_args.kwargs["daemon"] is True
        thread_cls.return_value.start.assert_called_once()


class TestStop:
    """Tests for releasing devices on shutdown."""

    def test_stop_closes_devices_and_sets_event(self):
        h = HotkeyListener("ctrl+shift")
        device = _FakeDevice()
        h._devices = [device]

        h.stop()

        assert h._stop.is_set()
        assert device.closed is True
        assert h._devices == []

    def test_stop_swallows_close_errors(self):
        h = HotkeyListener("ctrl+shift")
        device = Mock()
        device.close.side_effect = OSError("already gone")
        h._devices = [device]

        h.stop()  # must not raise

        assert h._devices == []


class TestGrabDevices:
    """Tests for opening keyboard devices (with a faked evdev)."""

    def test_missing_evdev_is_reported_and_inert(self, monkeypatch, caplog):
        # A None entry in sys.modules makes `import evdev` raise ImportError.
        monkeypatch.setitem(sys.modules, "evdev", None)

        h = HotkeyListener("ctrl+shift")
        with caplog.at_level(logging.INFO):
            assert h._grab_devices() == []
        assert "python-evdev not installed" in caplog.text

    def test_keeps_only_readable_keyboards(self, fake_evdev):
        keyboard = _FakeDevice(fd=3, caps=(fake_evdev.ecodes.EV_KEY,))
        mouse = _FakeDevice(fd=4, caps=(2,))  # no EV_KEY -> filtered out

        def open_device(path):
            if path == "/dev/input/event2":
                raise OSError("permission denied")  # skipped
            return {"/dev/input/event0": keyboard, "/dev/input/event1": mouse}[path]

        fake_evdev.list_devices = lambda: [
            "/dev/input/event0",
            "/dev/input/event1",
            "/dev/input/event2",
        ]
        fake_evdev.InputDevice = open_device

        h = HotkeyListener("ctrl+shift")
        assert h._grab_devices() == [keyboard]

    def test_no_keyboard_warns_with_input_group_hint(self, fake_evdev, caplog):
        fake_evdev.list_devices = list

        h = HotkeyListener("ctrl+shift")
        assert h._grab_devices() == []
        assert "input" in caplog.text


class TestRun:
    """Tests for the select/read loop feeding events into the state machine."""

    def test_processes_events_then_honours_stop(self, fake_evdev, monkeypatch):
        h = HotkeyListener("ctrl+shift")
        device = _FakeDevice(
            fd=7,
            events=[
                _event(fake_evdev.ecodes.EV_KEY, LEFTCTRL, 1),
                _event(fake_evdev.ecodes.EV_KEY, LEFTSHIFT, 1),
            ],
        )
        h._devices = [device]

        calls = {"n": 0}

        def fake_select(rlist, _w, _x, _timeout):
            calls["n"] += 1
            if calls["n"] == 1:
                return ([device.fd], [], [])
            h._stop.set()
            return ([], [], [])

        monkeypatch.setattr("select.select", fake_select)

        h._run()

        assert h.is_held() is True

    def test_drain_ignores_read_errors(self, fake_evdev):
        h = HotkeyListener("ctrl+shift")
        device = _FakeDevice(fd=7, read_error=True)

        h._drain(device)  # must not raise

        assert h.is_held() is False

    def test_event_keyname_skips_non_key_events(self, fake_evdev):
        h = HotkeyListener("ctrl+shift")

        assert h._event_keyname(_event(99, LEFTCTRL, 1)) is None

    def test_event_keyname_resolves_aliased_codes(self, fake_evdev):
        h = HotkeyListener("ctrl+shift")

        name = h._event_keyname(_event(fake_evdev.ecodes.EV_KEY, ALIASED, 1))

        assert name == "KEY_ALIASED"
