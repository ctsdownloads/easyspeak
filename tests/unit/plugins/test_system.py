"""Tests for the system plugin module."""

from unittest.mock import patch

import pytest
from easyspeak.plugins import system


def test_setup(mock_core):
    """When the system is set up, the core reference is stored globally."""
    system.setup(mock_core)

    assert system.core is mock_core


_STEP_UP = "org.gnome.SettingsDaemon.Power.Screen.StepUp"
_STEP_DOWN = "org.gnome.SettingsDaemon.Power.Screen.StepDown"

# (function, replayed keycode, command it falls back to when injection is unavailable).
MEDIA_KEYS = [
    (
        system.volume_up,
        system.KEY_VOLUME_UP,
        ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "10%+"],
    ),
    (
        system.volume_down,
        system.KEY_VOLUME_DOWN,
        ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "10%-"],
    ),
    (
        system.volume_mute,
        system.KEY_MUTE,
        ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"],
    ),
    (system.brightness_up, system.KEY_BRIGHTNESS_UP, [*system._POWER_SCREEN, _STEP_UP]),
    (
        system.brightness_down,
        system.KEY_BRIGHTNESS_DOWN,
        [*system._POWER_SCREEN, _STEP_DOWN],
    ),
]


@pytest.mark.parametrize(["func", "expected_keycode", "fallback"], MEDIA_KEYS)
def test_replays_media_key(func, expected_keycode, fallback, mock_core):
    """Volume and brightness controls replay the real key for GNOME's native feedback."""
    mock_core.tap_key.return_value = True

    func(mock_core)

    assert mock_core.tap_key.call_args.args[0] == expected_keycode


@pytest.mark.parametrize(["func", "expected_keycode", "fallback"], MEDIA_KEYS)
def test_no_fallback_when_key_injected(func, expected_keycode, fallback, mock_core):
    """When the key injection succeeds, no fallback command is issued."""
    mock_core.tap_key.return_value = True

    func(mock_core)

    assert not mock_core.host_run.called


@pytest.mark.parametrize(["func", "expected_keycode", "fallback"], MEDIA_KEYS)
def test_falls_back_when_key_unavailable(func, expected_keycode, fallback, mock_core):
    """When key injection is unavailable, fall back to the silent command."""
    mock_core.tap_key.return_value = False

    func(mock_core)

    assert mock_core.host_run.call_args.args[0] == fallback


@pytest.mark.parametrize(
    ["func", "expected_command"],
    [
        (
            system.dnd_on,
            [
                "gsettings",
                "set",
                "org.gnome.desktop.notifications",
                "show-banners",
                "false",
            ],
        ),
        (
            system.dnd_off,
            [
                "gsettings",
                "set",
                "org.gnome.desktop.notifications",
                "show-banners",
                "true",
            ],
        ),
    ],
)
def test_dnd_functions(func, expected_command, mock_core):
    """When do not disturb functions are called, host_run is called with correct commands."""
    func(mock_core)

    assert mock_core.host_run.call_args.args[0] == expected_command


@pytest.mark.parametrize(
    ["command", "expected_speech", "expected_func"],
    [
        ("volume up", "Volume up.", "volume_up"),
        ("volume louder", "Volume up.", "volume_up"),
        ("louder", "Volume up.", "volume_up"),
        ("make it louder", "Volume up.", "volume_up"),
        ("sound up", "Volume up.", "volume_up"),
        ("volume down", "Volume down.", "volume_down"),
        ("volume quieter", "Volume down.", "volume_down"),
        ("volume softer", "Volume down.", "volume_down"),
        ("more silent", "Volume down.", "volume_down"),
        ("make it quieter", "Volume down.", "volume_down"),
        ("sound down", "Volume down.", "volume_down"),
        ("volume mute", "Toggled mute.", "volume_mute"),
        ("volume unmute", "Toggled mute.", "volume_mute"),
        ("mute", "Toggled mute.", "volume_mute"),
    ],
)
@patch.object(system, "volume_up")
@patch.object(system, "volume_down")
@patch.object(system, "volume_mute")
def test_handle_volume_commands(
    mock_volume_mute,
    mock_volume_down,
    mock_volume_up,
    command,
    expected_speech,
    expected_func,
    mock_core,
):
    """When volume commands are handled, the correct function is called and speech is produced."""
    func_map = {
        "volume_up": mock_volume_up,
        "volume_down": mock_volume_down,
        "volume_mute": mock_volume_mute,
    }

    result = system.handle(command, mock_core)

    assert result is True
    assert mock_core.speak.call_args.args[0] == expected_speech
    assert func_map[expected_func].call_args.args[0] == mock_core


@pytest.mark.parametrize(
    ["command", "expected_speech", "expected_func"],
    [
        ("brightness up", "Brighter.", "brightness_up"),
        ("brightness brighter", "Brighter.", "brightness_up"),
        ("screen up", "Brighter.", "brightness_up"),
        ("brightness down", "Dimmer.", "brightness_down"),
        ("brightness dimmer", "Dimmer.", "brightness_down"),
        ("brightness darker", "Dimmer.", "brightness_down"),
        ("screen down", "Dimmer.", "brightness_down"),
    ],
)
@patch.object(system, "brightness_up")
@patch.object(system, "brightness_down")
def test_handle_brightness_commands(
    mock_brightness_down,
    mock_brightness_up,
    command,
    expected_speech,
    expected_func,
    mock_core,
):
    """When brightness commands are handled, the correct function is called and speech is produced."""
    func_map = {
        "brightness_up": mock_brightness_up,
        "brightness_down": mock_brightness_down,
    }

    result = system.handle(command, mock_core)

    assert result is True
    assert mock_core.speak.call_args.args[0] == expected_speech
    assert func_map[expected_func].call_args.args[0] == mock_core


@pytest.mark.parametrize(
    ["command", "expected_speech", "expected_func"],
    [
        ("do not disturb on", "Do not disturb on.", "dnd_on"),
        ("do not disturb enable", "Do not disturb on.", "dnd_on"),
        ("dnd on", "Do not disturb on.", "dnd_on"),
        ("do not disturb off", "Do not disturb off.", "dnd_off"),
        ("do not disturb disable", "Do not disturb off.", "dnd_off"),
        ("dnd off", "Do not disturb off.", "dnd_off"),
    ],
)
@patch.object(system, "dnd_on")
@patch.object(system, "dnd_off")
def test_handle_dnd_commands(
    mock_dnd_off, mock_dnd_on, command, expected_speech, expected_func, mock_core
):
    """When do not disturb commands are handled, the correct function is called and speech is produced."""
    func_map = {
        "dnd_on": mock_dnd_on,
        "dnd_off": mock_dnd_off,
    }

    result = system.handle(command, mock_core)

    assert result is True
    assert mock_core.speak.call_args.args[0] == expected_speech
    assert func_map[expected_func].call_args.args[0] == mock_core


@pytest.mark.parametrize("command", ["wait silently", "the softest blanket"])
def test_handle_volume_word_match_not_substring(command, mock_core):
    """Volume synonyms match whole words, so 'silently'/'softest' don't trigger it."""
    result = system.handle(command, mock_core)

    assert result is None
    assert not mock_core.speak.called


def test_handle_unrecognized_command(mock_core):
    """When an unrecognized command is handled, None is returned and no speech is produced."""
    result = system.handle("something else", mock_core)

    assert result is None
    assert not mock_core.speak.called
