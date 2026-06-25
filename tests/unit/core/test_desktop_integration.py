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
def test_item_text_returns_the_items_artifact(item, needle):
    assert needle in di.item_text(item)


def test_show_single_item_is_unlabelled(capsys):
    di.show(["service"])

    out = capsys.readouterr().out
    assert out.startswith("[Unit]")
    assert "# service" not in out


def test_show_multiple_items_are_labelled(capsys):
    di.show(["autostart", "desktop"])

    out = capsys.readouterr().out
    assert "# autostart\n" in out
    assert "# desktop\n" in out


@pytest.mark.parametrize(
    ("text", "expected"),
    [("no-newline", "no-newline\n"), ("has-newline\n", "has-newline\n")],
)
def test_show_normalises_the_trailing_newline(capsys, text, expected):
    with patch.object(di, "item_text", return_value=text):
        di.show(["service"])

    assert capsys.readouterr().out == expected
