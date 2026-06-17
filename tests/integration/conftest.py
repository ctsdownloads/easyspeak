"""Shared setup for integration tests that drive real external commands.

These tests actually run the piper and audio-player binaries, so they are
opt-in: `tests/integration` is excluded from default discovery (see
pyproject.toml) and run via `just integration`. Every test still skips
gracefully when the binary or audio server it needs is absent, so on an
unprepared machine the folder degrades to a no-op rather than a failure.
"""

import shutil
import subprocess
import sys
from unittest.mock import MagicMock

import pytest

# easyspeak.core.config imports faster_whisper at module load, and main imports
# pyaudio/openwakeword. We only need the command-building helpers here, so stub
# the heavy deps rather than require a GPU/model just to read an argv list.
sys.modules["pyaudio"] = MagicMock()
sys.modules["openwakeword"] = MagicMock()
sys.modules["openwakeword.model"] = MagicMock()
sys.modules["faster_whisper"] = MagicMock()


def _audio_server_reachable():
    """True when a PulseAudio or PipeWire server is reachable for playback.

    `pactl info` covers PulseAudio and PipeWire's pulse-compat layer, but a
    PipeWire box can ship `pw-play` without that layer (no `pactl`); probe the
    PipeWire server directly so such setups aren't a false negative.
    """
    probes = []
    if shutil.which("pactl"):
        probes.append(["pactl", "info"])
    if shutil.which("pw-cli"):
        probes.append(["pw-cli", "info", "0"])
    for cmd in probes:
        try:
            if (
                subprocess.run(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                ).returncode
                == 0
            ):
                return True
        except (OSError, subprocess.SubprocessError):
            continue
    return False


@pytest.fixture(scope="session")
def audio_server():
    """Skip the test unless an audio server is available to play into."""
    if not _audio_server_reachable():
        pytest.skip("no PulseAudio/PipeWire server reachable")


def _user_systemd_reachable():
    """True when a user systemd manager answers (``systemctl --user`` works).

    Headless CI usually has the systemctl binary but no per-user manager/bus, so
    ``--user`` commands fail to connect; ``show-environment`` needs that bus and
    returns non-zero when it's absent, making it a clean reachability probe.
    """
    if shutil.which("systemctl") is None:
        return False
    try:
        return (
            subprocess.run(
                ["systemctl", "--user", "show-environment"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False


@pytest.fixture(scope="session")
def user_systemd():
    """Skip the test unless a user systemd manager is reachable."""
    if not _user_systemd_reachable():
        pytest.skip("no user systemd session (systemctl --user unavailable)")
