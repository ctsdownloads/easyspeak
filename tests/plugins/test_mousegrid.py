"""Tests for the mousegrid plugin module."""

import importlib
from unittest.mock import Mock, patch

import pytest

mousegrid_plugin = importlib.import_module("easyspeak.plugins.00_mousegrid")


@pytest.fixture(autouse=True)
def reset_mousegrid_state():
    """Reset mousegrid plugin global state before and after each test."""
    # Reset to clean state before test
    mousegrid_plugin.grid_active = False
    mousegrid_plugin.grid_bounds = None
    mousegrid_plugin.screen_size = None
    mousegrid_plugin.last_bounds = None
    mousegrid_plugin.drag_start = None

    yield

    # Cleanup after test
    mousegrid_plugin.grid_active = False
    mousegrid_plugin.grid_bounds = None
    mousegrid_plugin.screen_size = None
    mousegrid_plugin.last_bounds = None
    mousegrid_plugin.drag_start = None


def test_setup(mock_core):
    """When setup is called with a core object then it stores the reference."""
    mousegrid_plugin.setup(mock_core)

    assert mousegrid_plugin.core is mock_core


@patch("subprocess.run", return_value=Mock(returncode=0, stdout="", stderr=""))
def test_host_run(mock_subprocess_run):
    """When host_run is called then it executes subprocess with capture_output and text."""
    cmd = ["test", "command"]

    result = mousegrid_plugin.host_run(cmd)

    assert mock_subprocess_run.call_args.args[0] == cmd
    assert mock_subprocess_run.call_args.kwargs["capture_output"] is True
    assert mock_subprocess_run.call_args.kwargs["text"] is True
    assert result.returncode == 0


@patch.object(mousegrid_plugin, "dbus_call", return_value=True)
def test_cleanup(mock_dbus_call):
    """When cleanup is called then it hides the grid via dbus."""
    mousegrid_plugin.cleanup()

    assert mock_dbus_call.call_args.args == ("Hide",)


@pytest.mark.parametrize(
    ["method", "args", "expected_returncode", "expected_result"],
    [
        ("Show", [1920, 1080], 0, True),
        ("Hide", [], 0, True),
        ("Update", [100, 200, 300, 400], 0, True),
        ("Click", [500, 600], 0, True),
        ("Show", [1920, 1080], 1, False),
    ],
)
@patch.object(mousegrid_plugin, "host_run")
def test_dbus_call(mock_host_run, method, args, expected_returncode, expected_result):
    """When dbus_call is invoked then it constructs gdbus command and returns success status."""
    mock_host_run.return_value = Mock(returncode=expected_returncode)

    result = mousegrid_plugin.dbus_call(method, *args)

    assert result == expected_result
    call_args = mock_host_run.call_args.args[0]
    assert call_args[0] == "gdbus"
    assert call_args[1] == "call"
    assert call_args[2] == "--session"
    assert call_args[3] == "--dest"
    assert call_args[4] == "org.gnome.Shell"
    assert call_args[5] == "--object-path"
    assert call_args[6] == "/org/easyspeak/Grid"
    assert call_args[7] == "--method"
    assert call_args[8] == f"org.easyspeak.Grid.{method}"
    assert call_args[9:] == [str(a) for a in args]


@pytest.mark.parametrize(
    ["stdout", "expected_size"],
    [
        ("((1920, 1080),)\n", (1920, 1080)),
        ("((2560, 1440),)\n", (2560, 1440)),
        ("((3840, 2160),)\n", (3840, 2160)),
        ("invalid output", (1920, 1080)),
        ("", (1920, 1080)),
    ],
)
@patch.object(mousegrid_plugin, "host_run")
def test_get_screen_size(mock_host_run, stdout, expected_size):
    """When get_screen_size is called then it parses screen dimensions from gdbus output."""
    mock_host_run.return_value = Mock(returncode=0, stdout=stdout)

    result = mousegrid_plugin.get_screen_size()

    assert result == expected_size


@patch.object(mousegrid_plugin, "host_run", return_value=Mock(returncode=1, stdout=""))
def test_get_screen_size_with_failure(mock_host_run):
    """When get_screen_size fails then it returns default dimensions."""
    result = mousegrid_plugin.get_screen_size()

    assert result == (1920, 1080)


@patch.object(mousegrid_plugin, "host_run")
def test_get_screen_size_with_fallback_to_drm(mock_host_run):
    """When get_screen_size fails to parse gdbus but finds drm modes then it parses drm output."""
    # First call (gdbus) succeeds but has invalid format, second call (drm) succeeds
    mock_host_run.side_effect = [
        Mock(returncode=0, stdout="invalid"),
        Mock(returncode=0, stdout="2560x1440@60\n1920x1080@60\n"),
    ]

    result = mousegrid_plugin.get_screen_size()

    assert result == (2560, 1440)


@pytest.mark.parametrize(
    ["text", "expected"],
    [
        ("3 7 5", [3, 7, 5]),
        ("1", [1]),
        ("9", [9]),
        ("one two three", [1, 2, 3]),
        ("four five six", [4, 5, 6]),
        ("seven eight nine", [7, 8, 9]),
        ("tree for five", [3, 4, 5]),
        ("won tu free", [1, 2, 3]),
        ("ate nein", [8, 9]),
        ("no numbers", []),
        ("0", []),
        ("zero", []),
    ],
)
def test_parse_number_sequence(text, expected):
    """When parse_number_sequence is called then it extracts zone numbers from text."""
    result = mousegrid_plugin.parse_number_sequence(text)

    assert result == expected


@pytest.mark.parametrize(
    ["text", "expected"],
    [
        ("nudge up 5", 5),
        ("scroll down 3", 3),
        ("up", 1),
        ("down seven", 7),
        ("left three", 3),
        ("no numbers", 1),
        ("twenty five", 5),
    ],
)
def test_parse_count(text, expected):
    """When parse_count is called then it extracts repeat count from text."""
    result = mousegrid_plugin.parse_count(text)

    assert result == expected


@pytest.mark.parametrize(
    ["text", "expected"],
    [
        ("nudge up", "up"),
        ("scroll down", "down"),
        ("move left", "left"),
        ("go right", "right"),
        ("north", "up"),
        ("south", "down"),
        ("west", "left"),
        ("east", "right"),
        ("no direction", None),
    ],
)
def test_parse_direction(text, expected):
    """When parse_direction is called then it extracts direction from text."""
    result = mousegrid_plugin.parse_direction(text)

    assert result == expected


def test_get_center_with_bounds():
    """When get_center is called with grid_bounds set then it returns center coordinates."""
    mousegrid_plugin.grid_bounds = (100, 200, 300, 400)

    result = mousegrid_plugin.get_center()

    assert result == (250, 400)


def test_get_center_without_bounds():
    """When get_center is called without grid_bounds then it returns None."""
    mousegrid_plugin.grid_bounds = None

    result = mousegrid_plugin.get_center()

    assert result is None


@patch.object(mousegrid_plugin, "dbus_call", return_value=True)
@patch.object(mousegrid_plugin, "get_screen_size", return_value=(1920, 1080))
def test_show_grid(mock_screen_size, mock_dbus_call, mock_core):
    """When show_grid is called then it initializes grid state and shows grid."""
    mousegrid_plugin.core = mock_core
    mousegrid_plugin.grid_active = False

    mousegrid_plugin.show_grid()

    assert mousegrid_plugin.grid_active is True
    assert mousegrid_plugin.grid_bounds == (0, 0, 1920, 1080)
    assert mousegrid_plugin.screen_size == (1920, 1080)
    assert mock_dbus_call.call_args.args == ("Show", 1920, 1080)
    assert mock_core.speak.call_args.args[0] == "Grid"


@patch.object(mousegrid_plugin, "dbus_call", return_value=True)
@patch.object(mousegrid_plugin, "get_screen_size", return_value=(1920, 1080))
def test_show_grid_when_already_active(mock_screen_size, mock_dbus_call, mock_core):
    """When show_grid is called while grid is active then it does nothing."""
    mousegrid_plugin.core = mock_core
    mousegrid_plugin.grid_active = True

    mousegrid_plugin.show_grid()

    assert not mock_dbus_call.called
    assert not mock_core.speak.called


@patch.object(mousegrid_plugin, "dbus_call", return_value=False)
@patch.object(mousegrid_plugin, "get_screen_size", return_value=(1920, 1080))
def test_show_grid_with_failure(mock_screen_size, mock_dbus_call, mock_core):
    """When show_grid fails to show grid then it does not activate grid."""
    mousegrid_plugin.core = mock_core
    mousegrid_plugin.grid_active = False

    mousegrid_plugin.show_grid()

    assert mousegrid_plugin.grid_active is False


@patch.object(mousegrid_plugin, "dbus_call", return_value=True)
def test_close_grid(mock_dbus_call):
    """When close_grid is called then it hides grid and resets state."""
    mousegrid_plugin.grid_active = True
    mousegrid_plugin.grid_bounds = (0, 0, 1920, 1080)

    mousegrid_plugin.close_grid()

    assert mousegrid_plugin.grid_active is False
    assert mousegrid_plugin.grid_bounds is None
    assert mock_dbus_call.call_args.args == ("Hide",)


@pytest.mark.parametrize(
    ["zone", "initial_bounds", "expected_bounds"],
    [
        (1, (0, 0, 1920, 1080), (0, 0, 640, 360)),
        (2, (0, 0, 1920, 1080), (640, 0, 640, 360)),
        (3, (0, 0, 1920, 1080), (1280, 0, 640, 360)),
        (4, (0, 0, 1920, 1080), (0, 360, 640, 360)),
        (5, (0, 0, 1920, 1080), (640, 360, 640, 360)),
        (6, (0, 0, 1920, 1080), (1280, 360, 640, 360)),
        (7, (0, 0, 1920, 1080), (0, 720, 640, 360)),
        (8, (0, 0, 1920, 1080), (640, 720, 640, 360)),
        (9, (0, 0, 1920, 1080), (1280, 720, 640, 360)),
    ],
)
@patch.object(mousegrid_plugin, "dbus_call", return_value=True)
def test_update_grid(mock_dbus_call, zone, initial_bounds, expected_bounds):
    """When update_grid is called with a zone then it zooms to that zone."""
    mousegrid_plugin.grid_active = True
    mousegrid_plugin.grid_bounds = initial_bounds
    mousegrid_plugin.screen_size = (1920, 1080)

    result = mousegrid_plugin.update_grid(zone)

    assert result is True
    assert mousegrid_plugin.grid_bounds == expected_bounds
    assert mock_dbus_call.call_args.args[0] == "Update"
    assert mock_dbus_call.call_args.args[1:] == expected_bounds


@patch.object(mousegrid_plugin, "dbus_call", return_value=True)
def test_update_grid_with_invalid_zone(mock_dbus_call):
    """When update_grid is called with invalid zone then it returns False."""
    mousegrid_plugin.grid_active = True
    mousegrid_plugin.grid_bounds = (0, 0, 1920, 1080)

    result = mousegrid_plugin.update_grid(0)

    assert result is False
    assert not mock_dbus_call.called


@pytest.mark.parametrize(
    ["zone", "initial_bounds", "screen_size", "expected_bounds"],
    [
        # Zone would go negative X, should clamp to 0
        (1, (-50, 0, 150, 150), (1920, 1080), (0, 0, 50, 50)),
        # Zone would go negative Y, should clamp to 0
        (1, (0, -50, 150, 150), (1920, 1080), (0, 0, 50, 50)),
        # Zone would exceed screen width, should clamp
        (3, (1800, 0, 300, 300), (1920, 1080), (1820, 0, 100, 100)),
        # Zone would exceed screen height, should clamp
        (7, (0, 980, 300, 300), (1920, 1080), (0, 980, 100, 100)),
    ],
)
@patch.object(mousegrid_plugin, "dbus_call", return_value=True)
def test_update_grid_with_clamping(
    mock_dbus_call, zone, initial_bounds, screen_size, expected_bounds
):
    """When update_grid creates bounds that go off-screen then it clamps them to screen edges."""
    mousegrid_plugin.grid_active = True
    mousegrid_plugin.grid_bounds = initial_bounds
    mousegrid_plugin.screen_size = screen_size

    result = mousegrid_plugin.update_grid(zone)

    assert result is True
    assert mousegrid_plugin.grid_bounds == expected_bounds


@patch.object(mousegrid_plugin, "dbus_call", return_value=True)
def test_update_grid_without_grid_active(mock_dbus_call):
    """When update_grid is called while grid is not active then it returns False."""
    mousegrid_plugin.grid_active = False

    result = mousegrid_plugin.update_grid(5)

    assert result is False
    assert not mock_dbus_call.called


@patch.object(mousegrid_plugin, "update_grid", return_value=True)
def test_process_zones(mock_update_grid):
    """When process_zones is called with multiple zones then it updates grid for each zone."""
    zones = [3, 7, 5]

    mousegrid_plugin.process_zones(zones)

    assert mock_update_grid.call_count == 3
    assert mock_update_grid.call_args_list[0].args == (3,)
    assert mock_update_grid.call_args_list[1].args == (7,)
    assert mock_update_grid.call_args_list[2].args == (5,)


@pytest.mark.parametrize(
    ["click_type", "expected_method"],
    [
        ("click", "Click"),
        ("double", "DoubleClick"),
        ("right", "RightClick"),
        ("middle", "MiddleClick"),
    ],
)
@patch.object(mousegrid_plugin, "dbus_call", return_value=True)
def test_do_click(mock_dbus_call, click_type, expected_method):
    """When do_click is called then it performs click at center and closes grid."""
    mousegrid_plugin.grid_active = True
    mousegrid_plugin.grid_bounds = (100, 200, 300, 400)

    result = mousegrid_plugin.do_click(click_type)

    assert result is True
    assert mousegrid_plugin.grid_active is False
    assert mousegrid_plugin.grid_bounds is None
    assert mousegrid_plugin.last_bounds == (100, 200, 300, 400)
    assert mock_dbus_call.call_args.args == (expected_method, 250, 400)


@patch.object(mousegrid_plugin, "dbus_call", return_value=True)
def test_do_click_without_bounds(mock_dbus_call):
    """When do_click is called without grid_bounds then it returns False."""
    mousegrid_plugin.grid_bounds = None

    result = mousegrid_plugin.do_click("click")

    assert result is False
    assert not mock_dbus_call.called


@pytest.mark.parametrize(
    ["direction", "count"],
    [
        ("up", 1),
        ("down", 3),
        ("left", 5),
        ("right", 2),
    ],
)
@patch.object(mousegrid_plugin, "dbus_call", return_value=True)
def test_do_scroll(mock_dbus_call, direction, count):
    """When do_scroll is called then it scrolls at center and closes grid."""
    mousegrid_plugin.grid_active = True
    mousegrid_plugin.grid_bounds = (100, 200, 300, 400)

    result = mousegrid_plugin.do_scroll(direction, count)

    assert result is True
    assert mousegrid_plugin.grid_active is False
    assert mousegrid_plugin.grid_bounds is None
    assert mousegrid_plugin.last_bounds == (100, 200, 300, 400)
    assert mock_dbus_call.call_args.args == ("Scroll", 250, 400, direction, count)


@patch.object(mousegrid_plugin, "dbus_call", return_value=True)
def test_do_scroll_without_bounds(mock_dbus_call):
    """When do_scroll is called without grid_bounds then it returns False."""
    mousegrid_plugin.grid_bounds = None

    result = mousegrid_plugin.do_scroll("down", 1)

    assert result is False
    assert not mock_dbus_call.called


@pytest.mark.parametrize(
    ["direction", "count", "initial_bounds", "expected_bounds"],
    [
        ("up", 1, (100, 100, 300, 400), (100, 80, 300, 400)),
        ("down", 1, (100, 100, 300, 400), (100, 120, 300, 400)),
        ("left", 1, (100, 100, 300, 400), (80, 100, 300, 400)),
        ("right", 1, (100, 100, 300, 400), (120, 100, 300, 400)),
        ("up", 3, (100, 100, 300, 400), (100, 40, 300, 400)),
        ("down", 2, (100, 100, 300, 400), (100, 140, 300, 400)),
    ],
)
@patch.object(mousegrid_plugin, "dbus_call", return_value=True)
def test_nudge_grid(mock_dbus_call, direction, count, initial_bounds, expected_bounds):
    """When nudge_grid is called then it moves grid in specified direction."""
    mousegrid_plugin.grid_bounds = initial_bounds
    mousegrid_plugin.screen_size = (1920, 1080)

    result = mousegrid_plugin.nudge_grid(direction, count)

    assert result is True
    assert mousegrid_plugin.grid_bounds == expected_bounds
    assert mock_dbus_call.call_args.args[0] == "Update"
    assert mock_dbus_call.call_args.args[1:] == expected_bounds


@patch.object(mousegrid_plugin, "dbus_call", return_value=True)
def test_nudge_grid_clamping_at_edges(mock_dbus_call):
    """When nudge_grid moves beyond screen edges then it clamps to screen bounds."""
    mousegrid_plugin.grid_bounds = (10, 10, 300, 400)
    mousegrid_plugin.screen_size = (1920, 1080)

    mousegrid_plugin.nudge_grid("up", 1)
    assert mousegrid_plugin.grid_bounds == (10, 0, 300, 400)

    mousegrid_plugin.grid_bounds = (10, 10, 300, 400)
    mousegrid_plugin.nudge_grid("left", 1)
    assert mousegrid_plugin.grid_bounds == (0, 10, 300, 400)


@patch.object(mousegrid_plugin, "dbus_call", return_value=True)
def test_nudge_grid_without_bounds(mock_dbus_call):
    """When nudge_grid is called without grid_bounds then it returns False."""
    mousegrid_plugin.grid_bounds = None

    result = mousegrid_plugin.nudge_grid("up", 1)

    assert result is False
    assert not mock_dbus_call.called


@patch.object(mousegrid_plugin, "dbus_call", return_value=True)
def test_start_drag(mock_dbus_call):
    """When start_drag is called then it marks drag start and resets grid to full screen."""
    mousegrid_plugin.grid_bounds = (100, 200, 300, 400)
    mousegrid_plugin.screen_size = (1920, 1080)

    result = mousegrid_plugin.start_drag()

    assert result is True
    assert mousegrid_plugin.drag_start == (250, 400)
    assert mousegrid_plugin.grid_bounds == (0, 0, 1920, 1080)
    assert mock_dbus_call.call_count == 2
    assert mock_dbus_call.call_args_list[0].args == ("StartDrag", 250, 400)
    assert mock_dbus_call.call_args_list[1].args == ("Update", 0, 0, 1920, 1080)


@patch.object(mousegrid_plugin, "dbus_call", return_value=True)
def test_start_drag_without_bounds(mock_dbus_call):
    """When start_drag is called without grid_bounds then it returns False."""
    mousegrid_plugin.grid_bounds = None

    result = mousegrid_plugin.start_drag()

    assert result is False
    assert not mock_dbus_call.called


@patch.object(mousegrid_plugin, "dbus_call", return_value=True)
def test_end_drag(mock_dbus_call):
    """When end_drag is called then it completes drag and closes grid."""
    mousegrid_plugin.drag_start = (100, 200)
    mousegrid_plugin.grid_active = True
    mousegrid_plugin.grid_bounds = (300, 400, 500, 600)

    result = mousegrid_plugin.end_drag()

    assert result is True
    assert mousegrid_plugin.drag_start is None
    assert mousegrid_plugin.grid_active is False
    assert mousegrid_plugin.grid_bounds is None
    assert mousegrid_plugin.last_bounds == (300, 400, 500, 600)
    assert mock_dbus_call.call_args.args == ("EndDrag", 550, 700)


@patch.object(mousegrid_plugin, "dbus_call", return_value=True)
def test_end_drag_without_drag_start(mock_dbus_call):
    """When end_drag is called without drag_start then it returns False."""
    mousegrid_plugin.drag_start = None
    mousegrid_plugin.grid_bounds = (300, 400, 500, 600)

    result = mousegrid_plugin.end_drag()

    assert result is False
    assert not mock_dbus_call.called


@patch.object(mousegrid_plugin, "dbus_call", return_value=True)
def test_end_drag_without_bounds(mock_dbus_call):
    """When end_drag is called without grid_bounds then it returns False."""
    mousegrid_plugin.drag_start = (100, 200)
    mousegrid_plugin.grid_bounds = None

    result = mousegrid_plugin.end_drag()

    assert result is False
    assert not mock_dbus_call.called


@pytest.mark.parametrize(
    ["command"],
    [
        ["grid"],
        ["mouse"],
        ["pointer"],
        ["grit"],
        ["grip"],
    ],
)
@patch.object(mousegrid_plugin, "listen_for_grid_commands")
@patch.object(mousegrid_plugin, "show_grid")
def test_handle_show_grid_commands(mock_show_grid, mock_listen, command, mock_core):
    """When handle receives a grid trigger command then it shows grid and listens."""
    result = mousegrid_plugin.handle(command, mock_core)

    assert result is True
    assert mock_show_grid.called
    assert mock_listen.call_args.args[0] == mock_core


@pytest.mark.parametrize(
    ["command"],
    [
        ["grid close"],
        ["grid hide"],
    ],
)
@patch.object(mousegrid_plugin, "listen_for_grid_commands")
@patch.object(mousegrid_plugin, "show_grid")
def test_handle_grid_close_commands(mock_show_grid, mock_listen, command, mock_core):
    """When handle receives a grid close command then it does not show grid."""
    result = mousegrid_plugin.handle(command, mock_core)

    assert result is None
    assert not mock_show_grid.called


@patch.object(mousegrid_plugin, "listen_for_grid_commands")
@patch.object(mousegrid_plugin, "dbus_call", return_value=True)
@patch.object(mousegrid_plugin, "get_screen_size", return_value=(1920, 1080))
def test_handle_again_command(mock_screen_size, mock_dbus_call, mock_listen, mock_core):
    """When handle receives again command then it reopens grid at last position."""
    mousegrid_plugin.last_bounds = (100, 200, 300, 400)

    result = mousegrid_plugin.handle("again", mock_core)

    assert result is True
    assert mousegrid_plugin.grid_active is True
    assert mousegrid_plugin.grid_bounds == (100, 200, 300, 400)
    assert mock_core.speak.call_args.args[0] == "Grid"
    assert mock_listen.call_args.args[0] == mock_core


@patch.object(mousegrid_plugin, "listen_for_grid_commands")
@patch.object(mousegrid_plugin, "dbus_call", return_value=True)
@patch.object(mousegrid_plugin, "get_screen_size", return_value=(1920, 1080))
def test_handle_again_command_without_last_bounds(
    mock_screen_size, mock_dbus_call, mock_listen, mock_core
):
    """When handle receives again command without last_bounds then it returns None."""
    mousegrid_plugin.last_bounds = None

    result = mousegrid_plugin.handle("again", mock_core)

    assert result is None
    assert not mock_listen.called


def test_handle_unrecognized_command(mock_core):
    """When handle receives an unrecognized command then it returns None."""
    result = mousegrid_plugin.handle("unrelated command", mock_core)

    assert result is None


@patch.object(mousegrid_plugin, "dbus_call", return_value=True)
def test_listen_for_grid_commands_close(mock_dbus_call, mock_core_factory):
    """When listen_for_grid_commands receives close command then it closes grid."""
    mock_core = mock_core_factory(
        wait_for_speech_values=[b"audio"], transcribe_values=["close"]
    )
    mousegrid_plugin.grid_active = True

    mousegrid_plugin.listen_for_grid_commands(mock_core)

    assert mousegrid_plugin.grid_active is False


@patch.object(mousegrid_plugin, "do_click", return_value=True)
def test_listen_for_grid_commands_click(mock_do_click, mock_core_factory):
    """When listen_for_grid_commands receives click then it performs click."""
    mock_core = mock_core_factory(
        wait_for_speech_values=[b"audio1", b"audio2"],
        transcribe_values=["click", "close"],
    )
    mousegrid_plugin.grid_active = True

    mousegrid_plugin.listen_for_grid_commands(mock_core)

    assert mock_do_click.call_args.args == ("click",)


@patch.object(mousegrid_plugin, "do_click", return_value=True)
def test_listen_for_grid_commands_double_click(mock_do_click, mock_core_factory):
    """When listen_for_grid_commands receives double click then it performs double click."""
    mock_core = mock_core_factory(
        wait_for_speech_values=[b"audio1", b"audio2"],
        transcribe_values=["double click", "close"],
    )
    mousegrid_plugin.grid_active = True

    mousegrid_plugin.listen_for_grid_commands(mock_core)

    assert mock_do_click.call_args.args == ("double",)


@patch.object(mousegrid_plugin, "do_click", return_value=True)
def test_listen_for_grid_commands_right_click(mock_do_click, mock_core_factory):
    """When listen_for_grid_commands receives right click then it performs right click."""
    mock_core = mock_core_factory(
        wait_for_speech_values=[b"audio1", b"audio2"],
        transcribe_values=["right click", "close"],
    )
    mousegrid_plugin.grid_active = True

    mousegrid_plugin.listen_for_grid_commands(mock_core)

    assert mock_do_click.call_args.args == ("right",)


@patch.object(mousegrid_plugin, "do_click", return_value=True)
def test_listen_for_grid_commands_middle_click(mock_do_click, mock_core_factory):
    """When listen_for_grid_commands receives middle click then it performs middle click."""
    mock_core = mock_core_factory(
        wait_for_speech_values=[b"audio1", b"audio2"],
        transcribe_values=["middle click", "close"],
    )
    mousegrid_plugin.grid_active = True

    mousegrid_plugin.listen_for_grid_commands(mock_core)

    assert mock_do_click.call_args.args == ("middle",)


@patch.object(mousegrid_plugin, "do_scroll", return_value=True)
def test_listen_for_grid_commands_scroll(mock_do_scroll, mock_core_factory):
    """When listen_for_grid_commands receives scroll then it performs scroll."""
    mock_core = mock_core_factory(
        wait_for_speech_values=[b"audio1", b"audio2"],
        transcribe_values=["scroll down 3", "close"],
    )
    mousegrid_plugin.grid_active = True

    mousegrid_plugin.listen_for_grid_commands(mock_core)

    assert mock_do_scroll.call_args.args == ("down", 3)


@patch.object(mousegrid_plugin, "process_zones")
def test_listen_for_grid_commands_scroll_without_direction(
    mock_process_zones, mock_core_factory
):
    """When listen_for_grid_commands receives scroll without valid direction then it continues listening."""
    mock_core = mock_core_factory(
        wait_for_speech_values=[b"audio1", b"audio2", b"audio3"],
        transcribe_values=["scroll", "3 5", "close"],
    )
    mousegrid_plugin.grid_active = True

    mousegrid_plugin.listen_for_grid_commands(mock_core)

    # Should have processed zones for "3 5" command after scroll failed
    assert mock_process_zones.call_args.args == ([3, 5],)


@patch.object(mousegrid_plugin, "nudge_grid", return_value=True)
def test_listen_for_grid_commands_nudge(mock_nudge_grid, mock_core_factory):
    """When listen_for_grid_commands receives nudge then it nudges grid."""
    mock_core = mock_core_factory(
        wait_for_speech_values=[b"audio1", b"audio2"],
        transcribe_values=["nudge up 5", "close"],
    )
    mousegrid_plugin.grid_active = True

    mousegrid_plugin.listen_for_grid_commands(mock_core)

    assert mock_nudge_grid.call_args.args == ("up", 5)


@patch.object(mousegrid_plugin, "process_zones")
def test_listen_for_grid_commands_zones(mock_process_zones, mock_core_factory):
    """When listen_for_grid_commands receives zone numbers then it processes zones."""
    mock_core = mock_core_factory(
        wait_for_speech_values=[b"audio1", b"audio2"],
        transcribe_values=["3 7 5", "close"],
    )
    mousegrid_plugin.grid_active = True

    mousegrid_plugin.listen_for_grid_commands(mock_core)

    assert mock_process_zones.call_args.args == ([3, 7, 5],)


@patch.object(mousegrid_plugin, "start_drag", return_value=True)
def test_listen_for_grid_commands_mark(mock_start_drag, mock_core_factory):
    """When listen_for_grid_commands receives mark then it starts drag."""
    mock_core = mock_core_factory(
        wait_for_speech_values=[b"audio1", b"audio2"],
        transcribe_values=["mark", "close"],
    )
    mousegrid_plugin.grid_active = True

    mousegrid_plugin.listen_for_grid_commands(mock_core)

    assert mock_start_drag.called


@patch.object(mousegrid_plugin, "end_drag", return_value=True)
def test_listen_for_grid_commands_drag(mock_end_drag, mock_core_factory):
    """When listen_for_grid_commands receives drag then it ends drag."""
    mock_core = mock_core_factory(
        wait_for_speech_values=[b"audio"], transcribe_values=["drag"]
    )
    mousegrid_plugin.grid_active = True
    mousegrid_plugin.drag_start = (100, 200)

    mousegrid_plugin.listen_for_grid_commands(mock_core)

    assert mock_end_drag.called


def test_listen_for_grid_commands_timeout(mock_core_factory):
    """When listen_for_grid_commands times out waiting then it continues loop."""
    mock_core = mock_core_factory(
        wait_for_speech_values=[None, b"audio"], transcribe_values=["close"]
    )
    mousegrid_plugin.grid_active = True

    mousegrid_plugin.listen_for_grid_commands(mock_core)

    assert mock_core.wait_for_speech.call_count == 2


def test_listen_for_grid_commands_empty_transcription(mock_core_factory):
    """When listen_for_grid_commands receives empty transcription then it continues loop."""
    mock_core = mock_core_factory(
        wait_for_speech_values=[b"audio1", b"audio2"],
        transcribe_values=["", "close"],
    )
    mousegrid_plugin.grid_active = True

    mousegrid_plugin.listen_for_grid_commands(mock_core)

    assert mock_core.transcribe.call_count == 2


def test_listen_for_grid_commands_stream_read_exception(mock_core_factory):
    """When listen_for_grid_commands encounters stream read exception then it continues."""
    mock_core = mock_core_factory(
        wait_for_speech_values=[b"audio"], transcribe_values=["close"]
    )
    mock_core.stream.read.side_effect = Exception("Stream error")
    mousegrid_plugin.grid_active = True

    mousegrid_plugin.listen_for_grid_commands(mock_core)

    assert mousegrid_plugin.grid_active is False


@pytest.mark.parametrize(
    ["exit_command"],
    [
        ["close"],
        ["cancel"],
        ["escape"],
        ["exit"],
        ["hide"],
        ["stop"],
        ["done"],
        ["quit"],
    ],
)
def test_listen_for_grid_commands_exit_commands(exit_command, mock_core_factory):
    """When listen_for_grid_commands receives exit commands then it closes grid."""
    mock_core = mock_core_factory(
        wait_for_speech_values=[b"audio"], transcribe_values=[exit_command]
    )
    mousegrid_plugin.grid_active = True

    mousegrid_plugin.listen_for_grid_commands(mock_core)

    assert mousegrid_plugin.grid_active is False
