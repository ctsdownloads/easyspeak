"""Logging setup for EasySpeak's terminal output.

Output is message-only (no level or timestamp prefixes) so the CLI reads
nicely for humans; the level only gates which lines appear. Only the
``easyspeak`` and ``plugins`` logger hierarchies are configured, so
importing the package as a library leaves the root logger untouched.
"""

import logging
import os

logger = logging.getLogger(__name__)

_PACKAGE_LOGGERS = ("easyspeak", "plugins")


def resolve_level(*, verbose=False, quiet=False):
    """Pick the log level: CLI flags win, then EASYSPEAK_LOG_LEVEL, else INFO."""
    if verbose:
        return logging.DEBUG
    if quiet:
        return logging.WARNING
    name = os.environ.get("EASYSPEAK_LOG_LEVEL", "INFO").upper()
    level = logging.getLevelName(name)
    return level if isinstance(level, int) else logging.INFO


def configure(level):
    """Attach a message-only stderr handler to the package loggers."""
    # Plain message-only output keeps the normal CLI clean; at DEBUG, prefix
    # each line with its level since that mode is for diagnosing.
    fmt = "%(levelname)s %(message)s" if level <= logging.DEBUG else "%(message)s"
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(fmt))
    for name in _PACKAGE_LOGGERS:
        log = logging.getLogger(name)
        log.handlers.clear()
        log.addHandler(handler)
        log.setLevel(level)
        log.propagate = False
    logger.debug(
        "logging configured: level=%s, stderr, format=%r, loggers=%s",
        logging.getLevelName(level),
        fmt,
        ", ".join(_PACKAGE_LOGGERS),
    )
