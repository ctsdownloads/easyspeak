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
        "stop listening",
    ],
)
def test_handle_sleep_commands(mock_core, command):
    """When handle receives a sleep phrase then it deactivates and returns True.

    The confirmation is spoken here, on the voice path, so the tray stays silent
    when it releases the mic and the phrase is not repeated. Releasing the mic
    is core's job, at its next tray poll: the plugin only queues it.
    """
    result = sleep.handle(command, mock_core)

    assert result is True
    mock_core.deactivate.assert_called_once()
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
