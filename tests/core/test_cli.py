"""Tests for the core main module."""

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


@patch("easyspeak.core.main.EasySpeak")
def test_main_run(mock_easyspeak):
    """Does main:run instantiate the EasySpeak class and run its method?"""
    sys.modules["pyaudio"] = MagicMock()
    from easyspeak.core import main

    main.run()

    assert mock_easyspeak.mock_calls == [call(), call().run()]
