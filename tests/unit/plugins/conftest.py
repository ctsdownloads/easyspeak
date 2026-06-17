"""Pytest fixtures for plugin tests."""

from unittest.mock import Mock

import pytest


@pytest.fixture
def mock_core():
    """Create a mock core object for testing plugins."""
    core = Mock()
    core.stream.read = Mock()
    core.stream.get_read_available = Mock(return_value=1024)
    return core


@pytest.fixture
def mock_core_success(mock_core):
    """Create a mock core with host_run returning success (returncode=0)."""
    mock_core.host_run.return_value = Mock(returncode=0)
    return mock_core


@pytest.fixture
def mock_core_failure(mock_core):
    """Create a mock core with host_run returning failure (returncode=1)."""
    mock_core.host_run.return_value = Mock(returncode=1)
    return mock_core


@pytest.fixture
def mock_core_with_audio():
    """Create a mock core with standard audio recording setup."""
    core = Mock()
    core.stream.read = Mock()
    core.stream.get_read_available = Mock(return_value=1024)
    core.wait_for_speech = Mock(return_value=b"audio1")
    core.record_until_silence = Mock(return_value=b"audio2")
    return core


@pytest.fixture
def mock_core_no_file_manager():
    """Create a mock core that simulates no file manager being available."""
    core = Mock()
    core.host_run = Mock(return_value=Mock(returncode=1))
    core.speak = Mock()
    return core


@pytest.fixture
def mock_core_which_finds_file_manager():
    """Factory fixture that creates a mock core simulating finding a specific file manager."""

    def _create_mock(file_manager):
        def side_effect(cmd, **kwargs):
            result = Mock()
            result.returncode = 0 if cmd[1] == file_manager else 1
            return result

        core = Mock()
        core.host_run = Mock(side_effect=side_effect)
        core.speak = Mock()
        return core

    return _create_mock


@pytest.fixture
def mock_core_factory():
    """Factory fixture to create mock core with custom transcription setup."""

    def _create_mock_core(
        wait_for_speech_values=None,
        record_until_silence_value=b"audio_data",
        transcribe_values=None,
    ):
        """
        Create a mock core with custom audio/transcription configuration.

        Args:
            wait_for_speech_values: List of values for wait_for_speech side_effect
            record_until_silence_value: Return value for record_until_silence
            transcribe_values: List of values for transcribe side_effect
        """
        core = Mock()
        core.stream.read = Mock()
        core.stream.get_read_available = Mock(return_value=1024)

        if wait_for_speech_values is not None:
            core.wait_for_speech = Mock(side_effect=wait_for_speech_values)
        else:
            core.wait_for_speech = Mock()

        core.record_until_silence = Mock(return_value=record_until_silence_value)

        if transcribe_values is not None:
            core.transcribe = Mock(side_effect=transcribe_values)
        else:
            core.transcribe = Mock()

        return core

    return _create_mock_core
