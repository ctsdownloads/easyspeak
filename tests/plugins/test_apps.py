"""Tests for the apps plugin module."""

from unittest.mock import patch

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
        ["files", "nautilus"],
        ["terminal", "gnome-terminal"],
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
    assert mock_core.host_run.call_args.kwargs == {"background": True}


@patch("easyspeak.plugins.apps.find_app", return_value=("local", "nautilus"))
def test_launch_app_local(mock_find_app, mock_core):
    """When local app is launched, then it runs directly."""
    app_name = "files"

    result = apps.launch_app(app_name, mock_core)

    assert result is True
    assert mock_find_app.call_args.args == (app_name, mock_core)
    assert mock_core.host_run.call_args.args == (["nautilus"],)
    assert mock_core.host_run.call_args.kwargs == {"background": True}


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


@patch("easyspeak.plugins.apps.launch_app", return_value=True)
@pytest.mark.parametrize(
    ["command", "app_name"],
    [
        ["open firefox", "firefox"],
        ["launch steam", "steam"],
        ["open spotify", "spotify"],
        ["launch files", "files"],
        ["open calculator", "calculator"],
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
        ["close files", "files"],
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
