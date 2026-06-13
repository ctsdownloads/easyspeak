"""Shared fixtures for the unit suite."""

import logging

import pytest


class CapturedLog:
    """A capsys-style view over captured log text.

    EasySpeak's terminal output goes through ``logging`` rather than ``print``,
    so ``.out`` and ``.err`` both return the captured log text and existing
    output assertions can keep reading from a single place.
    """

    def __init__(self, text):
        self.out = text
        self.err = text


@pytest.fixture(autouse=True)
def _restore_easyspeak_loggers():
    """Snapshot and restore the package loggers around each test.

    ``log.configure`` mutates the ``easyspeak`` and ``plugins`` loggers
    (handlers, level, ``propagate``); restoring them keeps a test that calls it
    from leaking that state into later tests that rely on ``caplog``.
    """
    names = ("easyspeak", "plugins")
    saved = [
        (
            logging.getLogger(n),
            logging.getLogger(n).handlers[:],
            logging.getLogger(n).level,
            logging.getLogger(n).propagate,
        )
        for n in names
    ]
    yield
    for log, handlers, level, propagate in saved:
        log.handlers[:] = handlers
        log.setLevel(level)
        log.propagate = propagate


@pytest.fixture
def readlog(caplog):
    """Return a reader yielding captured log output, capsys-style.

    Mirrors ``capsys.readouterr()``: each call returns the text logged since the
    previous call, then clears the buffer.
    """
    caplog.set_level(logging.DEBUG)

    def _read():
        captured = CapturedLog(caplog.text)
        caplog.clear()
        return captured

    return _read
