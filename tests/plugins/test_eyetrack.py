"""Tests for the eyetrack (head tracking) plugin module."""

import importlib
import time
from unittest.mock import Mock, patch

import pytest

eyetrack_plugin = importlib.import_module("easyspeak.plugins.00_eyetrack")


@pytest.fixture(autouse=True)
def reset_eyetrack_state():
    """Reset eyetrack plugin global state before and after each test."""
    # Reset to clean state before test
    eyetrack_plugin.tracking_active = False
    eyetrack_plugin.frozen = False
    eyetrack_plugin.stop_event.clear()

    yield

    # Cleanup after test
    eyetrack_plugin.tracking_active = False
    eyetrack_plugin.frozen = False
    eyetrack_plugin.stop_event.set()
    if eyetrack_plugin.tracking_thread is not None:
        time.sleep(0.1)  # Give thread time to stop


def test_setup(mock_core):
    """When setup is called with a core object then it stores the reference."""
    eyetrack_plugin.setup(mock_core)

    assert eyetrack_plugin.core is mock_core


@patch("subprocess.run", return_value=Mock(returncode=0, stdout="", stderr=""))
def test_host_run(mock_subprocess_run):
    """When host_run is called then it executes subprocess with capture_output and text."""
    cmd = ["test", "command"]

    result = eyetrack_plugin.host_run(cmd)

    assert mock_subprocess_run.call_args.args[0] == cmd
    assert mock_subprocess_run.call_args.kwargs["capture_output"] is True
    assert mock_subprocess_run.call_args.kwargs["text"] is True
    assert result.returncode == 0


@pytest.mark.parametrize(
    ["method", "args", "expected_returncode", "expected_result"],
    [
        ("MoveTo", [100, 200], 0, True),
        ("Click", [100, 200], 0, True),
        ("DoubleClick", [100, 200], 0, True),
        ("RightClick", [100, 200], 0, True),
        ("MoveTo", [100, 200], 1, False),
    ],
)
@patch.object(eyetrack_plugin, "host_run")
def test_dbus_call(mock_host_run, method, args, expected_returncode, expected_result):
    """When dbus_call is invoked then it constructs gdbus command and returns success status."""
    mock_host_run.return_value = Mock(returncode=expected_returncode)

    result = eyetrack_plugin.dbus_call(method, *args)

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
        ("(1920, 1080)\n", (1920, 1080)),
        ("(2560, 1440)\n", (2560, 1440)),
        ("(3840, 2160)\n", (3840, 2160)),
        ("invalid output", (1920, 1080)),
        ("", (1920, 1080)),
    ],
)
@patch.object(eyetrack_plugin, "host_run")
def test_get_screen_size(mock_host_run, stdout, expected_size):
    """When get_screen_size is called then it parses screen dimensions from gdbus output."""
    mock_host_run.return_value = Mock(returncode=0, stdout=stdout)

    result = eyetrack_plugin.get_screen_size()

    assert result == expected_size
    call_args = mock_host_run.call_args.args[0]
    assert call_args[0] == "gdbus"
    assert call_args[4] == "org.gnome.Shell"
    assert call_args[6] == "/org/easyspeak/Grid"
    assert call_args[8] == "org.easyspeak.Grid.GetScreenSize"


@patch.object(eyetrack_plugin, "host_run", return_value=Mock(returncode=1, stdout=""))
def test_get_screen_size_with_failure(mock_host_run):
    """When get_screen_size fails then it returns default dimensions."""
    result = eyetrack_plugin.get_screen_size()

    assert result == (1920, 1080)


def test_start_tracking_when_already_active():
    """When start_tracking is called while tracking is active then it returns failure."""
    eyetrack_plugin.tracking_active = True

    success, msg = eyetrack_plugin.start_tracking()

    assert success is False
    assert msg == "Already tracking"


@patch.object(eyetrack_plugin, "run_tracking")
def test_start_tracking_when_inactive(mock_run_tracking):
    """When start_tracking is called while inactive then it starts tracking thread."""
    eyetrack_plugin.tracking_active = False
    eyetrack_plugin.frozen = True

    success, msg = eyetrack_plugin.start_tracking()

    assert success is True
    assert msg == "Tracking"
    assert eyetrack_plugin.frozen is False
    assert eyetrack_plugin.tracking_active is True
    assert eyetrack_plugin.stop_event.is_set() is False
    assert eyetrack_plugin.tracking_thread is not None
    assert eyetrack_plugin.tracking_thread.daemon is True


def test_stop_tracking():
    """When stop_tracking is called then it signals thread to stop and sets tracking_active to False."""
    eyetrack_plugin.tracking_active = True
    eyetrack_plugin.stop_event.clear()

    success, msg = eyetrack_plugin.stop_tracking()

    assert success is True
    assert msg == "Stopped"
    assert eyetrack_plugin.tracking_active is False
    assert eyetrack_plugin.stop_event.is_set() is True


@patch.object(eyetrack_plugin, "start_tracking", return_value=(True, "Tracking"))
@patch.object(eyetrack_plugin, "stop_tracking", return_value=(True, "Stopped"))
def test_recalibrate_when_tracking(mock_stop, mock_start):
    """When recalibrate is called during tracking then it restarts tracking."""
    eyetrack_plugin.tracking_active = True

    success, msg = eyetrack_plugin.recalibrate()

    assert success is True
    assert msg == "Recalibrating"
    assert mock_stop.called
    assert mock_start.called


def test_recalibrate_when_not_tracking():
    """When recalibrate is called while not tracking then it returns failure."""
    eyetrack_plugin.tracking_active = False

    success, msg = eyetrack_plugin.recalibrate()

    assert success is False
    assert msg == "Not tracking"


@pytest.mark.parametrize(
    ["command"],
    [
        ["start tracking"],
        ["begin tracking"],
        ["enable tracking"],
    ],
)
@patch.object(eyetrack_plugin, "listen_for_tracking_commands")
@patch.object(eyetrack_plugin, "start_tracking", return_value=(True, "Tracking"))
def test_handle_start_tracking_commands(mock_start, mock_listen, command, mock_core):
    """When handle receives a start tracking command then it starts tracking and listens."""
    result = eyetrack_plugin.handle(command, mock_core)

    assert result is True
    assert mock_start.called
    assert mock_core.speak.call_args.args[0] == "Tracking"
    assert mock_listen.call_args.args[0] == mock_core


@pytest.mark.parametrize(
    ["command"],
    [
        ["stop tracking"],
        ["end tracking"],
        ["close tracking"],
        ["quit tracking"],
        ["disable tracking"],
        ["tracking off"],
        ["stop track"],
    ],
)
@patch.object(eyetrack_plugin, "stop_tracking", return_value=(True, "Stopped"))
def test_handle_stop_tracking_commands(mock_stop, command, mock_core):
    """When handle receives a stop tracking command then it stops tracking."""
    result = eyetrack_plugin.handle(command, mock_core)

    assert result is True
    assert mock_stop.called
    assert mock_core.speak.call_args.args[0] == "Stopped"


@pytest.mark.parametrize(
    ["command"],
    [
        ["recalibrate"],
        ["calibrate"],
    ],
)
@patch.object(eyetrack_plugin, "recalibrate", return_value=(True, "Recalibrating"))
def test_handle_recalibrate_commands(mock_recalibrate, command, mock_core):
    """When handle receives a recalibrate command then it recalibrates."""
    result = eyetrack_plugin.handle(command, mock_core)

    assert result is True
    assert mock_recalibrate.called
    assert mock_core.speak.call_args.args[0] == "Recalibrating"


def test_handle_unrecognized_command(mock_core):
    """When handle receives an unrecognized command then it returns None."""
    result = eyetrack_plugin.handle("unrelated command", mock_core)

    assert result is None
    assert not mock_core.speak.called


@patch.object(
    eyetrack_plugin, "start_tracking", return_value=(False, "Already tracking")
)
def test_handle_start_tracking_when_already_active(mock_start, mock_core):
    """When handle receives start tracking while already active then it does not call listen."""
    with patch.object(eyetrack_plugin, "listen_for_tracking_commands") as mock_listen:
        result = eyetrack_plugin.handle("start tracking", mock_core)

        assert result is True
        assert mock_start.called
        assert mock_core.speak.call_args.args[0] == "Already tracking"
        assert not mock_listen.called


def test_one_euro_filter_first_call_returns_input():
    """When filter is called first time then it returns input value unchanged."""
    filter_obj = eyetrack_plugin.OneEuroFilter()

    result = filter_obj(10.0)

    assert result == 10.0
    assert filter_obj.x_prev == 10.0


def test_one_euro_filter_smoothing_with_constant_input():
    """When filter receives constant input then it smooths toward that value."""
    filter_obj = eyetrack_plugin.OneEuroFilter()

    filter_obj(0.0)
    result = filter_obj(10.0)

    assert result < 10.0
    assert result > 0.0


def test_one_euro_filter_multiple_calls_converge():
    """When filter receives same value repeatedly then output converges to input."""
    filter_obj = eyetrack_plugin.OneEuroFilter()

    filter_obj(0.0)
    for _ in range(100):
        result = filter_obj(10.0)

    assert abs(result - 10.0) < 0.1


def test_one_euro_filter_alpha_calculation():
    """When _alpha is called then it calculates exponential smoothing factor."""
    filter_obj = eyetrack_plugin.OneEuroFilter(freq=30.0)

    alpha = filter_obj._alpha(1.0)

    assert 0.0 < alpha < 1.0


def test_one_euro_filter_derivative_tracking():
    """When filter processes values then it tracks derivative for adaptive cutoff."""
    filter_obj = eyetrack_plugin.OneEuroFilter()

    filter_obj(0.0)
    filter_obj(1.0)

    assert filter_obj.dx_prev != 0.0


def test_one_euro_filter_custom_parameters():
    """When filter is created with custom parameters then they are stored."""
    filter_obj = eyetrack_plugin.OneEuroFilter(
        freq=60.0, min_cutoff=2.0, beta=0.01, d_cutoff=2.0
    )

    assert filter_obj.freq == 60.0
    assert filter_obj.min_cutoff == 2.0
    assert filter_obj.beta == 0.01
    assert filter_obj.d_cutoff == 2.0


@patch.object(eyetrack_plugin, "get_screen_size", return_value=(1920, 1080))
@patch.object(eyetrack_plugin, "dbus_call", return_value=True)
def test_listen_for_tracking_commands_stops_on_stop_command(
    mock_dbus, mock_screen_size, mock_core
):
    """When listen_for_tracking_commands receives stop then it exits loop."""
    eyetrack_plugin.tracking_active = True
    mock_core.wait_for_speech.return_value = b"audio"
    mock_core.record_until_silence.return_value = b"more_audio"
    mock_core.transcribe.return_value = "stop tracking"

    eyetrack_plugin.listen_for_tracking_commands(mock_core)

    assert mock_core.speak.call_args.args[0] == "Stopped"
    assert eyetrack_plugin.tracking_active is False


@patch.object(eyetrack_plugin, "get_screen_size", return_value=(1920, 1080))
@patch.object(eyetrack_plugin, "dbus_call", return_value=True)
def test_listen_for_tracking_commands_freeze(mock_dbus, mock_screen_size, mock_core):
    """When listen_for_tracking_commands receives freeze then it sets frozen flag."""
    eyetrack_plugin.tracking_active = True
    eyetrack_plugin.frozen = False
    eyetrack_plugin.cursor_x = 100
    eyetrack_plugin.cursor_y = 200

    mock_core.wait_for_speech.side_effect = [b"audio1", b"audio2"]
    mock_core.record_until_silence.return_value = b"more_audio"
    mock_core.transcribe.side_effect = ["freeze", "stop"]

    eyetrack_plugin.listen_for_tracking_commands(mock_core)

    assert eyetrack_plugin.frozen is False


@patch.object(eyetrack_plugin, "get_screen_size", return_value=(1920, 1080))
@patch.object(eyetrack_plugin, "dbus_call", return_value=True)
def test_listen_for_tracking_commands_click(mock_dbus, mock_screen_size, mock_core):
    """When listen_for_tracking_commands receives click then it calls dbus Click."""
    eyetrack_plugin.tracking_active = True
    eyetrack_plugin.cursor_x = 100
    eyetrack_plugin.cursor_y = 200

    mock_core.wait_for_speech.side_effect = [b"audio1", b"audio2"]
    mock_core.record_until_silence.return_value = b"more_audio"
    mock_core.transcribe.side_effect = ["click", "stop"]

    eyetrack_plugin.listen_for_tracking_commands(mock_core)

    click_calls = [call for call in mock_dbus.call_args_list if call.args[0] == "Click"]
    assert len(click_calls) >= 1


@patch.object(eyetrack_plugin, "get_screen_size", return_value=(1920, 1080))
@patch.object(eyetrack_plugin, "dbus_call", return_value=True)
def test_listen_for_tracking_commands_nudge_when_frozen(
    mock_dbus, mock_screen_size, mock_core
):
    """When listen_for_tracking_commands receives nudge while frozen then it adjusts cursor."""
    eyetrack_plugin.tracking_active = True
    eyetrack_plugin.frozen = True
    eyetrack_plugin.cursor_x = 500
    eyetrack_plugin.cursor_y = 500

    mock_core.wait_for_speech.side_effect = [b"audio1", b"audio2"]
    mock_core.record_until_silence.return_value = b"more_audio"
    mock_core.transcribe.side_effect = ["nudge right", "stop"]

    eyetrack_plugin.listen_for_tracking_commands(mock_core)

    moveto_calls = [
        call for call in mock_dbus.call_args_list if call.args[0] == "MoveTo"
    ]
    assert len(moveto_calls) >= 1


@patch.object(eyetrack_plugin, "get_screen_size", return_value=(1920, 1080))
@patch.object(eyetrack_plugin, "dbus_call", return_value=True)
def test_listen_for_tracking_commands_timeout(mock_dbus, mock_screen_size, mock_core):
    """When listen_for_tracking_commands times out waiting then it continues loop."""
    eyetrack_plugin.tracking_active = True

    mock_core.wait_for_speech.side_effect = [None, b"audio"]
    mock_core.record_until_silence.return_value = b"more_audio"
    mock_core.transcribe.return_value = "stop"

    eyetrack_plugin.listen_for_tracking_commands(mock_core)

    assert mock_core.wait_for_speech.call_count == 2


@patch.object(eyetrack_plugin, "get_screen_size", return_value=(1920, 1080))
@patch.object(eyetrack_plugin, "dbus_call", return_value=True)
def test_listen_for_tracking_commands_empty_transcription(
    mock_dbus, mock_screen_size, mock_core
):
    """When listen_for_tracking_commands receives empty transcription then it continues loop."""
    eyetrack_plugin.tracking_active = True

    mock_core.wait_for_speech.side_effect = [b"audio1", b"audio2"]
    mock_core.record_until_silence.return_value = b"more_audio"
    mock_core.transcribe.side_effect = ["", "stop"]

    eyetrack_plugin.listen_for_tracking_commands(mock_core)

    assert mock_core.transcribe.call_count == 2


@patch.object(eyetrack_plugin, "get_screen_size", return_value=(1920, 1080))
@patch.object(eyetrack_plugin, "dbus_call", return_value=True)
def test_listen_for_tracking_commands_go_unfreezes(
    mock_dbus, mock_screen_size, mock_core
):
    """When listen_for_tracking_commands receives go then it unfreezes cursor."""
    eyetrack_plugin.tracking_active = True
    eyetrack_plugin.frozen = True

    mock_core.wait_for_speech.side_effect = [b"audio1", b"audio2"]
    mock_core.record_until_silence.return_value = b"more_audio"
    mock_core.transcribe.side_effect = ["go", "stop"]

    eyetrack_plugin.listen_for_tracking_commands(mock_core)

    assert eyetrack_plugin.frozen is False


@pytest.mark.parametrize(
    ["command", "expected_direction"],
    [
        ["nudge up", "up"],
        ["nudge down", "down"],
        ["nudge left", "left"],
        ["nudge right", "right"],
    ],
)
@patch.object(eyetrack_plugin, "get_screen_size", return_value=(1920, 1080))
@patch.object(eyetrack_plugin, "dbus_call", return_value=True)
def test_listen_for_tracking_commands_nudge_directions(
    mock_dbus, mock_screen_size, command, expected_direction, mock_core
):
    """When listen_for_tracking_commands receives nudge commands then it moves cursor in specified direction."""
    eyetrack_plugin.tracking_active = True
    eyetrack_plugin.frozen = True
    eyetrack_plugin.cursor_x = 500
    eyetrack_plugin.cursor_y = 500

    mock_core.wait_for_speech.side_effect = [b"audio1", b"audio2"]
    mock_core.record_until_silence.return_value = b"more_audio"
    mock_core.transcribe.side_effect = [command, "stop"]

    eyetrack_plugin.listen_for_tracking_commands(mock_core)

    moveto_calls = [
        call for call in mock_dbus.call_args_list if call.args[0] == "MoveTo"
    ]
    assert len(moveto_calls) >= 1


@patch.object(eyetrack_plugin, "get_screen_size", return_value=(1920, 1080))
@patch.object(eyetrack_plugin, "dbus_call", return_value=True)
@patch.object(eyetrack_plugin, "recalibrate", return_value=(True, "Recalibrating"))
def test_listen_for_tracking_commands_recalibrate(
    mock_recalibrate, mock_dbus, mock_screen_size, mock_core
):
    """When listen_for_tracking_commands receives recalibrate then it recalibrates."""
    eyetrack_plugin.tracking_active = True

    mock_core.wait_for_speech.side_effect = [b"audio1", b"audio2"]
    mock_core.record_until_silence.return_value = b"more_audio"
    mock_core.transcribe.side_effect = ["recalibrate", "stop"]

    eyetrack_plugin.listen_for_tracking_commands(mock_core)

    assert mock_recalibrate.called
    assert mock_core.speak.call_args_list[0].args[0] == "Recalibrating"


@patch.object(eyetrack_plugin, "get_screen_size", return_value=(1920, 1080))
@patch.object(eyetrack_plugin, "dbus_call", return_value=True)
def test_listen_for_tracking_commands_double_click(
    mock_dbus, mock_screen_size, mock_core
):
    """When listen_for_tracking_commands receives double click then it calls dbus DoubleClick."""
    eyetrack_plugin.tracking_active = True
    eyetrack_plugin.cursor_x = 100
    eyetrack_plugin.cursor_y = 200

    mock_core.wait_for_speech.side_effect = [b"audio1", b"audio2"]
    mock_core.record_until_silence.return_value = b"more_audio"
    mock_core.transcribe.side_effect = ["double click", "stop"]

    eyetrack_plugin.listen_for_tracking_commands(mock_core)

    double_click_calls = [
        call for call in mock_dbus.call_args_list if call.args[0] == "DoubleClick"
    ]
    assert len(double_click_calls) >= 1


@patch.object(eyetrack_plugin, "get_screen_size", return_value=(1920, 1080))
@patch.object(eyetrack_plugin, "dbus_call", return_value=True)
def test_listen_for_tracking_commands_right_click(
    mock_dbus, mock_screen_size, mock_core
):
    """When listen_for_tracking_commands receives right click then it calls dbus RightClick."""
    eyetrack_plugin.tracking_active = True
    eyetrack_plugin.cursor_x = 100
    eyetrack_plugin.cursor_y = 200

    mock_core.wait_for_speech.side_effect = [b"audio1", b"audio2"]
    mock_core.record_until_silence.return_value = b"more_audio"
    mock_core.transcribe.side_effect = ["right click", "stop"]

    eyetrack_plugin.listen_for_tracking_commands(mock_core)

    right_click_calls = [
        call for call in mock_dbus.call_args_list if call.args[0] == "RightClick"
    ]
    assert len(right_click_calls) >= 1


@patch.object(eyetrack_plugin, "get_screen_size", return_value=(1920, 1080))
@patch.object(eyetrack_plugin, "dbus_call", return_value=True)
def test_listen_for_tracking_commands_stream_read_exception(
    mock_dbus, mock_screen_size, mock_core
):
    """When listen_for_tracking_commands encounters stream read exception then it continues."""
    eyetrack_plugin.tracking_active = True
    mock_core.stream.read.side_effect = Exception("Stream error")

    mock_core.wait_for_speech.return_value = b"audio"
    mock_core.record_until_silence.return_value = b"more_audio"
    mock_core.transcribe.return_value = "stop"

    eyetrack_plugin.listen_for_tracking_commands(mock_core)

    assert eyetrack_plugin.tracking_active is False


@pytest.mark.parametrize(
    ["exit_command"],
    [
        ["stop tracking"],
        ["end tracking"],
        ["close tracking"],
        ["stop"],
        ["cancel"],
        ["escape"],
        ["exit"],
        ["quit"],
        ["done"],
    ],
)
@patch.object(eyetrack_plugin, "get_screen_size", return_value=(1920, 1080))
@patch.object(eyetrack_plugin, "dbus_call", return_value=True)
def test_listen_for_tracking_commands_exit_commands(
    mock_dbus, mock_screen_size, exit_command, mock_core
):
    """When listen_for_tracking_commands receives exit commands then it stops tracking."""
    eyetrack_plugin.tracking_active = True

    mock_core.wait_for_speech.return_value = b"audio"
    mock_core.record_until_silence.return_value = b"more_audio"
    mock_core.transcribe.return_value = exit_command

    eyetrack_plugin.listen_for_tracking_commands(mock_core)

    assert eyetrack_plugin.tracking_active is False
    assert mock_core.speak.call_args.args[0] == "Stopped"


@pytest.mark.parametrize(
    ["webcam_opens", "frame_count", "prediction_sequence"],
    [
        # Webcam fails to open - exits immediately
        (False, 0, []),
        # Webcam opens but read fails immediately - loops but continues
        (True, 0, []),
        # Webcam opens, gets 5 frames with empty predictions - continues loop
        (True, 5, []),
        # Webcam opens, gets 15 frames with predictions for calibration
        (True, 15, [[[1.0], [2.0], [0.0]]]),
        # Webcam opens with varying predictions to exceed buffer size (BUFFER_SIZE=15)
        # Use predictions varying by 0.5 per frame (above VELOCITY_THRESHOLD of 0.3)
        (True, 50, [[[i * 0.5], [i * 0.5], [0.0]] for i in range(50)]),
        # Webcam opens with varying predictions: calibration + large positive offsets
        (True, 50, [[[1.0], [2.0], [0.0]]] * 10 + [[[10.0], [12.0], [0.0]]] * 40),
        # Webcam opens with varying predictions: calibration + large negative offsets
        (True, 50, [[[1.0], [2.0], [0.0]]] * 10 + [[[-10.0], [-12.0], [0.0]]] * 40),
    ],
)
@patch.object(eyetrack_plugin, "get_screen_size", return_value=(1920, 1080))
@patch.object(eyetrack_plugin, "dbus_call", return_value=True)
def test_run_tracking_scenarios(
    mock_dbus,
    mock_screen_size,
    webcam_opens,
    frame_count,
    prediction_sequence,
):
    """When run_tracking is called with various scenarios then it handles them appropriately."""
    mock_cap = Mock()
    mock_cap.isOpened.return_value = webcam_opens

    # Set up frame reading to return frames for frame_count iterations
    read_counter = [0]

    def read_side_effect():
        read_counter[0] += 1
        if read_counter[0] > frame_count + 20:
            # Safety: force stop after many iterations to prevent infinite loop
            eyetrack_plugin.stop_event.set()
        if read_counter[0] <= frame_count:
            return (True, Mock())
        return (False, None)

    mock_cap.read.side_effect = read_side_effect
    mock_cap.release = Mock()

    mock_model = Mock()
    if prediction_sequence:
        # Return different predictions per frame
        predict_counter = [0]

        def predict_side_effect(frame):
            idx = predict_counter[0]
            predict_counter[0] += 1
            if idx < len(prediction_sequence):
                pred = prediction_sequence[idx]
                return (pred[0], pred[1], pred[2])
            # Return last prediction for any extra frames
            pred = prediction_sequence[-1]
            return (pred[0], pred[1], pred[2])

        mock_model.predict.side_effect = predict_side_effect
    else:
        mock_model.predict.return_value = ([], [], [])

    mock_sixdrepnet_class = Mock(return_value=mock_model)

    mock_cv2 = Mock()
    mock_cv2.VideoCapture.return_value = mock_cap
    mock_cv2.flip.return_value = Mock()

    with patch.dict(
        "sys.modules",
        {
            "cv2": mock_cv2,
            "sixdrepnet": Mock(SixDRepNet=mock_sixdrepnet_class),
        },
    ):
        eyetrack_plugin.tracking_active = True
        eyetrack_plugin.stop_event.clear()

        # Set stop_event after a short delay to prevent infinite loop in test
        import threading

        def stop_after_delay():
            time.sleep(0.5)
            eyetrack_plugin.stop_event.set()

        stopper = threading.Thread(target=stop_after_delay, daemon=True)
        stopper.start()

        eyetrack_plugin.run_tracking()

        # After run_tracking completes, tracking_active should be False
        assert eyetrack_plugin.tracking_active is False
        if webcam_opens:
            assert mock_cap.release.called
