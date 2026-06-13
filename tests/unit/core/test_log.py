"""Tests for the core.log module."""

import logging
import sys

import pytest
from easyspeak.core import log


@pytest.mark.parametrize(
    ("kwargs", "env", "expected"),
    [
        ({"verbose": True}, None, logging.DEBUG),
        ({"quiet": True}, None, logging.WARNING),
        ({}, "WARNING", logging.WARNING),
        ({}, None, logging.INFO),
        ({}, "bogus", logging.INFO),
    ],
)
def test_resolve_level(kwargs, env, expected, monkeypatch):
    """CLI flags win, then EASYSPEAK_LOG_LEVEL, then INFO (invalid -> INFO)."""
    if env is None:
        monkeypatch.delenv("EASYSPEAK_LOG_LEVEL", raising=False)
    else:
        monkeypatch.setenv("EASYSPEAK_LOG_LEVEL", env)

    assert log.resolve_level(**kwargs) == expected


def test_configure_sets_message_only_stderr_handler():
    """configure attaches one message-only handler and isolates the loggers."""
    log.configure(logging.DEBUG)

    pkg = logging.getLogger("easyspeak")
    assert pkg.level == logging.DEBUG
    assert pkg.propagate is False
    assert len(pkg.handlers) == 1

    handler = pkg.handlers[0]
    assert handler.stream is sys.stderr
    record = logging.LogRecord("n", logging.INFO, "", 0, "hello", None, None)
    assert handler.format(record) == "hello"
