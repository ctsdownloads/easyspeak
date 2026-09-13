"""Pytest fixtures for plugin tests."""

from unittest.mock import Mock

import pytest

# How many times a constant `transcribe.return_value` is replayed to a modal
# loop; enough for the tests that expect a repeat, bounded so none can spin.
REPEATED_TRANSCRIPTION_LIMIT = 3


def attach_listen_modal(core):
    """Give a mock core a stand-in for EasySpeak.listen_modal. Returns the core.

    The real generator (core.main) owns the wait/record/transcribe boilerplate and
    the tray poll shared by every modal plugin mode, so plugin tests only care which
    commands arrive. This reads them from whatever the test put on
    `core.transcribe.side_effect` — lazily, so it works whether the values were set
    before or after this call — and normalises each exactly as core does. Falsy
    entries are skipped, so feeding `[None, "close"]` still covers "nothing
    recognised, then a command".
    """

    def _listen_modal(_label, **_kwargs):
        values = getattr(core.transcribe, "side_effect", None) or []
        yielded = False
        for value in values:
            if value:
                yielded = True
                yield value.strip(".,!? ")
        if yielded:
            return
        # Tests that set a constant `transcribe.return_value` relied on the old
        # `while` loop supplying it repeatedly. Repeat it a bounded number of
        # times so those keep working without any test being able to spin.
        constant = getattr(core.transcribe, "return_value", None)
        if isinstance(constant, str) and constant:
            for _ in range(REPEATED_TRANSCRIPTION_LIMIT):
                yield constant.strip(".,!? ")

    core.listen_modal = Mock(side_effect=_listen_modal)
    return core


@pytest.fixture
def mock_core():
    """Create a mock core object for testing plugins.

    Session flags a plugin's setup() would set are set here too. A bare Mock
    invents any attribute asked of it and every invented one is truthy, so
    without this a flag meaning "already in browser mode" reads as True.
    """
    core = Mock()
    core.stream.read = Mock()
    core.stream.get_read_available = Mock(return_value=1024)
    core.browser_page_js_stale = False
    core.in_browser_mode = False
    return attach_listen_modal(core)


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
    return attach_listen_modal(core)


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
        # Session flags a plugin's setup() would set; see mock_core.
        core.browser_page_js_stale = False
        core.in_browser_mode = False

        if wait_for_speech_values is not None:
            core.wait_for_speech = Mock(side_effect=wait_for_speech_values)
        else:
            core.wait_for_speech = Mock()

        core.record_until_silence = Mock(return_value=record_until_silence_value)

        if transcribe_values is not None:
            core.transcribe = Mock(side_effect=transcribe_values)
        else:
            core.transcribe = Mock()

        return attach_listen_modal(core)

    return _create_mock_core
