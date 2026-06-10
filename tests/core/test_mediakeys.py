"""Tests for the mediakeys module."""

from unittest.mock import Mock, patch

import pytest
from easyspeak.core import mediakeys


@patch("easyspeak.core.mediakeys.open_dbus_connection")
def test_tap_key_replays_press_and_release(mock_open):
    """tap_key drives one RemoteDesktop session, pressing then releasing the key."""
    conn = Mock()
    create_reply = Mock()
    create_reply.body = ["/org/gnome/Mutter/RemoteDesktop/Session/u0"]
    conn.send_and_get_reply.return_value = create_reply
    mock_open.return_value = conn

    with patch("easyspeak.core.mediakeys.new_method_call") as mock_call:
        mediakeys.tap_key(115)

    mock_open.assert_called_once_with(bus="SESSION")

    # CreateSession -> Start -> key press -> key release -> Stop, in order.
    methods = [call.args[1] for call in mock_call.call_args_list]
    assert methods == [
        "CreateSession",
        "Start",
        "NotifyKeyboardKeycode",
        "NotifyKeyboardKeycode",
        "Stop",
    ]

    # The two key events carry (keycode, pressed) with press before release.
    key_events = [
        call.args[3]
        for call in mock_call.call_args_list
        if call.args[1] == "NotifyKeyboardKeycode"
    ]
    assert key_events == [(115, True), (115, False)]

    conn.close.assert_called_once()


@patch("easyspeak.core.mediakeys.open_dbus_connection")
def test_tap_key_closes_connection_on_error(mock_open):
    """The connection is closed even when a D-Bus call fails."""
    conn = Mock()
    conn.send_and_get_reply.side_effect = RuntimeError("no RemoteDesktop")
    mock_open.return_value = conn

    with pytest.raises(RuntimeError):
        mediakeys.tap_key(115)

    conn.close.assert_called_once()
