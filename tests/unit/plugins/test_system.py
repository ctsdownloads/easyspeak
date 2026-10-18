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
def test_replays_media_key(func, expected_keycode, fallback, mock_core, monkeypatch):
    """Volume and brightness controls replay the real key for GNOME's native feedback."""
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    mock_core.tap_key.return_value = True

    func(mock_core)

    assert mock_core.tap_key.call_args.args[0] == expected_keycode


@pytest.mark.parametrize(["func", "expected_keycode", "fallback"], MEDIA_KEYS)
def test_no_fallback_when_key_injected(
    func, expected_keycode, fallback, mock_core, monkeypatch
):
    """On a media-key desktop, a successful injection issues no fallback."""
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    mock_core.tap_key.return_value = True

    func(mock_core)

    assert not mock_core.host_run.called


@pytest.mark.parametrize("desktop", [None, "sway", "Hyprland", "wlroots"])
@pytest.mark.parametrize(["func", "expected_keycode", "fallback"], MEDIA_KEYS)
def test_fallback_is_the_replay_without_global_media_keys(
    func, expected_keycode, fallback, mock_core, monkeypatch, desktop
):
    """On a desktop without global XF86Audio handling, the fallback IS the
    replay — injecting there hands the key to a compositor that may drop it
    silently (sway/Hyprland with no binding: no volume change, no OSD, no
    speech). The absence of a KDE env here is the point: the family check is
    substring-based on the XDG token, so the real desktops stay on the
    injection arm (test_no_fallback_when_key_injected pins that side)."""
    if desktop is None:
        monkeypatch.delenv("XDG_CURRENT_DESKTOP", raising=False)
    else:
        monkeypatch.setenv("XDG_CURRENT_DESKTOP", desktop)
    mock_core.tap_key.return_value = True  # even a working injection is not enough

    func(mock_core)

    assert mock_core.host_run.call_args.args[0] == fallback


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
    ["command", "expected_func"],
    [
        ("volume up", "volume_up"),
        ("volume louder", "volume_up"),
        ("louder", "volume_up"),
        ("make it louder", "volume_up"),
        ("sound up", "volume_up"),
        ("volume down", "volume_down"),
        ("volume quieter", "volume_down"),
        ("volume softer", "volume_down"),
        ("more silent", "volume_down"),
        ("make it quieter", "volume_down"),
        ("sound down", "volume_down"),
        ("volume mute", "volume_mute"),
        ("volume unmute", "volume_mute"),
        ("mute", "volume_mute"),
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
    expected_func,
    mock_core,
):
    """Volume commands call the right function and stay silent — GNOME's native
    OSD and chime acknowledge the change."""
    func_map = {
        "volume_up": mock_volume_up,
        "volume_down": mock_volume_down,
        "volume_mute": mock_volume_mute,
    }

    result = system.handle(command, mock_core)

    assert result is True
    assert not mock_core.speak.called
    assert func_map[expected_func].call_args.args[0] == mock_core


@pytest.mark.parametrize(
    ["command", "expected_func"],
    [
        ("very loud", "volume_max"),
        ("make it very loud", "volume_max"),
        ("very louder", "volume_max"),
        ("very silent", "volume_min"),
        ("very quiet", "volume_min"),
        ("very soft", "volume_min"),
    ],
)
@patch.object(system, "volume_max")
@patch.object(system, "volume_min")
def test_handle_extreme_volume_commands(
    mock_volume_min, mock_volume_max, command, expected_func, mock_core
):
    """ "very loud"/"very silent" jump straight to max/min volume, silently."""
    func_map = {"volume_max": mock_volume_max, "volume_min": mock_volume_min}

    result = system.handle(command, mock_core)

    assert result is True
    assert not mock_core.speak.called
    assert func_map[expected_func].call_args.args[0] == mock_core


def test_volume_max_sets_near_full_volume(mock_core):
    """volume_max sets the default sink to 85% directly (no media key for it)."""
    system.volume_max(mock_core)

    mock_core.host_run.assert_called_once_with(
        ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "85%"]
    )


def test_volume_min_sets_very_low_volume(mock_core):
    """volume_min drops the default sink to 15% — quiet but not muted."""
    system.volume_min(mock_core)

    mock_core.host_run.assert_called_once_with(
        ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "15%"]
    )


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


@pytest.mark.parametrize(
    ["command", "expected_func"],
    [
        # Silencing notifications IS do-not-disturb on, so the two vocabularies
        # run opposite ways and the direction word has to be read against the noun
        # the user actually spoke.
        ("turn off notifications", "dnd_on"),
        ("notifications off", "dnd_on"),
        ("turn notifications off", "dnd_on"),
        ("disable notifications", "dnd_on"),
        ("turn on notifications", "dnd_off"),
        ("notifications on", "dnd_off"),
        ("enable notifications", "dnd_off"),
    ],
)
@patch.object(system, "dnd_on")
@patch.object(system, "dnd_off")
def test_handle_dnd_direction_on_notifications(
    mock_dnd_off, mock_dnd_on, command, expected_func, mock_core
):
    """When 'notifications' is the noun then the direction is inverted.

    "notifications" also contains the letters "on", which the original substring
    test matched inside the trigger word itself.
    """
    func_map = {"dnd_on": mock_dnd_on, "dnd_off": mock_dnd_off}
    wrong = "dnd_off" if expected_func == "dnd_on" else "dnd_on"

    result = system.handle(command, mock_core)

    assert result is True
    assert func_map[expected_func].called
    assert not func_map[wrong].called


@pytest.mark.parametrize("command", ["notifications", "do not disturb", "dnd"])
def test_handle_dnd_without_a_direction_falls_through(command, mock_core):
    """When no direction is given then nothing is toggled."""
    assert system.handle(command, mock_core) is None


@pytest.mark.parametrize(
    "command",
    ["take a screenshot", "screenshots up", "shut down the upstairs light"],
)
def test_handle_ignores_substring_matches(command, mock_core):
    """When a word merely contains a trigger then no system command fires."""
    assert system.handle(command, mock_core) is None
