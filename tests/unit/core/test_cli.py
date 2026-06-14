"""Tests for the core CLI entry point."""

import logging
import shutil
from importlib import import_module
from unittest.mock import call, patch

import pytest
from easyspeak.core import cli


def test_dunder_main_module():
    """Exercise (most of) the code in the ``__main__`` module."""
    import_module("easyspeak.core.__main__")


def test_entrypoint():
    """Is entrypoint script installed? (pyproject.toml)"""
    assert shutil.which("easyspeak")


@patch("easyspeak.core.cli.EasySpeak")
def test_run(mock_easyspeak):
    """cli.run parses args, configures logging, and runs the app."""
    cli.run([])

    assert mock_easyspeak.mock_calls == [call(), call().run()]


@pytest.mark.parametrize(
    ("argv", "verbose", "quiet"),
    [
        ([], False, False),
        (["-v"], True, False),
        (["--verbose"], True, False),
        (["-q"], False, True),
        (["--quiet"], False, True),
    ],
)
def test_parse_args_flags(argv, verbose, quiet):
    """-v/--verbose and -q/--quiet set their flags; default is neither."""
    args = cli.parse_args(argv)

    assert args.verbose is verbose
    assert args.quiet is quiet


def test_parse_args_verbose_and_quiet_are_mutually_exclusive():
    """Passing both -v and -q is rejected by argparse."""
    with pytest.raises(SystemExit):
        cli.parse_args(["-v", "-q"])


def _run_then_log(argv, capsys, level, message):
    """Run the CLI with argv, emit one log record, return its formatted stderr.

    The configured handler's own startup output is discarded so only the
    record's resulting line (if any) is returned.
    """
    cli.run(argv)
    capsys.readouterr()
    logging.getLogger("easyspeak").log(level, message)
    return capsys.readouterr().err


@patch("easyspeak.core.cli.EasySpeak")
def test_run_default_prints_info_without_prefix(mock_easyspeak, capsys):
    """No flag: INFO is shown as the bare message; DEBUG is suppressed."""
    assert _run_then_log([], capsys, logging.INFO, "hello") == "hello\n"
    assert _run_then_log([], capsys, logging.DEBUG, "noise") == ""


@patch("easyspeak.core.cli.EasySpeak")
def test_run_verbose_enables_debug_with_level_prefix(mock_easyspeak, capsys):
    """-v: DEBUG is shown and every line is prefixed with its level name."""
    assert _run_then_log(["-v"], capsys, logging.INFO, "hello") == "INFO hello\n"
    assert _run_then_log(["-v"], capsys, logging.DEBUG, "x") == "DEBUG x\n"


@patch("easyspeak.core.cli.EasySpeak")
def test_run_quiet_silences_info_but_keeps_warnings(mock_easyspeak, capsys):
    """-q: INFO is silent; warnings/errors still print (without a prefix)."""
    assert _run_then_log(["-q"], capsys, logging.INFO, "hidden") == ""
    assert _run_then_log(["-q"], capsys, logging.WARNING, "oops") == "oops\n"
