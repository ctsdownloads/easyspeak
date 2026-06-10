"""Tests for the files plugin module."""

from unittest.mock import patch

import pytest
from easyspeak.plugins import files


def test_setup_stores_core_reference(mock_core):
    """When setup is called with a core object then it stores the reference."""
    files.setup(mock_core)

    assert files.core == mock_core


@patch(
    "easyspeak.plugins.files.os.path.expanduser", return_value="/home/user/Documents"
)
def test_open_folder_expands_path(mock_expanduser, mock_core):
    """When open_folder is used with a user path then it expands the path."""
    files.open_folder("~/Documents", mock_core)

    assert mock_expanduser.call_count == 1
    assert mock_expanduser.call_args.args == ("~/Documents",)


@pytest.mark.parametrize(
    ["file_manager", "expected_args"],
    [
        ("nautilus", ["/home/user/Documents"]),
        ("dolphin", ["/home/user/Documents"]),
        ("thunar", ["/home/user/Documents"]),
        ("nemo", ["/home/user/Documents"]),
        ("xdg-open", ["/home/user/Documents"]),
    ],
)
@patch(
    "easyspeak.plugins.files.os.path.expanduser", return_value="/home/user/Documents"
)
def test_open_folder_tries_file_managers(
    mock_expanduser, file_manager, expected_args, mock_core_which_finds_file_manager
):
    """When a file manager is available then open_folder uses it to open the folder."""
    core = mock_core_which_finds_file_manager(file_manager)

    result = files.open_folder("~/Documents", core)

    assert result is True
    found_call = False
    for call in core.host_run.call_args_list:
        cmd_args = call.args[0]
        if cmd_args[0] == file_manager:
            found_call = True
            assert cmd_args == [file_manager, *expected_args]
            assert call.kwargs["background"] is True
            break
    assert found_call


@patch(
    "easyspeak.plugins.files.os.path.expanduser", return_value="/home/user/Documents"
)
def test_open_folder_returns_false_when_no_file_manager_found(
    mock_expanduser, mock_core_no_file_manager
):
    """When no file manager is available then open_folder returns False."""
    result = files.open_folder("~/Documents", mock_core_no_file_manager)

    assert result is False


@pytest.mark.parametrize(
    ["command", "folder_name", "expected_message"],
    [
        ("open documents", "documents", "Opening documents."),
        ("open downloads", "downloads", "Opening downloads."),
        ("open pictures", "pictures", "Opening pictures."),
        ("open music", "music", "Opening music."),
        ("open videos", "videos", "Opening videos."),
        ("open home", "home", "Opening home."),
        ("open desktop", "desktop", "Opening desktop."),
    ],
)
@patch("easyspeak.plugins.files.open_folder", return_value=True)
def test_handle_open_command_with_folders(
    mock_open_folder, command, folder_name, expected_message, mock_core
):
    """When handle receives a folder command then it opens the folder and speaks."""
    result = files.handle(command, mock_core)

    assert result is True
    assert mock_open_folder.call_count == 1
    assert mock_open_folder.call_args.args == (files.FOLDERS[folder_name], mock_core)
    assert mock_core.speak.call_count == 1
    assert mock_core.speak.call_args.args == (expected_message,)


@pytest.mark.parametrize(
    ["command_prefix"],
    [
        ("open",),
        ("go to",),
        ("show",),
        ("browse",),
    ],
)
@patch("easyspeak.plugins.files.open_folder", return_value=True)
def test_handle_recognizes_different_command_prefixes(
    mock_open_folder, command_prefix, mock_core
):
    """When handle receives commands with different prefixes then it recognizes them."""
    command = f"{command_prefix} documents"

    result = files.handle(command, mock_core)

    assert result is True
    assert mock_open_folder.call_count == 1


@patch("easyspeak.plugins.files.open_folder", return_value=False)
def test_handle_speaks_error_when_no_file_manager_found(mock_open_folder, mock_core):
    """When no file manager is found then handle speaks an error message."""
    result = files.handle("open documents", mock_core)

    assert result is True
    assert mock_core.speak.call_count == 1
    assert mock_core.speak.call_args.args == ("No file manager found.",)


@pytest.mark.parametrize(
    ["command"],
    [
        ("hello world",),
        ("what time is it",),
        ("play music",),
        ("close window",),
        ("unrelated command",),
    ],
)
@patch("easyspeak.plugins.files.open_folder")
def test_handle_returns_none_for_unrelated_commands(
    mock_open_folder, command, mock_core
):
    """When handle receives unrelated commands then it returns None."""
    result = files.handle(command, mock_core)

    assert result is None
    assert not mock_open_folder.called


@patch("easyspeak.plugins.files.open_folder")
def test_handle_requires_both_folder_and_action_keywords(mock_open_folder, mock_core):
    """When handle receives incomplete commands then it returns None."""
    result1 = files.handle("documents", mock_core)
    result2 = files.handle("open something else", mock_core)

    assert result1 is None
    assert result2 is None
    assert not mock_open_folder.called
