"""Tests for the microphone noise filter."""

import os
import subprocess
from unittest.mock import Mock, patch

import pytest
from easyspeak.core import noisefilter
from easyspeak.core.noisefilter import NODE, NoiseFilter


@pytest.fixture
def no_wait():
    """Make the startup wait run instantly: one poll, then the deadline passes."""
    with (
        patch.object(noisefilter.time, "monotonic", side_effect=[0, 0, 99]),
        patch.object(noisefilter.time, "sleep"),
    ):
        yield


@pytest.fixture(autouse=True)
def _clean_pipewire_node(monkeypatch):
    """Start every test without a PIPEWIRE_NODE from the shell running it."""
    monkeypatch.delenv("PIPEWIRE_NODE", raising=False)


@patch.object(noisefilter, "_node_exists", return_value=True)
@patch.object(noisefilter.subprocess, "Popen")
def test_start_loads_the_echo_cancel_module(mock_popen, mock_exists):
    """The filter is PipeWire's echo-cancel module, hosted by pw-cli."""
    mock_popen.return_value.poll.return_value = None

    assert NoiseFilter().start() is True
    command = mock_popen.call_args.args[0]
    assert command[:4] == [
        "pw-cli",
        "-m",
        "load-module",
        "libpipewire-module-echo-cancel",
    ]
    assert "webrtc.noise_suppression = true" in command[4]
    assert f'node.name = "{NODE}"' in command[4]


@patch.object(noisefilter.subprocess, "Popen", side_effect=FileNotFoundError("pw-cli"))
def test_start_without_pw_cli_keeps_the_plain_mic(mock_popen):
    """No pw-cli, no filter, and nothing breaks."""
    nf = NoiseFilter()

    assert nf.start() is False
    with nf.selected():
        assert "PIPEWIRE_NODE" not in os.environ


@pytest.mark.usefixtures("no_wait")
@patch.object(noisefilter, "_node_exists", return_value=False)
@patch.object(noisefilter.subprocess, "Popen")
def test_start_gives_up_when_the_filter_never_appears(mock_popen, mock_exists):
    """An old PipeWire without the module: the helper is stopped, plain mic kept."""
    process = mock_popen.return_value
    process.poll.return_value = None

    nf = NoiseFilter()

    assert nf.start() is False
    process.terminate.assert_called_once_with()
    with nf.selected():
        assert "PIPEWIRE_NODE" not in os.environ


@patch.object(noisefilter, "_node_exists")
@patch.object(noisefilter.subprocess, "Popen")
def test_start_gives_up_when_the_helper_exits(mock_popen, mock_exists):
    """pw-cli quitting on its own means the module was refused."""
    mock_popen.return_value.poll.return_value = 1

    assert NoiseFilter().start() is False
    mock_exists.assert_not_called()


def test_stop_without_a_filter_does_nothing():
    """Stopping twice, or before starting, is harmless."""
    NoiseFilter().stop()


def test_stop_kills_a_helper_that_ignores_terminate():
    """A stuck pw-cli is killed rather than left holding the mic."""
    nf = NoiseFilter()
    process = Mock()
    process.wait.side_effect = [subprocess.TimeoutExpired("pw-cli", 2), 0]
    nf._process = process

    nf.stop()

    process.kill.assert_called_once_with()
    assert nf._process is None


def test_selected_points_only_the_open_at_the_filter():
    """PIPEWIRE_NODE is set inside the block and gone after it."""
    nf = NoiseFilter()
    nf._process = Mock()

    with nf.selected():
        assert os.environ["PIPEWIRE_NODE"] == NODE
    assert "PIPEWIRE_NODE" not in os.environ


def test_selected_restores_a_users_own_setting(monkeypatch):
    """Someone who set PIPEWIRE_NODE themselves gets it back after the open."""
    monkeypatch.setenv("PIPEWIRE_NODE", "my_mic")
    nf = NoiseFilter()
    nf._process = Mock()

    with nf.selected():
        assert os.environ["PIPEWIRE_NODE"] == NODE
    assert os.environ["PIPEWIRE_NODE"] == "my_mic"


@patch.object(noisefilter.subprocess, "run")
def test_node_exists_reads_the_node_list(mock_run):
    """The filter counts as up once pw-cli lists its source by name."""
    mock_run.return_value = Mock(stdout=f'\tid 84\n\t\tnode.name = "{NODE}"\n')

    assert noisefilter._node_exists() is True


@patch.object(noisefilter.subprocess, "run", side_effect=OSError("pw-cli"))
def test_node_exists_without_pw_cli(mock_run):
    """No pw-cli to ask means no filter."""
    assert noisefilter._node_exists() is False
