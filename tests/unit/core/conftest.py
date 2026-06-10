"""Pytest fixtures for core module tests."""

from unittest.mock import Mock

import pytest


def create_mock_plugin(name="TestPlugin", **kwargs) -> Mock:
    """
    Factory function to create mock plugin objects.

    Args:
        name: Plugin name (default: "TestPlugin")
        **kwargs: Additional attributes to set on the plugin
            - commands: List of commands to set as COMMANDS attribute
            - handle_side_effect: Side effect for handle method
            - handle_return: Return value for handle method
            - Any other attributes will be set directly on the plugin
    """
    plugin = Mock()
    plugin.NAME = name

    if "commands" in kwargs:
        plugin.COMMANDS = kwargs.pop("commands")

    plugin.handle = (
        Mock(side_effect=kwargs.pop("handle_side_effect"))
        if "handle_side_effect" in kwargs
        else Mock(return_value=kwargs.pop("handle_return"))
        if "handle_return" in kwargs
        else Mock()
    )

    for key, val in kwargs.items():
        setattr(plugin, key, val)

    return plugin


@pytest.fixture
def mock_plugin():
    """Create a mock plugin with name 'TestPlugin' that handles commands."""
    return create_mock_plugin(handle_return=True)


@pytest.fixture
def mock_plugin_with_setup():
    """Create a mock plugin with name 'TestPlugin' that has a setup method."""
    return create_mock_plugin(setup=Mock())


@pytest.fixture
def mock_plugin_no_handle():
    """Create a mock plugin that doesn't handle commands (returns None)."""
    return create_mock_plugin(handle_return=None)


@pytest.fixture
def mock_plugin_exit():
    """Create a mock plugin that signals exit (returns False)."""
    return create_mock_plugin(handle_return=False)


@pytest.fixture
def mock_plugin_with_commands_12():
    """Create a mock plugin with COMMANDS attribute containing cmd1 and cmd2."""
    return create_mock_plugin(commands=["cmd1", "cmd2"], handle_return=True)


@pytest.fixture
def mock_plugin_with_commands_34():
    """Create a mock plugin with COMMANDS attribute containing cmd3 and cmd4."""
    return create_mock_plugin(commands=["cmd3", "cmd4"], handle_return=True)


@pytest.fixture
def mock_plugin_without_commands():
    """Create a mock plugin without COMMANDS attribute."""
    return Mock(spec=[])


@pytest.fixture
def mock_multiple_plugins():
    """Create multiple mock plugins for testing plugin routing."""
    return [
        create_mock_plugin(name="Plugin1", handle_return=None),
        create_mock_plugin(name="Plugin2", handle_return=True),
    ]


@pytest.fixture
def mock_plugin_with_error():
    """Create a mock plugin that raises an exception."""
    return create_mock_plugin(handle_side_effect=ValueError("Test error"))
