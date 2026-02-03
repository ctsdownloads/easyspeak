"""Tests for the zz_base plugin module."""

from unittest.mock import Mock, patch

import pytest
from easyspeak.plugins import zz_base


def test_setup(mock_core):
    """When setup is called with a core object then it stores the reference."""
    zz_base.setup(mock_core)

    assert zz_base.core is mock_core


@pytest.mark.parametrize(
    ["command", "expected_return"],
    [
        ["stop", False],
        ["exit", False],
        ["quit", False],
        ["goodbye", False],
        ["bye", False],
        ["STOP", False],
        ["EXIT", False],
        ["QUIT", False],
    ],
)
def test_handle_exit_commands(mock_core, command, expected_return):
    """When handle receives exit commands then it speaks goodbye and returns False."""
    result = zz_base.handle(command, mock_core)

    assert result == expected_return
    assert mock_core.speak.call_args.args[0] == "Goodbye."


@pytest.mark.parametrize(
    ["command", "expected_return"],
    [
        ["jarvis stop", False],
        ["jarvis exit", False],
        ["jarvis quit", False],
        ["computer stop", False],
        ["computer exit", False],
        ["hey stop", False],
    ],
)
def test_handle_exit_commands_with_prefix(mock_core, command, expected_return):
    """When handle receives exit commands with prefix then it speaks goodbye and returns False."""
    result = zz_base.handle(command, mock_core)

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
    result = zz_base.handle(command, mock_core)

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
@patch.object(zz_base, "show_help")
def test_handle_help_commands(mock_show_help, mock_core, command, expected_return):
    """When handle receives help commands then it calls show_help and returns True."""
    result = zz_base.handle(command, mock_core)

    assert result == expected_return
    assert mock_show_help.call_args.args[0] == mock_core


@pytest.mark.parametrize(
    ["command"],
    [
        ["open firefox"],
        ["volume up"],
        ["grid"],
        ["some random command"],
    ],
)
def test_handle_unrecognized_commands(mock_core, command):
    """When handle receives unrecognized commands then it returns None."""
    result = zz_base.handle(command, mock_core)

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

    zz_base.show_help(mock_core)

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

    zz_base.show_help(mock_core)

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

    zz_base.show_help(mock_core)

    assert (
        mock_core.speak.call_args.args[0]
        == "Check the terminal for available commands."
    )
    # Should not crash and should print header
    print_calls = [
        call.args[0] if call.args else "" for call in mock_print.call_args_list
    ]
    assert "\n=== Available Commands ===" in print_calls
