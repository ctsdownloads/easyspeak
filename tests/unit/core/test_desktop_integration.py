"""Tests for the --configure desktop-integration setup."""

from unittest.mock import patch

import pytest
from easyspeak.core import desktop_integration as di


def test_paths_are_user_local(tmp_path):
    with patch.object(di.Path, "home", return_value=tmp_path):
        assert di.autostart_path() == (
            tmp_path / ".config" / "autostart" / "easyspeak.desktop"
        )
        assert di.desktop_path() == (
            tmp_path / ".local" / "share" / "applications" / "easyspeak.desktop"
        )


def test_install_autostart_file_writes_bundled_template(tmp_path, readlog):
    with patch.object(di.Path, "home", return_value=tmp_path):
        assert di.install_autostart_file() is True
        dest = di.autostart_path()

    body = dest.read_text()
    assert "[Desktop Entry]" in body
    assert "X-GNOME-Autostart-enabled=true" in body
    assert str(dest) in readlog().err


def test_install_desktop_file_writes_bundled_template(tmp_path):
    """The launcher starts this install's own `easyspeak`."""
    with patch.object(di.Path, "home", return_value=tmp_path):
        assert di.install_desktop_file() is True
        assert f"Exec={di.executable()}\n" in di.desktop_path().read_text()


@pytest.fixture(autouse=True)
def _no_launcher(monkeypatch):
    """Run as if started without a wrapping launcher; tests about one set it."""
    monkeypatch.delenv("EASYSPEAK_LAUNCHER", raising=False)


@pytest.fixture
def venv(tmp_path, monkeypatch):
    """An install whose interpreter is `venv/bin/python`."""
    bin_dir = tmp_path / "venv" / "bin"
    bin_dir.mkdir(parents=True)
    monkeypatch.setattr(di.sys, "executable", str(bin_dir / "python"))
    return bin_dir


def test_executable_is_the_program_beside_the_interpreter(venv):
    """The full path, as a project's virtual environment isn't on the session's
    PATH, and the desktop rejects an entry whose program it can't find."""
    (venv / "easyspeak").touch()

    assert di.executable() == str(venv / "easyspeak")


def test_executable_falls_back_to_the_name(venv):
    """Without that program, e.g. run as `python -m`, the name is all there is."""
    assert di.executable() == "easyspeak"


def test_executable_prefers_a_wrapping_launcher(venv, monkeypatch):
    """A launcher that wraps EasySpeak, as Nix's does, is started instead of the
    program it wraps, so the environment it sets up isn't skipped."""
    (venv / "easyspeak").touch()
    monkeypatch.setenv("EASYSPEAK_LAUNCHER", "/nix/store/abc-easyspeak/bin/easyspeak")

    assert di.executable() == "/nix/store/abc-easyspeak/bin/easyspeak"


def test_executable_escapes_the_launcher(monkeypatch):
    """The launcher's path is written as `Exec` spells it, too."""
    monkeypatch.setenv("EASYSPEAK_LAUNCHER", "/opt/My Apps/easyspeak")

    assert di.executable() == '"/opt/My Apps/easyspeak"'


@pytest.mark.parametrize(
    ("argument", "value"),
    [
        ("/usr/bin/easyspeak", "/usr/bin/easyspeak"),
        ("/opt/My Apps/easyspeak", '"/opt/My Apps/easyspeak"'),
        ("/home/o'neil/easyspeak", '"/home/o\'neil/easyspeak"'),
        ('/a "b"/easyspeak', '"/a \\\\"b\\\\"/easyspeak"'),
        ("/a $b `c`/easyspeak", '"/a \\\\$b \\\\`c\\\\`/easyspeak"'),
        ("/a\\b/easyspeak", '"/a\\\\\\\\b/easyspeak"'),
        ("/100%/easyspeak", "/100%%/easyspeak"),
    ],
)
def test_exec_argument_follows_the_specification(argument, value):
    """Reserved characters get the argument quoted, with double quotes, backticks,
    dollar signs and backslashes escaped inside the quotes; each backslash is then
    doubled for the value as a string; a literal `%` is doubled."""
    assert di.exec_argument(argument) == value


def test_install_data_file_write_failure_returns_false(tmp_path, readlog):
    with (
        patch.object(di.Path, "home", return_value=tmp_path),
        patch.object(di.Path, "write_text", side_effect=OSError("read-only")),
    ):
        assert di.install_autostart_file() is False
    assert "could not write" in readlog().err


@pytest.mark.parametrize(
    "items",
    [
        set(),  # empty does nothing; the CLI supplies any default
        {"extension"},
        {"service"},
        {"autostart"},
        {"desktop"},
        {"service", "desktop"},
        {"extension", "service", "autostart", "desktop"},
    ],
)
def test_configure_runs_exactly_the_requested_activities(items):
    expected = items
    done = set()
    with (
        patch.object(di, "activate_extension", lambda: done.add("extension")),
        patch.object(di, "install_refresh_unit", lambda: done.add("service")),
        patch.object(di, "install_autostart_file", lambda: done.add("autostart")),
        patch.object(di, "install_desktop_file", lambda: done.add("desktop")),
    ):
        di.configure(items)

    assert done == expected


@pytest.mark.parametrize(
    ("item", "needle"),
    [
        ("service", "[Unit]"),
        ("autostart", "X-GNOME-Autostart-enabled"),
        ("desktop", "Exec="),
        ("extension", '"uuid"'),  # the metadata.json manifest
    ],
)
def test_preview_renders_each_items_artifact(item, needle, capsys):
    di.preview(item)

    assert needle in capsys.readouterr().out


@pytest.mark.parametrize("text", ["no-newline", "has-newline\n"])
def test_preview_writes_content_verbatim(capsys, text):
    """The content goes to stdout unchanged — no trailing-newline fixup."""
    with patch.object(di, "entry_text", return_value=text):
        di.preview("desktop")

    assert capsys.readouterr().out == text


def test_preview_prints_target_path_to_stderr(capsys):
    """The `TARGET:` line goes to stderr, keeping stdout to just the content."""
    with (
        patch.object(di, "entry_text", return_value="body"),
        patch.object(
            di, "desktop_path", return_value=di.Path("/dest/easyspeak.desktop")
        ),
    ):
        di.preview("desktop")

    captured = capsys.readouterr()
    assert captured.out == "body"
    assert captured.err == "TARGET: /dest/easyspeak.desktop\n"
