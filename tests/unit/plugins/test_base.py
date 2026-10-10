"""Tests for the base plugin module."""

import importlib
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from easyspeak.core.main import EasySpeak
from easyspeak.plugins import base


def test_setup(mock_core):
    """When setup is called with a core object then it stores the reference."""
    base.setup(mock_core)

    assert base.core is mock_core


@pytest.mark.parametrize(
    ["command", "expected_return"],
    [
        ["exit", False],
        ["quit", False],
        ["goodbye", False],
        ["bye", False],
        ["EXIT", False],
        ["QUIT", False],
        ["exit the application", False],
        ["please stop the application", False],
        ["close the app", False],
        ["quit easyspeak", False],
        ["stop easy speak", False],
        ["exit easy speak", False],
    ],
)
def test_handle_exit_commands(mock_core, command, expected_return):
    """When handle receives exit commands then it speaks goodbye and returns False."""
    result = base.handle(command, mock_core)

    assert result == expected_return
    assert mock_core.speak.call_args.args[0] == "Goodbye."


@pytest.mark.parametrize(
    ["command", "expected_return"],
    [
        ["jarvis exit", False],
        ["jarvis quit", False],
        ["computer exit", False],
        ["computer quit", False],
    ],
)
def test_handle_exit_commands_with_prefix(mock_core, command, expected_return):
    """When handle receives exit commands with prefix then it speaks goodbye and returns False."""
    result = base.handle(command, mock_core)

    assert result == expected_return
    assert mock_core.speak.call_args.args[0] == "Goodbye."


@pytest.mark.parametrize(
    ["command"],
    [
        ["stop tracking"],
        ["stop eyetracking"],
        ["stop the tracking"],
        ["please stop tracking now"],
        ["STOP TRACKING"],
    ],
)
def test_handle_stop_tracking_commands_not_exit(mock_core, command):
    """When handle receives stop tracking commands then it does not exit."""
    result = base.handle(command, mock_core)

    assert result is None
    assert not mock_core.speak.called


@pytest.mark.parametrize(
    ["command", "expected_return"],
    [
        ["help", True],
        ["HELP", True],
        ["Help", True],
        ["what can you do", True],
        ["what can you do for me", True],
    ],
)
@patch.object(base, "show_help")
def test_handle_help_commands(mock_show_help, mock_core, command, expected_return):
    """When handle receives help commands then it calls show_help and returns True."""
    result = base.handle(command, mock_core)

    assert result == expected_return
    assert mock_show_help.call_args.args[0] == mock_core


@pytest.mark.parametrize(
    "command",
    [
        "open the about dialog",
        "Open the About box",
        "about easyspeak",
        "jarvis about easy speak",
        "please show the about box",
        "open the about dialogue",
        "show me the about window",
    ],
)
def test_handle_about_commands(mock_core, command):
    """An About request confirms out loud and opens the About dialog."""
    assert base.handle(command, mock_core) is True
    mock_core.speak.assert_called_once_with("Opening the About dialog.")
    mock_core.tray.open_about.assert_called_once()


@pytest.mark.parametrize(
    ["command"],
    [
        ["open firefox"],
        ["volume up"],
        ["grid"],
        ["some random command"],
        ["stop"],
        ["jarvis stop"],
    ],
)
def test_handle_unrecognized_commands(mock_core, command):
    """When handle receives unrecognized commands then it returns None."""
    result = base.handle(command, mock_core)

    assert result is None
    assert not mock_core.speak.called


@patch("builtins.print")
def test_show_help_with_multiple_plugins(mock_print, mock_core):
    """When show_help is called with multiple plugins then it prints all commands."""
    plugin1 = Mock()
    plugin1.NAME = "test_plugin"
    plugin1.COMMANDS = ["command1 - does thing 1", "command2 - does thing 2"]

    plugin2 = Mock()
    plugin2.NAME = "another_plugin"
    plugin2.COMMANDS = ["command3 - does thing 3"]

    plugin3 = Mock()
    # Plugin without COMMANDS attribute
    del plugin3.COMMANDS

    mock_core.plugins = [plugin1, plugin2, plugin3]

    base.show_help(mock_core)

    assert (
        mock_core.speak.call_args.args[0]
        == "Check the terminal for available commands."
    )
    # Verify print was called with expected content
    print_calls = [
        call.args[0] if call.args else "" for call in mock_print.call_args_list
    ]
    assert "\n=== Available Commands ===" in print_calls
    assert "\ntest_plugin:" in print_calls
    assert "  • command1 - does thing 1" in print_calls
    assert "  • command2 - does thing 2" in print_calls
    assert "\nanother_plugin:" in print_calls
    assert "  • command3 - does thing 3" in print_calls


@patch("builtins.print")
def test_show_help_with_no_plugins(mock_print, mock_core):
    """When show_help is called with no plugins then it prints header and footer."""
    mock_core.plugins = []

    base.show_help(mock_core)

    assert (
        mock_core.speak.call_args.args[0]
        == "Check the terminal for available commands."
    )
    print_calls = [
        call.args[0] if call.args else "" for call in mock_print.call_args_list
    ]
    assert "\n=== Available Commands ===" in print_calls


@patch("builtins.print")
def test_show_help_with_plugins_without_commands_attribute(mock_print, mock_core):
    """When show_help is called with plugins lacking COMMANDS then it skips them."""
    plugin = Mock(spec=[])  # Mock with no attributes
    mock_core.plugins = [plugin]

    base.show_help(mock_core)

    assert (
        mock_core.speak.call_args.args[0]
        == "Check the terminal for available commands."
    )
    # Should not crash and should print header
    print_calls = [
        call.args[0] if call.args else "" for call in mock_print.call_args_list
    ]
    assert "\n=== Available Commands ===" in print_calls


@pytest.mark.parametrize(
    ["command", "expected"],
    [
        ("require wake word", True),
        ("require the wake word", True),
        ("free listening", False),
        ("stop requiring wake word", False),
    ],
)
def test_wake_word_requirement_toggle(command, expected, mock_core):
    """The requirement can be turned on and off by voice, in any mode."""
    assert base.handle(command, mock_core) is True
    assert mock_core.require_wake_word is expected


@pytest.fixture
def routed_core(monkeypatch):
    """An EasySpeak core routing through every real plugin, in load order.

    Plugins are sorted as `load_plugins` sorts them, so base runs last as in
    the app; their `setup` hooks, which touch the system, are left out, and
    commands the plugins run report failure.
    """
    plugins_dir = Path(base.__file__).parent.parent
    plugins = []
    for package in sorted(plugins_dir.iterdir()):
        if package.name.startswith("_") or not (package / "__init__.py").is_file():
            continue
        module = importlib.import_module(f"easyspeak.plugins.{package.name}")
        if hasattr(module, "NAME") and hasattr(module, "handle"):
            plugins.append(module)
    plugins.sort(key=lambda m: (getattr(m, "PRIORITY", 50), m.NAME))

    core = EasySpeak()
    core.plugins = plugins
    failed = Mock(returncode=1, stdout="", stderr="")
    monkeypatch.setattr(core, "host_run", Mock(return_value=failed))
    monkeypatch.setattr(core, "speak", Mock())
    monkeypatch.setattr(core, "listen_modal", Mock(return_value=iter(())))
    for module in plugins:
        monkeypatch.setattr(module, "core", core, raising=False)
    return core


@pytest.mark.parametrize(
    "command",
    [
        "exit the application",
        "please quit the application",
        "close the application",
        "stop the application",
        "close the app",
        "quit easyspeak",
        "close easyspeak",
        "stop easy speak",
        "exit easy speak",
    ],
)
def test_quit_phrases_reach_base_through_routing(routed_core, command):
    """No plugin routed before base claims a quit phrase, so EasySpeak exits."""
    assert routed_core.route_command(command) is False


@pytest.mark.parametrize("command", ["quit tracking", "close files", "stop the music"])
def test_other_commands_with_quit_words_dont_exit(routed_core, command):
    """Commands that merely contain a quit word stay with their own plugin."""
    assert routed_core.route_command(command) is True
    assert routed_core.unrecognized is False
    replies = [c.args[0] for c in routed_core.speak.call_args_list]
    assert "Sorry, something went wrong with that command." not in replies
