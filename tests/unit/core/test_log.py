"""Tests for the core.log module."""

import logging
import os
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
    """configure attaches a stderr handler and the problem collector, and
    isolates the package loggers."""
    log.configure(logging.INFO)

    pkg = logging.getLogger("easyspeak")
    assert pkg.level == logging.INFO
    assert pkg.propagate is False
    assert len(pkg.handlers) == 2
    assert pkg.handlers[0].stream is sys.stderr
    assert isinstance(pkg.handlers[1], log.ProblemCollector)


def test_configure_collects_warnings_and_errors(capsys):
    """Warnings and errors are kept, stripped of the blank lines around them,
    and plain information isn't."""
    log.configure(logging.INFO)

    logging.getLogger("easyspeak.core").info("Loading plugins...")
    logging.getLogger("plugins.media").warning("\nNo player %s", "found")
    logging.getLogger("easyspeak.core").error("Cannot start")

    assert list(log.problems) == [
        (logging.WARNING, "No player found"),
        (logging.ERROR, "Cannot start"),
    ]


def test_problems_keeps_only_the_latest():
    """A long-running daemon keeps the latest ten problems, not every one."""
    log.configure(logging.INFO)

    for n in range(12):
        logging.getLogger("easyspeak").warning("problem %d", n)

    assert list(log.problems) == [
        (logging.WARNING, f"problem {n}") for n in range(2, 12)
    ]


@pytest.mark.parametrize(
    ("level", "expected"),
    [(logging.DEBUG, True), (logging.INFO, False), (logging.WARNING, False)],
)
def test_verbose(level, expected):
    """Verbose means the debug level, from `-v` or `EASYSPEAK_LOG_LEVEL`."""
    log.configure(level)

    assert log.verbose() is expected


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


@pytest.mark.parametrize("level", [logging.DEBUG, logging.WARNING])
def test_configure_passes_the_level_on(level):
    """Processes EasySpeak starts inherit the level, even one from a CLI flag."""
    log.configure(level)

    assert os.environ["EASYSPEAK_LOG_LEVEL"] == logging.getLevelName(level)
    assert log.resolve_level() == level
