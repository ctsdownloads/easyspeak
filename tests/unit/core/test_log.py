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


def test_configure_isolates_package_loggers():
    """configure attaches one stderr handler and isolates the package loggers."""
    log.configure(logging.INFO)

    pkg = logging.getLogger("easyspeak")
    assert pkg.level == logging.INFO
    assert pkg.propagate is False
    assert len(pkg.handlers) == 1
    assert pkg.handlers[0].stream is sys.stderr


def _format_info_record():
    handler = logging.getLogger("easyspeak").handlers[0]
    record = logging.LogRecord("n", logging.INFO, "", 0, "hello", None, None)
    return handler.format(record)


def test_configure_message_only_above_debug():
    """Above DEBUG, output is the bare message."""
    log.configure(logging.INFO)
    assert _format_info_record() == "hello"


def test_configure_level_prefixed_at_debug():
    """At DEBUG, output is prefixed with the level name."""
    log.configure(logging.DEBUG)
    assert _format_info_record() == "INFO hello"


def test_configure_reports_config_at_debug(capsys):
    """At DEBUG, configure echoes the resolved configuration on startup."""
    log.configure(logging.DEBUG)

    assert "logging configured: level=DEBUG" in capsys.readouterr().err


def test_configure_quiet_about_config_above_debug(capsys):
    """Below DEBUG, the configuration line is suppressed."""
    log.configure(logging.INFO)

    assert capsys.readouterr().err == ""
