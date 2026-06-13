"""Tests for the core main module."""

import argparse
import logging
import shutil
import sys
from importlib import import_module
from unittest.mock import MagicMock, call, patch

import pytest


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

    main.run([])

    assert mock_easyspeak.mock_calls == [call(), call().run()]


@pytest.mark.parametrize(
    ("flags", "env", "expected"),
    [
        ({"verbose": True, "quiet": False}, None, logging.DEBUG),
        ({"verbose": False, "quiet": True}, None, logging.WARNING),
        ({"verbose": False, "quiet": False}, "WARNING", logging.WARNING),
        ({"verbose": False, "quiet": False}, None, logging.INFO),
        ({"verbose": False, "quiet": False}, "bogus", logging.INFO),
    ],
)
def test_resolve_log_level(flags, env, expected, monkeypatch):
    """CLI flags win, then EASYSPEAK_LOG_LEVEL, then INFO (invalid -> INFO)."""
    sys.modules["pyaudio"] = MagicMock()
    from easyspeak.core import main

    if env is None:
        monkeypatch.delenv("EASYSPEAK_LOG_LEVEL", raising=False)
    else:
        monkeypatch.setenv("EASYSPEAK_LOG_LEVEL", env)

    assert main._resolve_log_level(argparse.Namespace(**flags)) == expected
