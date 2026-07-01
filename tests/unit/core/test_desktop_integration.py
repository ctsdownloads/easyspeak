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
    with patch.object(di.Path, "home", return_value=tmp_path):
        assert di.install_desktop_file() is True
        assert "Exec=easyspeak" in di.desktop_path().read_text()


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
        ("desktop", "Exec=easyspeak"),
        ("extension", '"uuid"'),  # the metadata.json manifest
    ],
)
def test_preview_renders_each_items_artifact(item, needle, capsys):
    di.preview(item)

    assert needle in capsys.readouterr().out


@pytest.mark.parametrize("text", ["no-newline", "has-newline\n"])
def test_preview_writes_content_verbatim(capsys, text):
    """The content goes to stdout unchanged — no trailing-newline fixup."""
    with patch.object(di, "data_text", return_value=text):
        di.preview("desktop")

    assert capsys.readouterr().out == text


def test_preview_prints_target_path_to_stderr(capsys):
    """The `TARGET:` line goes to stderr, keeping stdout to just the content."""
    with (
        patch.object(di, "data_text", return_value="body"),
        patch.object(
            di, "desktop_path", return_value=di.Path("/dest/easyspeak.desktop")
        ),
    ):
        di.preview("desktop")

    captured = capsys.readouterr()
    assert captured.out == "body"
    assert captured.err == "TARGET: /dest/easyspeak.desktop\n"
