"""Pytest fixtures for core module tests."""

import sys
from unittest.mock import MagicMock, Mock

import pytest

# Stub the heavy native/model deps once for the whole core suite. conftest is
# imported before any test module, so importing easyspeak.core.* below needs no
# model or GPU. Assign directly (not setdefault) to override a real install too.
for _name in ("pyaudio", "pyopen_wakeword", "faster_whisper"):
    sys.modules[_name] = MagicMock()
# The config validates EASYSPEAK_LANGUAGE against faster-whisper's language codes.
sys.modules["faster_whisper.tokenizer"] = MagicMock(
    _LANGUAGE_CODES=("en", "de", "it", "fr", "es", "pt", "nl")
)


from easyspeak.core import main as main_module  # noqa: E402
from easyspeak.core import tray as tray_module  # noqa: E402

# Kept before the stub below replaces it, so the tests that exercise calibration
# itself can put the real method back.
REAL_CALIBRATE_SILENCE = main_module.EasySpeak.calibrate_silence


@pytest.fixture(autouse=True)
def _skip_silence_calibration(monkeypatch):
    """Don't sample the microphone at startup during tests.

    calibrate_silence() reads a second of audio when the daemon starts, which
    every test that drives run() would otherwise count as part of its own
    recording. Its own behaviour is covered directly in test_listen_modal.
    """
    monkeypatch.setattr(main_module.EasySpeak, "calibrate_silence", lambda _self: None)


@pytest.fixture(autouse=True)
def _silence_desktop_sounds(monkeypatch, tmp_path_factory):
    """Keep the suite from chiming through the speakers.

    `play_sound` spawns a real audio player whenever the sound file exists, so on
    any desktop with sound-theme-freedesktop installed the suite played the wake
    chime out loud while it ran. Pointing the sound paths at a file that isn't
    there makes it short-circuit before spawning anything. Tests that exercise the
    player itself pass their own path and patch `subprocess.run`, so they are
    unaffected.
    """
    missing = tmp_path_factory.mktemp("nosound") / "absent.oga"
    for module, name in (
        (main_module, "WAKE_SOUND"),
        (tray_module, "ERROR_SOUND"),
    ):
        monkeypatch.setattr(module, name, missing)


def create_mock_plugin(name="TestPlugin", **kwargs) -> Mock:
    """
    Factory function to create mock plugin objects.

    Args:
        name: Plugin name (default: "TestPlugin")
        **kwargs: Additional attributes to set on the plugin
            - commands: List of commands to set as COMMANDS attribute
            - handle_side_effect: Side effect for handle method
            - handle_return: Return value for handle method
            - Any other attributes will be set directly on the plugin
    """
    plugin = Mock()
    plugin.NAME = name

    if "commands" in kwargs:
        plugin.COMMANDS = kwargs.pop("commands")

    plugin.handle = (
        Mock(side_effect=kwargs.pop("handle_side_effect"))
        if "handle_side_effect" in kwargs
        else Mock(return_value=kwargs.pop("handle_return"))
        if "handle_return" in kwargs
        else Mock()
    )

    for key, val in kwargs.items():
        setattr(plugin, key, val)

    return plugin


@pytest.fixture
def mock_plugin():
    """Create a mock plugin with name 'TestPlugin' that handles commands."""
    return create_mock_plugin(handle_return=True)


@pytest.fixture
def mock_plugin_with_setup():
    """Create a mock plugin with name 'TestPlugin' that has a setup method."""
    return create_mock_plugin(setup=Mock())


@pytest.fixture
def mock_plugin_no_handle():
    """Create a mock plugin that doesn't handle commands (returns None)."""
    return create_mock_plugin(handle_return=None)


@pytest.fixture
def mock_plugin_exit():
    """Create a mock plugin that signals exit (returns False)."""
    return create_mock_plugin(handle_return=False)


@pytest.fixture
def mock_plugin_with_commands_12():
    """Create a mock plugin with COMMANDS attribute containing cmd1 and cmd2."""
    return create_mock_plugin(commands=["cmd1", "cmd2"], handle_return=True)


@pytest.fixture
def mock_plugin_with_commands_34():
    """Create a mock plugin with COMMANDS attribute containing cmd3 and cmd4."""
    return create_mock_plugin(commands=["cmd3", "cmd4"], handle_return=True)


@pytest.fixture
def mock_plugin_without_commands():
    """Create a mock plugin without COMMANDS attribute."""
    return Mock(spec=[])


@pytest.fixture
def mock_multiple_plugins():
    """Create multiple mock plugins for testing plugin routing."""
    return [
        create_mock_plugin(name="Plugin1", handle_return=None),
        create_mock_plugin(name="Plugin2", handle_return=True),
    ]


@pytest.fixture
def mock_plugin_with_error():
    """Create a mock plugin that raises an exception."""
    return create_mock_plugin(handle_side_effect=ValueError("Test error"))
