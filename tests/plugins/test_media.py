"""Tests for the media plugin module."""

from unittest.mock import Mock, patch

import pytest
from easyspeak.plugins import media


def test_setup(mock_core):
    """When setup is called with a core object then it stores the reference."""
    media.setup(mock_core)

    assert media.core is mock_core


@pytest.mark.parametrize(
    ["stdout_content", "expected_players"],
    [
        (
            'string "org.mpris.MediaPlayer2.spotify"\n',
            ["org.mpris.MediaPlayer2.spotify"],
        ),
        (
            'string "org.mpris.MediaPlayer2.vlc"\nstring "org.mpris.MediaPlayer2.spotify"\n',
            ["org.mpris.MediaPlayer2.vlc", "org.mpris.MediaPlayer2.spotify"],
        ),
        (
            'string "org.freedesktop.DBus"\nstring "org.mpris.MediaPlayer2.rhythmbox"\n',
            ["org.mpris.MediaPlayer2.rhythmbox"],
        ),
        (
            'string "org.freedesktop.DBus"\nstring "some.other.service"\n',
            [],
        ),
        ("", []),
    ],
)
def test_get_media_players(stdout_content, expected_players, mock_core):
    """When get_media_players is called then it parses MPRIS players from dbus output."""
    mock_core.host_run.return_value = Mock(stdout=stdout_content)

    result = media.get_media_players(mock_core)

    assert result == expected_players
    assert mock_core.host_run.call_args.args[0] == [
        "dbus-send",
        "--session",
        "--dest=org.freedesktop.DBus",
        "--type=method_call",
        "--print-reply",
        "/org/freedesktop/DBus",
        "org.freedesktop.DBus.ListNames",
    ]


@pytest.mark.parametrize(
    ["action", "expected_method"],
    [
        ("play", "Play"),
        ("pause", "Pause"),
        ("next", "Next"),
        ("previous", "Previous"),
    ],
)
@patch.object(
    media,
    "get_media_players",
    return_value=["org.mpris.MediaPlayer2.spotify", "org.mpris.MediaPlayer2.vlc"],
)
def test_media_control_with_players(
    mock_get_players, action, expected_method, mock_core
):
    """When media_control is called with a valid action then it sends the command to all players."""
    result = media.media_control(action, mock_core)

    assert result is True
    assert mock_core.host_run.call_count == 2
    for call in mock_core.host_run.call_args_list:
        cmd_args = call.args[0]
        assert cmd_args[0] == "dbus-send"
        assert cmd_args[1] == "--session"
        assert cmd_args[2] == "--type=method_call"
        assert cmd_args[4] == "/org/mpris/MediaPlayer2"
        assert cmd_args[5] == f"org.mpris.MediaPlayer2.Player.{expected_method}"


@patch.object(media, "get_media_players", return_value=[])
def test_media_control_with_no_players(mock_get_players, mock_core):
    """When media_control is called with no players available then it returns False."""
    result = media.media_control("play", mock_core)

    assert result is False
    assert not mock_core.host_run.called


@patch.object(
    media, "get_media_players", return_value=["org.mpris.MediaPlayer2.spotify"]
)
def test_media_control_with_invalid_action(mock_get_players, mock_core):
    """When media_control is called with an invalid action then it returns False."""
    result = media.media_control("invalid", mock_core)

    assert result is False
    assert not mock_core.host_run.called


@pytest.mark.parametrize(
    ["command", "expected_action", "expected_speech"],
    [
        ("play", "play", "Playing."),
        ("play music", "play", "Playing."),
        ("playing now", "play", "Playing."),
    ],
)
@patch.object(media, "media_control", return_value=True)
def test_handle_play_commands(
    mock_media_control, command, expected_action, expected_speech, mock_core
):
    """When handle receives a play command then it calls media_control and speaks."""
    result = media.handle(command, mock_core)

    assert result is True
    assert mock_media_control.call_args.args == (expected_action, mock_core)
    assert mock_core.speak.call_args.args[0] == expected_speech


@pytest.mark.parametrize(
    ["command", "expected_action", "expected_speech"],
    [
        ("pause", "pause", "Paused."),
        ("pause music", "pause", "Paused."),
        ("pause the song", "pause", "Paused."),
    ],
)
@patch.object(media, "media_control", return_value=True)
def test_handle_pause_commands(
    mock_media_control, command, expected_action, expected_speech, mock_core
):
    """When handle receives a pause command then it calls media_control and speaks."""
    result = media.handle(command, mock_core)

    assert result is True
    assert mock_media_control.call_args.args == (expected_action, mock_core)
    assert mock_core.speak.call_args.args[0] == expected_speech


@pytest.mark.parametrize(
    ["command", "expected_action", "expected_speech"],
    [
        ("next", "next", "Next."),
        ("next track", "next", "Next."),
        ("skip", "next", "Next."),
        ("skip song", "next", "Next."),
    ],
)
@patch.object(media, "media_control", return_value=True)
def test_handle_next_commands(
    mock_media_control, command, expected_action, expected_speech, mock_core
):
    """When handle receives a next command then it calls media_control and speaks."""
    result = media.handle(command, mock_core)

    assert result is True
    assert mock_media_control.call_args.args == (expected_action, mock_core)
    assert mock_core.speak.call_args.args[0] == expected_speech


@pytest.mark.parametrize(
    ["command", "expected_action", "expected_speech"],
    [
        ("previous", "previous", "Previous."),
        ("previous track", "previous", "Previous."),
        ("back", "previous", "Previous."),
        ("go back", "previous", "Previous."),
    ],
)
@patch.object(media, "media_control", return_value=True)
def test_handle_previous_commands(
    mock_media_control, command, expected_action, expected_speech, mock_core
):
    """When handle receives a previous command then it calls media_control and speaks."""
    result = media.handle(command, mock_core)

    assert result is True
    assert mock_media_control.call_args.args == (expected_action, mock_core)
    assert mock_core.speak.call_args.args[0] == expected_speech


@patch.object(media, "media_control", return_value=True)
def test_handle_play_pause_disambiguation(mock_media_control, mock_core):
    """When handle receives a command with both play and pause then pause takes precedence."""
    result = media.handle("play pause", mock_core)

    assert result is True
    assert mock_media_control.call_args.args == ("pause", mock_core)
    assert mock_core.speak.call_args.args[0] == "Paused."


@patch.object(media, "media_control")
def test_handle_unrecognized_command(mock_media_control, mock_core):
    """When handle receives an unrecognized command then it returns None."""
    result = media.handle("unrelated command", mock_core)

    assert result is None
    assert not mock_media_control.called
    assert not mock_core.speak.called
