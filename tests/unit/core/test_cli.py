"""Tests for the core CLI entry point."""

import logging
import os
import shutil
import sys
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


@patch("easyspeak.core.main.EasySpeak")
def test_run(mock_easyspeak):
    """cli.run parses args, configures logging, and runs the app."""
    cli.run([])

    assert mock_easyspeak.mock_calls == [call(), call().run()]


@patch("easyspeak.core.main.EasySpeak")
def test_run_ends_quietly_on_ctrl_c(mock_easyspeak, capsys):
    """Ctrl+C while the models still load ends EasySpeak without a stack trace."""
    mock_easyspeak.return_value.run.side_effect = KeyboardInterrupt

    cli.run([])

    assert "Stopped (Ctrl+C)." in capsys.readouterr().err


def test_run_ends_quietly_on_ctrl_c_while_importing(capsys, monkeypatch):
    """Ctrl+C while the audio stack is still being imported ends quietly too."""
    import builtins

    real_import = builtins.__import__

    def interrupted_import(name, *args, **kwargs):
        if name == "main" and args[2] and "EasySpeak" in args[2]:
            raise KeyboardInterrupt
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", interrupted_import)

    cli.run([])

    assert "Stopped (Ctrl+C)." in capsys.readouterr().err


@patch("easyspeak.core.main.EasySpeak")
def test_run_language_overrides_the_environment(mock_easyspeak, monkeypatch):
    """--language sets EASYSPEAK_LANGUAGE before the app, and its config, load."""
    monkeypatch.setenv("EASYSPEAK_LANGUAGE", "en")

    cli.run(["--language", "de"])

    assert os.environ["EASYSPEAK_LANGUAGE"] == "de"
    assert mock_easyspeak.mock_calls == [call(), call().run()]


@patch("easyspeak.core.main.EasySpeak")
def test_run_without_language_leaves_the_environment_alone(mock_easyspeak, monkeypatch):
    """No --language: whatever EASYSPEAK_LANGUAGE says stands."""
    monkeypatch.setenv("EASYSPEAK_LANGUAGE", "it")

    cli.run([])

    assert os.environ["EASYSPEAK_LANGUAGE"] == "it"


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


@patch("easyspeak.core.cli.app_version", return_value="1.2.3")
def test_version_prints_program_and_version_then_exits(_app_version, capsys):
    """--version prints "easyspeak <version>" and exits 0 without running the app."""
    with pytest.raises(SystemExit) as exc:
        cli.parse_args(["--version"])

    assert exc.value.code == 0
    assert capsys.readouterr().out == "easyspeak 1.2.3\n"


def _run_then_log(argv, capsys, level, message):
    """Run the CLI with argv, emit one log record, return its formatted stderr.

    The configured handler's own startup output is discarded so only the
    record's resulting line (if any) is returned.
    """
    cli.run(argv)
    capsys.readouterr()
    logging.getLogger("easyspeak").log(level, message)
    return capsys.readouterr().err


@patch("easyspeak.core.main.EasySpeak")
def test_run_default_prints_info_without_prefix(mock_easyspeak, capsys):
    """No flag: INFO is shown as the bare message; DEBUG is suppressed."""
    assert _run_then_log([], capsys, logging.INFO, "hello") == "hello\n"
    assert _run_then_log([], capsys, logging.DEBUG, "noise") == ""


@patch("easyspeak.core.main.EasySpeak")
def test_run_verbose_enables_debug_with_level_prefix(mock_easyspeak, capsys):
    """-v: DEBUG is shown and every line is prefixed with its level name."""
    assert _run_then_log(["-v"], capsys, logging.INFO, "hello") == "INFO hello\n"
    assert _run_then_log(["-v"], capsys, logging.DEBUG, "x") == "DEBUG x\n"


@patch("easyspeak.core.main.EasySpeak")
def test_run_quiet_silences_info_but_keeps_warnings(mock_easyspeak, capsys):
    """-q: INFO is silent; warnings/errors still print (without a prefix)."""
    assert _run_then_log(["-q"], capsys, logging.INFO, "hidden") == ""
    assert _run_then_log(["-q"], capsys, logging.WARNING, "oops") == "oops\n"


@patch("easyspeak.core.desktop_integration.configure")
def test_run_configure_dispatches_items_and_skips_app(mock_configure):
    """--configure runs setup with the parsed items and does not start the app."""
    cli.run(["--configure", "autostart"])

    mock_configure.assert_called_once_with({"autostart"})


@patch("easyspeak.core.desktop_integration.configure")
def test_run_configure_with_no_items_applies_default(mock_configure):
    """--configure with no items is resolved to the default pair by parse_args."""
    cli.run(["--configure"])

    mock_configure.assert_called_once_with({"extension", "service"})


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], None),  # no --configure: run the app
        (["--configure"], {"extension", "service"}),  # empty → default pair
        (["--configure", "autostart"], {"autostart"}),  # explicit items kept
    ],
)
def test_parse_args_configure_default(argv, expected):
    """parse_args fills the default pair only for a bare --configure."""
    assert cli.parse_args(argv).configure == expected


@patch("easyspeak.core.desktop_integration.preview")
def test_run_preview_prints_item_and_skips_app(mock_preview):
    """--preview prints the requested item and does not start the app."""
    cli.run(["--preview", "service"])

    mock_preview.assert_called_once_with("service")


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], None),  # no --preview: run the app
        (["--preview", "desktop"], "desktop"),  # the single item to print
    ],
)
def test_parse_args_preview(argv, expected):
    """parse_args records the one --preview item, or None when absent."""
    assert cli.parse_args(argv).preview == expected


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], False),  # no --provision-kokoro: run the app
        (["--provision-kokoro"], True),  # the provisioning one-shot
    ],
)
def test_parse_args_provision_kokoro(argv, expected):
    """parse_args records --provision-kokoro, or False when absent."""
    assert cli.parse_args(argv).provision_kokoro is expected


def test_help_lists_provision_kokoro(capsys):
    """--help lists the provisioning one-shot with a one-line description."""
    with pytest.raises(SystemExit) as exc:
        cli.parse_args(["--help"])

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--provision-kokoro" in out
    assert "reply-voice engine" in out


@patch("easyspeak.core.provision.provision_kokoro")
def test_run_provision_kokoro_dispatches_and_returns_its_code(
    mock_provision, monkeypatch, capsys
):
    """--provision-kokoro runs the provisioner, whose int is run()'s return."""
    # conftest imports core.main at module scope, so drop it for this test:
    # if the dispatch ever fell through to the app, the import would re-add it.
    monkeypatch.delitem(sys.modules, "easyspeak.core.main", raising=False)
    mock_provision.return_value = 7

    assert cli.run(["--provision-kokoro"]) == 7

    mock_provision.assert_called_once_with()
    # The one-shot works without the audio stack: core.main never loaded.
    assert "easyspeak.core.main" not in sys.modules
    # stdout stays pure; the machine line is the provisioner's own business.
    assert capsys.readouterr().out == ""


@patch("easyspeak.core.provision.provision_kokoro")
def test_run_provision_kokoro_ends_quietly_on_ctrl_c(mock_provision, capsys):
    """Ctrl+C mid-provision ends quietly and exits 1, per the 0/1 contract."""
    mock_provision.side_effect = KeyboardInterrupt

    assert cli.run(["--provision-kokoro"]) == 1

    assert "Stopped (Ctrl+C)." in capsys.readouterr().err


def test_run_provision_kokoro_dispatches_after_logging_is_configured(monkeypatch):
    """The provisioner's INFO narration only survives once configure() ran."""
    sequence = []
    monkeypatch.setattr(
        "easyspeak.core.log.configure", lambda level: sequence.append("configure")
    )

    def fake_provision():
        sequence.append("provision")
        return 0

    monkeypatch.setattr("easyspeak.core.provision.provision_kokoro", fake_provision)

    cli.run(["--provision-kokoro"])

    assert sequence == ["configure", "provision"]
