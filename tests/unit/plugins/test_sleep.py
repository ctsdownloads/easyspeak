"""Tests for the sleep plugin module."""

import pytest
from easyspeak.plugins import sleep


@pytest.mark.parametrize(
    "command",
    [
        "go to sleep",
        "go to sleep jarvis",
        "goto sleep",
        "GO TO SLEEP",
    ],
)
def test_handle_sleep_commands(mock_core, command):
    """When handle receives a sleep phrase then it deactivates and returns True."""
    result = sleep.handle(command, mock_core)

    assert result is True
    mock_core.deactivate.assert_called_once()
    # Speaking the deactivation here also ends the command session promptly; the
    # tray stays silent on this voice path so the phrase isn't repeated.
    mock_core.speak.assert_called_once_with("Voice control turned off.")


@pytest.mark.parametrize(
    "command",
    [
        "open firefox",
        "volume up",
        "sleep timer",  # unrelated use of 'sleep'
        "what can you do",
    ],
)
def test_handle_ignores_other_commands(mock_core, command):
    """When handle receives an unrelated command then it does nothing."""
    result = sleep.handle(command, mock_core)

    assert result is None
    assert not mock_core.deactivate.called
    assert not mock_core.speak.called
