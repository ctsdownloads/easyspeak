"""Tests for the connectivity plugin module."""

from unittest.mock import Mock, patch

import pytest
from easyspeak.plugins import connectivity


def test_setup(mock_core):
    """When the plugin is set up, the core reference is stored globally."""
    connectivity.setup(mock_core)

    assert connectivity.core is mock_core


@pytest.mark.parametrize(
    ["func", "on", "prop", "value"],
    [
        (connectivity.set_wifi, True, "WirelessEnabled", "<true>"),
        (connectivity.set_wifi, False, "WirelessEnabled", "<false>"),
        (connectivity.set_airplane_mode, True, "AirplaneMode", "<true>"),
        (connectivity.set_airplane_mode, False, "AirplaneMode", "<false>"),
        (connectivity.set_bluetooth, True, "BluetoothAirplaneMode", "<false>"),
        (connectivity.set_bluetooth, False, "BluetoothAirplaneMode", "<true>"),
    ],
)
def test_switches_set_the_right_property(func, on, prop, value, mock_core):
    """Each switch sets its own D-Bus property; Bluetooth on is its airplane mode off."""
    mock_core.host_run.return_value = Mock(returncode=0, stderr="")

    assert func(mock_core, on=on) is True
    assert mock_core.host_run.call_args.args[0][-2:] == [prop, value]


def test_wifi_goes_through_network_manager(mock_core):
    """Wi-Fi is NetworkManager's, on the system bus, so it works outside GNOME too."""
    mock_core.host_run.return_value = Mock(returncode=0, stderr="")

    connectivity.set_wifi(mock_core, on=True)

    command = mock_core.host_run.call_args.args[0]
    assert "--system" in command
    assert "org.freedesktop.NetworkManager" in command


def test_a_refused_switch_reports_failure(mock_core):
    """A non-zero exit, say no GNOME or no radio, is reported, not hidden."""
    mock_core.host_run.return_value = Mock(returncode=1, stderr="no such name\n")

    assert connectivity.set_bluetooth(mock_core, on=True) is False


@pytest.mark.parametrize(
    ["command", "setter", "on", "reply"],
    [
        ("wifi on", "set_wifi", True, "Wi-Fi on."),
        ("turn off wi-fi", "set_wifi", False, "Wi-Fi off."),
        ("wireless off", "set_wifi", False, "Wi-Fi off."),
        ("airplane mode on", "set_airplane_mode", True, "Airplane mode on."),
        ("flight mode off", "set_airplane_mode", False, "Airplane mode off."),
        ("bluetooth on", "set_bluetooth", True, "Bluetooth on."),
        ("turn bluetooth off", "set_bluetooth", False, "Bluetooth off."),
        ("disable bluetooth", "set_bluetooth", False, "Bluetooth off."),
    ],
)
def test_handle_switches_and_says_so(command, setter, on, reply, mock_core):
    """A command flips the named switch and says what it did."""
    with patch.object(connectivity, setter, return_value=True) as switch:
        result = connectivity.handle(command, mock_core)

    assert result is True
    assert switch.call_args.kwargs == {"on": on}
    assert mock_core.speak.call_args.args[0] == reply


@patch.object(connectivity, "set_wifi", return_value=False)
def test_handle_says_when_a_switch_fails(mock_set_wifi, mock_core):
    """A refused change is never announced as done."""
    result = connectivity.handle("wifi off", mock_core)

    assert result is True
    assert mock_core.speak.call_args.args[0] == "Sorry, I couldn't change that."


@pytest.mark.parametrize(
    "command",
    [
        "wifi",
        "bluetooth",
        "turn wifi on and bluetooth off",
        "turn it off",
        "something else",
        "the bluetoothy speaker on",
    ],
)
def test_handle_leaves_unclear_commands_alone(command, mock_core):
    """No switch, no direction, or both directions: nothing is touched."""
    assert connectivity.handle(command, mock_core) is None
    assert not mock_core.host_run.called
    assert not mock_core.speak.called
