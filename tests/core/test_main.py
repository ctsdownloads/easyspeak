"""Tests for the core main module."""

import pytest


def test_main():
    """Importing the main mudule will fail by default."""
    expected_error = "No module named 'pyaudio'"

    with pytest.raises(ModuleNotFoundError, match=expected_error):
        from easyspeak.core import main
