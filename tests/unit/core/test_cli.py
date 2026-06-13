"""Tests for the core CLI entry point."""

import shutil
import sys
from importlib import import_module
from unittest.mock import MagicMock, call, patch


def test_dunder_main_module():
    """Exercise (most of) the code in the ``__main__`` module."""
    import_module("easyspeak.core.__main__")


def test_entrypoint():
    """Is entrypoint script installed? (pyproject.toml)"""
    assert shutil.which("easyspeak")


@patch("easyspeak.core.cli.EasySpeak")
def test_run(mock_easyspeak):
    """cli.run parses args, configures logging, and runs the app."""
    sys.modules["pyaudio"] = MagicMock()
    from easyspeak.core import cli

    cli.run([])

    assert mock_easyspeak.mock_calls == [call(), call().run()]
