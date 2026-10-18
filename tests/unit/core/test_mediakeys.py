"""Tests for the mediakeys module.

The RemoteDesktop choreography tests target `RemoteDesktopBackend` directly:
the module-level `tap_key`/`tap_chord` dispatch through the sticky gate
(covered by `test_injection_gate.py`), and going through it here would resolve
a backend from the real session bus.
"""

from unittest.mock import MagicMock, Mock, patch

import pytest
from easyspeak.core import mediakeys
from jeepney import new_error, new_method_call


def _session_conn(reply=None, side_effect=None):
    """A MagicMock honoring the connection contract the backend binds with.

    The backend takes the connection through ``with``, and jeepney's
    ``__enter__`` yields the connection itself — a bare MagicMock would hand
    the body a fresh auto-configured child, so ``__enter__`` is pinned here.
    """
    conn = MagicMock()
    conn.__enter__.return_value = conn
    if reply is not None:
        conn.send_and_get_reply.return_value = reply
    if side_effect is not None:
        conn.send_and_get_reply.side_effect = side_effect
    return conn


def _connected_backend():
    """A RemoteDesktopBackend whose every chord rides one scripted connection."""
    conn = _session_conn(reply=Mock(body=("/session/1",)))
    return mediakeys.RemoteDesktopBackend(conn_factory=lambda: conn), conn


def test_tap_key_replays_press_and_release():
    """One RemoteDesktop session per key: CreateSession, Start, press, release, Stop."""
    create_reply = Mock()
    create_reply.body = ["/org/gnome/Mutter/RemoteDesktop/Session/u0"]
    conn = _session_conn(reply=create_reply)
    backend = mediakeys.RemoteDesktopBackend(conn_factory=lambda: conn)

    with patch("easyspeak.core.mediakeys.new_method_call") as mock_call:
        backend.tap_key(115)

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

    # The connection's lifetime is the with-scope: exiting it is what closes
    # the connection (jeepney's __exit__ closes), success or error.
    conn.__exit__.assert_called_once()
    # The disclosed bounded-wait delta: no D-Bus send waits indefinitely.
    for call in conn.send_and_get_reply.call_args_list:
        assert call.kwargs["timeout"] == mediakeys.GDBUS_TIMEOUT


def test_tap_key_closes_connection_on_error():
    """The connection is closed even when a D-Bus call fails."""
    conn = _session_conn(side_effect=RuntimeError("no RemoteDesktop"))
    backend = mediakeys.RemoteDesktopBackend(conn_factory=lambda: conn)

    with pytest.raises(RuntimeError):
        backend.tap_key(115)

    conn.__exit__.assert_called_once()  # the with-scope closed it on the way out


def test_tap_chord_raises_when_remotedesktop_is_missing():
    """On a desktop without Mutter, e.g. KDE Plasma, D-Bus answers with an error.

    That error is reported as such, not mistaken for a session path.
    """
    conn = _session_conn(
        reply=new_error(
            new_method_call(mediakeys._REMOTE_DESKTOP, "CreateSession"),
            "org.freedesktop.DBus.Error.ServiceUnknown",
            "s",
            ("The name is not activatable",),
        )
    )
    backend = mediakeys.RemoteDesktopBackend(conn_factory=lambda: conn)

    with pytest.raises(mediakeys.InjectionUnavailableError, match="not activatable"):
        backend.tap_chord([29, 47])

    conn.__exit__.assert_called_once()  # the with-scope closed it on the way out


def test_tap_chord_presses_together_and_releases_in_reverse():
    """Ctrl+V is one chord, not two unrelated keypresses.

    Keys go down in order and come up backwards, which is what an application
    reads as a modifier being held while another key is struck.
    """
    backend, conn = _connected_backend()
    backend.tap_chord([29, 47])

    keys = [
        call.args[0].body
        for call in conn.send_and_get_reply.call_args_list
        if call.args[0].header.fields.get(3) == "NotifyKeyboardKeycode"
    ]
    assert keys == [(29, True), (47, True), (47, False), (29, False)]


def test_tap_key_is_a_single_key_chord():
    """The volume-key path still works, now expressed through tap_chord."""
    backend = mediakeys.RemoteDesktopBackend()
    with patch.object(backend, "tap_chord") as mock_chord:
        backend.tap_key(115)

    assert mock_chord.call_args.args[0] == [115]


def test_tap_key_repeats_stay_per_repeat_sessions():
    """Repeats are one RemoteDesktop session each, as today's press_key loop ran."""

    def factory():
        return _session_conn(reply=Mock(body=("/session/1",)))

    conns = [factory(), factory(), factory()]
    handed_out = iter(conns)
    backend = mediakeys.RemoteDesktopBackend(conn_factory=lambda: next(handed_out))

    backend.tap_key(mediakeys.KEYS["enter"], repeats=3)

    assert len(conns) == 3  # one connection (and session) per repeat
    for conn in conns:
        # CreateSession, Start, press, release, Stop.
        assert conn.send_and_get_reply.call_count == 5


def test_parse_key_request_needs_a_key_after_press():
    """A bare "press" with no key name behind it is not a keystroke command."""
    assert mediakeys.parse_key_request(["press"], set()) is None


def test_parse_key_request_rejects_an_unrecognised_count():
    """A trailing word that is neither a digit nor a number word is refused."""
    assert mediakeys.parse_key_request(["press", "enter", "banana"], set()) is None


@patch("easyspeak.core.mediakeys.select_backend")
def test_press_key_hands_the_whole_repeat_run_to_the_backend(mock_select):
    """press_key delegates one call with the repeats; True when delivered."""
    assert mediakeys.press_key(mediakeys.KEYS["enter"], repeats=3) is True
    mock_select.return_value.tap_key.assert_called_once_with(
        mediakeys.KEYS["enter"], repeats=3
    )


@patch("easyspeak.core.mediakeys.select_backend")
def test_press_key_reports_an_unavailable_backend(mock_select, readlog):
    """With no backend answering, the keys can't be sent: False, not a crash."""
    mock_select.return_value.tap_key.side_effect = mediakeys.InjectionUnavailableError(
        "The name is not activatable"
    )
    assert mediakeys.press_key(mediakeys.KEYS["enter"]) is False
    assert "could not be injected" in readlog().err


@patch("easyspeak.core.mediakeys.select_backend")
def test_press_key_survives_an_oserror_from_the_backend(mock_select, readlog):
    """A missing injection binary is a False, not a crash: press_key's ladder
    catches RuntimeError (the InjectionUnavailableError family) and OSError."""
    mock_select.return_value.tap_key.side_effect = FileNotFoundError("ydotool")
    assert mediakeys.press_key(mediakeys.KEYS["enter"]) is False
    assert "could not be injected" in readlog().err


@patch("easyspeak.core.mediakeys.select_backend")
def test_press_key_survives_an_unspellable_code(mock_select, monkeypatch, readlog):
    """A code the 0.1.8 name tables cannot spell raises ValueError from the
    REAL argv builder on the uinput path; the ladder catches it so dictation
    speaks its proper refusal (and the system plugin falls back) instead of the
    error escaping to the dispatcher's generic apology. 113 (mute) spells no
    legacy combo name — the media keys are absent from the client's own name
    tables (see ydotool.KEY_LEGACY_NAMES), so pinning the legacy dialect and
    letting key_argv run is the honest premise: if a name for 113 ever lands in
    the table, this test says so instead of staying green through a mock."""
    monkeypatch.setattr(mediakeys.yd, "_dialect", mediakeys.yd.YDTOOL_DIALECT_LEGACY)
    mock_select.return_value = mediakeys.UinputBackend(
        runner=lambda args, timeout: "ran"
    )
    assert mediakeys.press_key(113) is False
    assert "could not be injected" in readlog().err


def test_remote_desktop_repeats_below_one_is_a_noop():
    """The GNOME twin of the uinput guard: spoken "backspace 0" must not open
    a RemoteDesktop session, let alone delete a character nobody asked for —
    the two backends no-op consistently, so the silent-deletion hazard
    _check_batch documents has no arm that slips through."""
    handed = []
    backend = mediakeys.RemoteDesktopBackend(conn_factory=handed.append)
    assert backend.tap_key(14, repeats=0) is None
    assert handed == []
