"""Logging setup: EasySpeak's terminal output, and messages for the desktop.

Output is message-only (no level or timestamp prefixes) so the CLI reads nicely for
humans; the level only gates which lines appear. Only the `easyspeak` and `plugins`
logger hierarchies are configured, so importing the package as a library leaves the root
logger untouched.

Warnings, errors and messages logged with `extra=NOTIFY` are also collected, for
people who don't look at a terminal: the latest in [`recent`][core.log.recent], and
those not delivered yet in [`pending`][core.log.pending]. Started with `-v`,
EasySpeak shows each as a desktop notification and says where it came from (see
[`Tray.report`][core.tray.Tray.report]). Logging only collects them, which keeps it
cheap and safe from any thread.
"""

import collections
import logging
import os
from typing import NamedTuple

logger = logging.getLogger(__name__)

_PACKAGE_LOGGERS = ("easyspeak", "plugins")

NOTIFY = {"notify": True}
"""Pass as `extra=` to have an INFO message shown on the desktop, too, with `-v`."""


class Message(NamedTuple):
    """A message for the desktop: its level, its logger's name and its text."""

    level: int
    source: str
    text: str


recent: collections.deque[Message] = collections.deque(maxlen=10)
"""The latest messages for the desktop, oldest first, to show when asked for later."""

pending: collections.deque[Message] = collections.deque(maxlen=50)
"""The messages for the desktop not delivered yet, oldest first."""


class MessageCollector(logging.Handler):
    """Keep warnings, errors and `NOTIFY` messages for the desktop."""

    def emit(self, record):
        """Collect the record if it is meant for the desktop."""
        if record.levelno < logging.WARNING and not getattr(record, "notify", False):
            return
        message = Message(record.levelno, record.name, record.getMessage().strip())
        recent.append(message)
        pending.append(message)


_settings = {"verbose": False}


def verbose():
    """Whether EasySpeak shows and speaks its messages, as `-v` asks."""
    return _settings["verbose"]


def resolve_level(*, debug=False, quiet=False):
    """Pick the terminal's log level: flags win, then EASYSPEAK_LOG_LEVEL, else INFO."""
    if debug:
        return logging.DEBUG
    if quiet:
        return logging.WARNING
    name = os.environ.get("EASYSPEAK_LOG_LEVEL", "INFO").upper()
    level = logging.getLevelName(name)
    return level if isinstance(level, int) else logging.INFO


def configure(level, *, verbose=False):
    """Attach a message-only stderr handler at `level` and the message collector.

    `verbose` is whether the messages for the desktop are delivered there, too. The
    loggers let INFO through even below a quieter terminal, so `NOTIFY` messages
    reach the collector.

    The level is also passed on to the processes EasySpeak starts, such as the tray
    helper, through `EASYSPEAK_LOG_LEVEL`, so they log like the daemon, even when
    the level came from `--debug` or `--quiet`.
    """
    _settings["verbose"] = verbose
    os.environ["EASYSPEAK_LOG_LEVEL"] = logging.getLevelName(level)
    # Plain message-only output keeps the normal CLI clean; at DEBUG, prefix
    # each line with its level since that mode is for diagnosing.
    fmt = "%(levelname)s %(message)s" if level <= logging.DEBUG else "%(message)s"
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(fmt))
    handler.setLevel(level)
    collector = MessageCollector()
    for name in _PACKAGE_LOGGERS:
        log = logging.getLogger(name)
        log.handlers.clear()
        log.addHandler(handler)
        log.addHandler(collector)
        log.setLevel(min(level, logging.INFO))
        log.propagate = False
    logger.debug(
        "logging configured: level=%s, stderr, format=%r, loggers=%s, verbose=%s",
        logging.getLevelName(level),
        fmt,
        ", ".join(_PACKAGE_LOGGERS),
        verbose,
    )
