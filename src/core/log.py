"""Logging setup for EasySpeak's terminal output.

Output is message-only (no level or timestamp prefixes) so the CLI reads
nicely for humans; the level only gates which lines appear. Only the
``easyspeak`` and ``plugins`` logger hierarchies are configured, so
importing the package as a library leaves the root logger untouched.
"""

import logging
import os


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
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    for name in ("easyspeak", "plugins"):
        log = logging.getLogger(name)
        log.handlers.clear()
        log.addHandler(handler)
        log.setLevel(level)
        log.propagate = False
