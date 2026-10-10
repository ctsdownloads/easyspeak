"""Tests for starting EasySpeak at login (core.autostart)."""

from pathlib import Path

import pytest
from easyspeak.core import autostart


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A throwaway home and system config dir, with paths to both entries."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_DIRS", str(tmp_path / "xdg"))
    user = tmp_path / "home" / ".config" / "autostart" / "easyspeak.desktop"
    system = tmp_path / "xdg" / "autostart" / "easyspeak.desktop"
    return user, system


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_nothing_installed_means_no_autostart(home):
    """Without any entry, nothing starts EasySpeak at login."""
    assert autostart.is_enabled() is False


def test_the_packaged_entry_starts_it(home):
    """The system-wide entry the packages install turns autostart on."""
    _user, system = home
    write(system, "[Desktop Entry]\nName=EasySpeak\n")

    assert autostart.is_enabled() is True


@pytest.mark.parametrize(
    "user_text",
    [
        "[Desktop Entry]\nHidden=true\n",
        "[Desktop Entry]\nX-GNOME-Autostart-enabled=false\n",
    ],
)
def test_the_users_entry_overrides_the_packaged_one(home, user_text):
    """The user's own entry wins, whether turned off the KDE or the GNOME way."""
    user, system = home
    write(system, "[Desktop Entry]\nName=EasySpeak\n")
    write(user, user_text)

    assert autostart.is_enabled() is False


def test_turning_it_off_copies_the_packaged_entry(home):
    """Turning off writes the user's entry from the system one, marked off both ways."""
    user, system = home
    write(system, "[Desktop Entry]\nName=EasySpeak\nExec=easyspeak\n")

    autostart.set_enabled(False)

    text = user.read_text()
    assert "Exec=easyspeak" in text
    assert "Hidden=true" in text
    assert "X-GNOME-Autostart-enabled=false" in text
    assert autostart.is_enabled() is False


def test_turning_it_on_keeps_the_users_edits(home):
    """An existing user entry is the base, so hand edits survive the switch."""
    user, _system = home
    write(user, "[Desktop Entry]\nExec=easyspeak --language de\nHidden=true\n")

    autostart.set_enabled(True)

    text = user.read_text()
    assert "Exec=easyspeak --language de" in text
    assert "Hidden=false" in text
    assert autostart.is_enabled() is True


def test_turning_it_on_without_any_entry_uses_the_template(home):
    """Without any entry, the template EasySpeak ships is the base."""
    user, _system = home

    autostart.set_enabled(True)

    assert "Exec=easyspeak" in user.read_text()
    assert autostart.is_enabled() is True


def test_a_custom_config_home_is_followed(home, tmp_path, monkeypatch):
    """With `XDG_CONFIG_HOME` set, the entry lives there, where the desktop looks."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    custom = tmp_path / "config" / "autostart" / "easyspeak.desktop"

    autostart.set_enabled(True)

    assert custom.is_file()
    assert autostart.is_enabled() is True
    default, _system = home
    assert not default.exists()


def test_a_relative_config_home_is_ignored(home, monkeypatch):
    """A relative `XDG_CONFIG_HOME` is invalid, so `~/.config` is used instead."""
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative/config")
    user, _system = home

    assert autostart.user_entry() == user


def test_relative_system_config_dirs_are_ignored(home, tmp_path, monkeypatch):
    """Only absolute entries of `XDG_CONFIG_DIRS` count, else `/etc/xdg`."""
    monkeypatch.setenv("XDG_CONFIG_DIRS", f"relative:{tmp_path / 'xdg'}")
    _user, system = home
    assert autostart.system_entries() == [system]

    monkeypatch.setenv("XDG_CONFIG_DIRS", "relative")
    assert autostart.system_entries() == [Path("/etc/xdg/autostart/easyspeak.desktop")]
