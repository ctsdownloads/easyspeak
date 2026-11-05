"""Logging setup for EasySpeak's terminal output.

Output is message-only (no level or timestamp prefixes) so the CLI reads nicely for
humans; the level only gates which lines appear. Only the `easyspeak` and `plugins`
logger hierarchies are configured, so importing the package as a library leaves the root
logger untouched. The latest warnings and errors are also kept in
[`problems`][core.log.problems], for users who don't look at a terminal.
"""

import collections
import logging
import os

logger = logging.getLogger(__name__)

_PACKAGE_LOGGERS = ("easyspeak", "plugins")

problems: collections.deque[str] = collections.deque(maxlen=10)
"""The latest warnings and errors logged, oldest first."""


class ProblemCollector(logging.Handler):
    """Keep each warning and error in [`problems`][core.log.problems]."""

    def __init__(self):
        """Collect records from WARNING up."""
        super().__init__(logging.WARNING)

    def emit(self, record):
        """Remember the record's message."""
        problems.append(record.getMessage().strip())


def verbose():
    """Whether EasySpeak runs verbose: with `-v`, or `EASYSPEAK_LOG_LEVEL=DEBUG`."""
    return resolve_level() <= logging.DEBUG


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
    """Attach a message-only stderr handler and the problem collector.

    The level is also passed on to the processes EasySpeak starts, such as the tray
    helper, through `EASYSPEAK_LOG_LEVEL`, so they log like the daemon, even when
    the level came from `--verbose` or `--quiet`.
    """
    os.environ["EASYSPEAK_LOG_LEVEL"] = logging.getLevelName(level)
    # Plain message-only output keeps the normal CLI clean; at DEBUG, prefix
    # each line with its level since that mode is for diagnosing.
    fmt = "%(levelname)s %(message)s" if level <= logging.DEBUG else "%(message)s"
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(fmt))
    collector = ProblemCollector()
    for name in _PACKAGE_LOGGERS:
        log = logging.getLogger(name)
        log.handlers.clear()
        log.addHandler(handler)
        log.addHandler(collector)
        log.setLevel(level)
        log.propagate = False
    logger.debug(
        "logging configured: level=%s, stderr, format=%r, loggers=%s",
        logging.getLevelName(level),
        fmt,
        ", ".join(_PACKAGE_LOGGERS),
    )
