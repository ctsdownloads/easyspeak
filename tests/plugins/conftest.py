"""Pytest fixtures for plugin tests."""

from unittest.mock import Mock

import pytest


@pytest.fixture
def mock_core():
    """Create a mock core object for testing."""
    core = Mock()
    core.host_run = Mock()
    core.speak = Mock()
    core.stream = Mock()
    core.wait_for_speech = Mock()
    core.record_until_silence = Mock()
    core.transcribe = Mock()
    core.route_command = Mock()
    return core
