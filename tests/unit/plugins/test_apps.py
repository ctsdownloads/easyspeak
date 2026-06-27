"""Tests for the apps plugin module."""

from unittest.mock import Mock, patch

import pytest
from easyspeak.plugins import apps


def test_setup(mock_core):
    """When setup is called, then core reference is stored."""
    apps.setup(mock_core)

    assert apps.core == mock_core


@pytest.mark.parametrize(
    ["app_name", "flatpak_id"],
    [
        ["firefox", "org.mozilla.firefox"],
        ["steam", "com.valvesoftware.Steam"],
        ["spotify", "com.spotify.Client"],
        ["calculator", "org.gnome.Calculator"],
        ["settings", "org.gnome.Settings"],
    ],
)
def test_find_app_flatpak_installed(mock_core_success, app_name, flatpak_id):
    """When flatpak app is installed, then it is found as flatpak type."""
    app_type, app_id = apps.find_app(app_name, mock_core_success)

    assert app_type == "flatpak"
    assert app_id == flatpak_id
    assert mock_core_success.host_run.call_args.args == (
        ["flatpak", "info", flatpak_id],
    )


@pytest.mark.parametrize(
    "app_name",
    [
        "firefox",
        "steam",
        "spotify",
    ],
)
def test_find_app_flatpak_not_installed(mock_core_failure, app_name):
    """When flatpak app is not installed, then None is returned."""
    app_type, app_id = apps.find_app(app_name, mock_core_failure)

    assert app_type is None
    assert app_id is None
    assert mock_core_failure.host_run.call_count == 2
    assert (["flatpak", "info", apps.FLATPAK_APPS[app_name]],) in [
        c.args for c in mock_core_failure.host_run.call_args_list
    ]
    assert (["which", app_name],) in [
        c.args for c in mock_core_failure.host_run.call_args_list
    ]


@pytest.mark.parametrize(
    ["app_name", "binary_name"],
    [
        ["nautilus", "nautilus"],
        ["browser", "qutebrowser"],
    ],
)
def test_find_app_local(mock_core, app_name, binary_name):
    """When local app exists, then it is found as local type."""
    app_type, app_id = apps.find_app(app_name, mock_core)

    assert app_type == "local"
    assert app_id == binary_name


def test_find_app_in_path(mock_core_success):
    """When app is found in PATH, then it is returned as local type."""
    app_name = "custom-app"

    app_type, app_id = apps.find_app(app_name, mock_core_success)

    assert app_type == "local"
    assert app_id == app_name
    assert mock_core_success.host_run.call_args.args == (["which", app_name],)


def test_find_app_not_found(mock_core_failure):
    """When app is not found anywhere, then None is returned."""
    app_name = "nonexistent-app"

    app_type, app_id = apps.find_app(app_name, mock_core_failure)

    assert app_type is None
    assert app_id is None
    assert mock_core_failure.host_run.call_args.args == (["which", app_name],)


@patch(
    "easyspeak.plugins.apps.find_app", return_value=("flatpak", "org.mozilla.firefox")
)
def test_launch_app_flatpak(mock_find_app, mock_core):
    """When flatpak app is launched, then it runs via flatpak command."""
    app_name = "firefox"

    result = apps.launch_app(app_name, mock_core)

    assert result is True
    assert mock_find_app.call_args.args == (app_name, mock_core)
    assert mock_core.host_run.call_args.args == (
        ["flatpak", "run", "org.mozilla.firefox"],
    )
    assert mock_core.host_run.call_args.kwargs == {
        "background": True,
        "clean_env": True,
    }


@patch("easyspeak.plugins.apps.find_app", return_value=("local", "nautilus"))
def test_launch_app_local(mock_find_app, mock_core):
    """When local app is launched, then it runs directly."""
    app_name = "nautilus"

    result = apps.launch_app(app_name, mock_core)

    assert result is True
    assert mock_find_app.call_args.args == (app_name, mock_core)
    assert mock_core.host_run.call_args.args == (["nautilus"],)
    assert mock_core.host_run.call_args.kwargs == {
        "background": True,
        "clean_env": True,
    }


@patch("easyspeak.plugins.apps.find_app", return_value=(None, None))
def test_launch_app_not_found(mock_find_app, mock_core):
    """When app is not found, then launch fails and returns False."""
    app_name = "nonexistent"

    result = apps.launch_app(app_name, mock_core)

    assert result is False
    assert mock_find_app.call_args.args == (app_name, mock_core)
    assert not mock_core.host_run.called


@patch(
    "easyspeak.plugins.apps.find_app", return_value=("flatpak", "org.mozilla.firefox")
)
def test_close_app_flatpak(mock_find_app, mock_core):
    """When flatpak app is closed, then it kills via flatpak command."""
    app_name = "firefox"

    result = apps.close_app(app_name, mock_core)

    assert result is True
    assert mock_find_app.call_args.args == (app_name, mock_core)
    assert mock_core.host_run.call_args.args == (
        ["flatpak", "kill", "org.mozilla.firefox"],
    )


@patch("easyspeak.plugins.apps.find_app", return_value=("local", "nautilus"))
def test_close_app_local(mock_find_app, mock_core):
    """When local app is closed, then it kills via pkill command."""
    app_name = "files"

    result = apps.close_app(app_name, mock_core)

    assert result is True
    assert mock_find_app.call_args.args == (app_name, mock_core)
    assert mock_core.host_run.call_args.args == (["pkill", "-f", "nautilus"],)


@patch("easyspeak.plugins.apps.find_app", return_value=(None, None))
def test_close_app_not_found(mock_find_app, mock_core):
    """When app is not found, then close fails and returns False."""
    app_name = "nonexistent"

    result = apps.close_app(app_name, mock_core)

    assert result is False
    assert mock_find_app.call_args.args == (app_name, mock_core)
    assert not mock_core.host_run.called


@pytest.fixture(autouse=True)
def _reset_apps():
    """Keep setup()'s discovered terminal entry from leaking between tests."""
    local, flatpak = apps.LOCAL_APPS.copy(), apps.FLATPAK_APPS.copy()
    yield
    apps.LOCAL_APPS.clear()
    apps.LOCAL_APPS.update(local)
    apps.FLATPAK_APPS.clear()
    apps.FLATPAK_APPS.update(flatpak)


def test_setup_registers_terminal_via_xdg_spec(mock_core):
    """When the spec launcher exists, then setup registers the real terminal binary."""

    def side_effect(cmd, **kwargs):
        if cmd == ["which", "xdg-terminal-exec"]:
            return Mock(returncode=0)
        if cmd == ["xdg-terminal-exec", "--print-cmd"]:
            return Mock(
                returncode=0,
                stdout="/opt/ghostty/bin/ghostty\n--gtk-single-instance=true\n",
            )
        if cmd == ["which", "/opt/ghostty/bin/ghostty"]:
            return Mock(returncode=0)
        return Mock(returncode=1)

    mock_core.host_run.side_effect = side_effect

    apps.setup(mock_core)

    assert apps.LOCAL_APPS["terminal"] == "/opt/ghostty/bin/ghostty"


def test_setup_skips_env_wrapper_in_xdg_spec(mock_core):
    """When the spec wraps the terminal in env, then setup registers the binary, not env."""

    def side_effect(cmd, **kwargs):
        if cmd == ["which", "xdg-terminal-exec"]:
            return Mock(returncode=0)
        if cmd == ["xdg-terminal-exec", "--print-cmd"]:
            return Mock(returncode=0, stdout="/usr/bin/env\nFOO=bar\nghostty\n")
        if cmd == ["which", "ghostty"]:
            return Mock(returncode=0)
        return Mock(returncode=1)

    mock_core.host_run.side_effect = side_effect

    apps.setup(mock_core)

    assert apps.LOCAL_APPS["terminal"] == "ghostty"


def test_setup_registers_flatpak_terminal_by_app_id(mock_core):
    """When the default terminal is a flatpak, then setup registers it by app-id."""

    def side_effect(cmd, **kwargs):
        if cmd == ["which", "xdg-terminal-exec"]:
            return Mock(returncode=0)
        if cmd == ["xdg-terminal-exec", "--print-cmd"]:
            return Mock(
                returncode=0,
                stdout="flatpak\nrun\n--branch=stable\ncom.raggesilver.BlackBox\n",
            )
        if cmd == ["flatpak", "info", "com.raggesilver.BlackBox"]:
            return Mock(returncode=0)
        return Mock(returncode=1)

    mock_core.host_run.side_effect = side_effect

    apps.setup(mock_core)

    assert apps.FLATPAK_APPS["terminal"] == "com.raggesilver.BlackBox"
    assert "terminal" not in apps.LOCAL_APPS


def test_setup_registers_snap_terminal_by_name(mock_core):
    """When the default terminal is a snap, then setup registers its executable name."""

    def side_effect(cmd, **kwargs):
        if cmd == ["which", "xdg-terminal-exec"]:
            return Mock(returncode=0)
        if cmd == ["xdg-terminal-exec", "--print-cmd"]:
            return Mock(returncode=0, stdout="snap\nrun\nalacritty\n")
        if cmd == ["which", "alacritty"]:
            return Mock(returncode=0)
        return Mock(returncode=1)

    mock_core.host_run.side_effect = side_effect

    apps.setup(mock_core)

    assert apps.LOCAL_APPS["terminal"] == "alacritty"


def test_setup_falls_back_when_spec_terminal_uninstalled(mock_core):
    """When the spec names a terminal not in PATH, then setup falls back to PATH."""

    def side_effect(cmd, **kwargs):
        if cmd == ["which", "xdg-terminal-exec"]:
            return Mock(returncode=0)
        if cmd == ["xdg-terminal-exec", "--print-cmd"]:
            return Mock(returncode=0, stdout="ghostty\n")
        if cmd == ["which", "kgx"]:
            return Mock(returncode=0)
        return Mock(returncode=1)

    mock_core.host_run.side_effect = side_effect

    apps.setup(mock_core)

    assert apps.LOCAL_APPS["terminal"] == "kgx"


def test_setup_falls_back_when_spec_flatpak_uninstalled(mock_core):
    """When the spec names an uninstalled flatpak terminal, then setup falls back."""

    def side_effect(cmd, **kwargs):
        if cmd == ["which", "xdg-terminal-exec"]:
            return Mock(returncode=0)
        if cmd == ["xdg-terminal-exec", "--print-cmd"]:
            return Mock(returncode=0, stdout="flatpak\nrun\ncom.raggesilver.BlackBox\n")
        if cmd == ["which", "kgx"]:
            return Mock(returncode=0)
        return Mock(returncode=1)

    mock_core.host_run.side_effect = side_effect

    apps.setup(mock_core)

    assert apps.LOCAL_APPS["terminal"] == "kgx"
    assert "terminal" not in apps.FLATPAK_APPS


def test_setup_falls_back_when_spec_snap_uninstalled(mock_core):
    """When the spec names an uninstalled snap terminal, then setup falls back."""

    def side_effect(cmd, **kwargs):
        if cmd == ["which", "xdg-terminal-exec"]:
            return Mock(returncode=0)
        if cmd == ["xdg-terminal-exec", "--print-cmd"]:
            return Mock(returncode=0, stdout="snap\nrun\nalacritty\n")
        if cmd == ["which", "kgx"]:
            return Mock(returncode=0)
        return Mock(returncode=1)

    mock_core.host_run.side_effect = side_effect

    apps.setup(mock_core)

    assert apps.LOCAL_APPS["terminal"] == "kgx"


def test_setup_falls_back_when_spec_yields_only_env(mock_core):
    """When the spec output is only an env prefix, then setup falls back to PATH."""

    def side_effect(cmd, **kwargs):
        if cmd == ["which", "xdg-terminal-exec"]:
            return Mock(returncode=0)
        if cmd == ["xdg-terminal-exec", "--print-cmd"]:
            return Mock(returncode=0, stdout="env\nFOO=bar\n")
        if cmd == ["which", "kgx"]:
            return Mock(returncode=0)
        return Mock(returncode=1)

    mock_core.host_run.side_effect = side_effect

    apps.setup(mock_core)

    assert apps.LOCAL_APPS["terminal"] == "kgx"


def test_setup_falls_back_when_wrapper_has_no_target(mock_core):
    """When a wrapper command names no app, then setup falls back to PATH."""

    def side_effect(cmd, **kwargs):
        if cmd == ["which", "xdg-terminal-exec"]:
            return Mock(returncode=0)
        if cmd == ["xdg-terminal-exec", "--print-cmd"]:
            return Mock(returncode=0, stdout="flatpak\nrun\n--branch=stable\n")
        if cmd == ["which", "kgx"]:
            return Mock(returncode=0)
        return Mock(returncode=1)

    mock_core.host_run.side_effect = side_effect

    apps.setup(mock_core)

    assert apps.LOCAL_APPS["terminal"] == "kgx"


def test_setup_registers_terminal_via_fallback(mock_core):
    """When the spec launcher is missing, then setup registers the first terminal in PATH."""

    def side_effect(cmd, **kwargs):
        if cmd == ["which", "xdg-terminal-exec"]:
            return Mock(returncode=1)
        if cmd == ["which", "kgx"]:
            return Mock(returncode=0)
        return Mock(returncode=1)

    mock_core.host_run.side_effect = side_effect

    apps.setup(mock_core)

    assert apps.LOCAL_APPS["terminal"] == "kgx"


def test_setup_falls_back_when_spec_print_fails(mock_core):
    """When the spec launcher cannot report a command, then setup falls back to PATH."""

    def side_effect(cmd, **kwargs):
        if cmd == ["which", "xdg-terminal-exec"]:
            return Mock(returncode=0)
        if cmd == ["xdg-terminal-exec", "--print-cmd"]:
            return Mock(returncode=1, stdout="")
        if cmd == ["which", "kgx"]:
            return Mock(returncode=0)
        return Mock(returncode=1)

    mock_core.host_run.side_effect = side_effect

    apps.setup(mock_core)

    assert apps.LOCAL_APPS["terminal"] == "kgx"


def test_setup_no_terminal_not_registered(mock_core_failure):
    """When no terminal can be found, then no terminal entry is registered."""
    apps.setup(mock_core_failure)

    assert "terminal" not in apps.LOCAL_APPS


def test_launch_registered_terminal(mock_core):
    """When a registered terminal is launched, then its binary runs in the background."""
    apps.LOCAL_APPS["terminal"] = "ghostty"

    result = apps.launch_app("terminal", mock_core)

    assert result is True
    assert mock_core.host_run.call_args.args == (["ghostty"],)
    assert mock_core.host_run.call_args.kwargs == {
        "background": True,
        "clean_env": True,
    }


def test_close_registered_terminal(mock_core):
    """When a registered terminal is closed, then its binary is killed."""
    apps.LOCAL_APPS["terminal"] = "ghostty"

    result = apps.close_app("terminal", mock_core)

    assert result is True
    assert mock_core.host_run.call_args.args == (["pkill", "-f", "ghostty"],)


@patch("easyspeak.plugins.apps.launch_app", return_value=True)
@pytest.mark.parametrize(
    ["command", "app_name"],
    [
        ["open firefox", "firefox"],
        ["launch steam", "steam"],
        ["open spotify", "spotify"],
        ["open calculator", "calculator"],
        ["open music player", "music player"],
        ["open music app", "music app"],
    ],
)
def test_handle_open_installed_app(mock_launch_app, mock_core, command, app_name):
    """When open/launch command is given for installed app, then app launches and confirms."""
    result = apps.handle(command, mock_core)

    assert result is True
    assert mock_launch_app.call_args.args == (app_name, mock_core)
    assert mock_core.speak.call_args.args == (f"Opening {app_name}.",)


@patch("easyspeak.plugins.apps.launch_app", return_value=False)
@pytest.mark.parametrize(
    ["command", "app_name"],
    [
        ["open firefox", "firefox"],
        ["launch steam", "steam"],
    ],
)
def test_handle_open_not_installed_app(mock_launch_app, mock_core, command, app_name):
    """When open/launch command is given for missing app, then failure is announced."""
    result = apps.handle(command, mock_core)

    assert result is True
    assert mock_launch_app.call_args.args == (app_name, mock_core)
    assert mock_core.speak.call_args.args == (f"{app_name} not installed.",)


@patch("easyspeak.plugins.apps.close_app")
@pytest.mark.parametrize(
    ["command", "app_name"],
    [
        ["close firefox", "firefox"],
        ["close steam", "steam"],
        ["close spotify", "spotify"],
    ],
)
def test_handle_close_app(mock_close_app, mock_core, command, app_name):
    """When close command is given, then app is closed and confirms."""
    result = apps.handle(command, mock_core)

    assert result is True
    assert mock_close_app.call_args.args == (app_name, mock_core)
    assert mock_core.speak.call_args.args == (f"Closing {app_name}.",)


@pytest.mark.parametrize(
    "command",
    [
        "volume up",
        "play music",
        "shutdown",
        "random command",
    ],
)
def test_handle_unrelated_command(mock_core, command):
    """When unrelated command is given, then it is not handled."""
    result = apps.handle(command, mock_core)

    assert result is None
    assert not mock_core.speak.called
