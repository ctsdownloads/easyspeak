"""Tests for the core CLI entry point."""

import logging
import os
import shutil
import subprocess
import sys
from importlib import import_module
from unittest.mock import call, patch

import pytest
from easyspeak.core import cli, instance


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


@pytest.mark.parametrize(
    ("argv", "command"), [([], "present"), (["-v"], "present verbose")]
)
@patch("easyspeak.core.main.EasySpeak")
def test_run_while_running_greets_from_the_running_copy(
    mock_easyspeak, argv, command, capsys
):
    """A second launch asks the running copy to come forward, then quits."""
    running = instance.acquire()

    cli.run(argv)

    running.close()
    mock_easyspeak.assert_not_called()
    assert instance.CONTROL_FILE.read_text() == command
    assert "EasySpeak is running already" in capsys.readouterr().err


@patch("easyspeak.core.main.EasySpeak")
def test_run_while_running_passes_on_a_verbose_environment(mock_easyspeak, monkeypatch):
    """Verbose by `EASYSPEAK_LOG_LEVEL`, as an alternative to `-v`, asks for the
    details, too."""
    monkeypatch.setenv("EASYSPEAK_LOG_LEVEL", "DEBUG")
    running = instance.acquire()

    cli.run([])

    running.close()
    assert instance.CONTROL_FILE.read_text() == "present verbose"


def test_second_launch_path_leaves_the_speech_stack_unloaded():
    """Checking the lock needs no speech recognition, so a second launch quits
    at once. A fresh interpreter tells, as this suite stubs those modules."""
    check = (
        "import sys; import easyspeak.core.cli, easyspeak.core.instance; "
        "loaded = {'faster_whisper', 'onnx_asr', 'numpy', 'pyaudio'} & set(sys.modules); "
        "sys.exit(', '.join(sorted(loaded)) or None)"
    )

    result = subprocess.run(
        [sys.executable, "-c", check], capture_output=True, text=True
    )

    assert result.returncode == 0, result.stderr


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
