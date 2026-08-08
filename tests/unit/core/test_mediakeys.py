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


def test_tap_chord_presses_together_and_releases_in_reverse():
    """Ctrl+V is one chord, not two unrelated keypresses.

    Keys go down in order and come up backwards, which is what an application
    reads as a modifier being held while another key is struck.
    """
    conn = Mock()
    conn.send_and_get_reply = Mock(return_value=Mock(body=("/session/1",)))

    with patch("easyspeak.core.mediakeys.open_dbus_connection", return_value=conn):
        mediakeys.tap_chord([29, 47])

    keys = [
        call.args[0].body
        for call in conn.send_and_get_reply.call_args_list
        if call.args[0].header.fields.get(3) == "NotifyKeyboardKeycode"
    ]
    assert keys == [(29, True), (47, True), (47, False), (29, False)]


def test_tap_key_is_a_single_key_chord():
    """The volume-key path still works, now expressed through tap_chord."""
    with patch("easyspeak.core.mediakeys.tap_chord") as mock_chord:
        mediakeys.tap_key(115)

    assert mock_chord.call_args.args[0] == [115]


def test_parse_key_request_needs_a_key_after_press():
    """A bare "press" with no key name behind it is not a keystroke command."""
    assert mediakeys.parse_key_request(["press"], set()) is None


def test_parse_key_request_rejects_an_unrecognised_count():
    """A trailing word that is neither a digit nor a number word is refused."""
    assert mediakeys.parse_key_request(["press", "enter", "banana"], set()) is None


@patch("easyspeak.core.mediakeys.tap_chord")
def test_press_key_taps_once_per_repeat(mock_chord):
    """Each repeat is one tap_chord, and a delivered chord reports True."""
    assert mediakeys.press_key(mediakeys.KEYS["enter"], repeats=3) is True
    assert mock_chord.call_count == 3


@patch("easyspeak.core.mediakeys.tap_chord", side_effect=RuntimeError("no portal"))
def test_press_key_reports_a_missing_remotedesktop(mock_chord, readlog):
    """Without GNOME's RemoteDesktop the keys can't be sent, so False, not a crash."""
    assert mediakeys.press_key(mediakeys.KEYS["enter"]) is False
    assert "RemoteDesktop" in readlog().err
