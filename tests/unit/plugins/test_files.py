"""Tests for the files plugin module."""

from unittest.mock import Mock, patch

import pytest
from easyspeak.plugins import files


def test_setup_stores_core_reference(mock_core):
    """When setup is called with a core object then it stores the reference."""
    files.setup(mock_core)

    assert files.core == mock_core


@patch("easyspeak.plugins.files.Path")
def test_open_folder_expands_path(mock_path, mock_core):
    """When open_folder is used with a user path then it expands the path."""
    files.open_folder("~/Documents", mock_core)

    mock_path.assert_called_once_with("~/Documents")
    mock_path.return_value.expanduser.assert_called_once_with()


@patch("easyspeak.plugins.files.Path")
def test_open_folder_uses_xdg_open(mock_path, mock_core_which_finds_file_manager):
    """When xdg-open is available then open_folder launches it with a clean env."""
    mock_path.return_value.expanduser.return_value = "/home/user/Documents"
    core = mock_core_which_finds_file_manager("xdg-open")

    result = files.open_folder("~/Documents", core)

    assert result is True
    launch = core.host_run.call_args_list[-1]
    assert launch.args[0] == ["xdg-open", "/home/user/Documents"]
    assert launch.kwargs["background"] is True
    assert launch.kwargs["clean_env"] is True


def test_open_folder_returns_false_when_no_file_manager_found(
    mock_core_no_file_manager,
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
        ("open projects", "projects", "Opening projects."),
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
    "command",
    [
        "open files",
        "open file manager",
        "show file browser",
    ],
)
@patch("easyspeak.plugins.files.open_folder", return_value=True)
def test_handle_opens_default_file_manager(mock_open_folder, command, mock_core):
    """When asked for the file manager then handle opens it at home and speaks."""
    result = files.handle(command, mock_core)

    assert result is True
    assert mock_open_folder.call_args.args == ("~", mock_core)
    assert mock_core.speak.call_args.args == ("Opening files.",)


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


@pytest.fixture
def xdg(tmp_path, monkeypatch, mock_core):
    """XDG data dirs under tmp_path, with xdg-mime naming "manager.desktop"."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_DATA_DIRS", f"{tmp_path / 'missing'}:{tmp_path / 'system'}")
    mock_core.host_run.return_value = Mock(returncode=0, stdout="manager.desktop\n")
    return tmp_path


def _entry(directory, exec_line):
    apps = directory / "applications"
    apps.mkdir(parents=True)
    (apps / "manager.desktop").write_text(f"[Desktop Entry]\n{exec_line}\n")


def test_default_file_manager_is_found_in_a_later_data_dir(xdg, mock_core):
    """Data dirs without the entry are skipped until one has it."""
    _entry(xdg / "system", "Exec=/usr/bin/thunar %U")

    assert files.default_file_manager(mock_core) == "thunar"


def test_default_file_manager_with_an_empty_exec_line_is_unknown(xdg, mock_core):
    """An entry that runs nothing names nothing."""
    _entry(xdg / "home", "Exec=")

    assert files.default_file_manager(mock_core) is None


def test_default_file_manager_without_an_entry_is_unknown(xdg, mock_core):
    """xdg-mime names an entry no data dir has."""
    assert files.default_file_manager(mock_core) is None
