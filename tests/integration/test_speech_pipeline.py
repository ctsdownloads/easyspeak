"""Real-execution checks for the text-to-speech pipeline.

The unit suite asserts that ``_player_cmd`` *returns* the right argv; nothing
there proves the chosen binary actually accepts that invocation. These tests
close that gap by running the commands for real. They are tiered by how much
environment preparation each needs:

- ``piper`` synthesis: needs the ``piper`` binary + voice model; no audio device.
- player playback:      needs the player binary *and* a running audio server.
"""

import shutil
import subprocess
from pathlib import Path

import pytest
from easyspeak.core.config import PIPER_MODEL
from easyspeak.core.main import EasySpeak

# Only the players _player_cmd can actually emit, in its own priority order.
# (pacat is intentionally absent: _player_cmd never selects it — paplay --raw
# is the same binary and is what the code uses.)
PLAYERS = ["pw-play", "paplay", "ffplay"]


@pytest.mark.skipif(not shutil.which("piper"), reason="piper not installed")
@pytest.mark.skipif(
    not Path(PIPER_MODEL).exists(), reason=f"voice model missing: {PIPER_MODEL}"
)
def test_piper_streams_raw_pcm():
    """piper --output-raw turns a phrase into non-empty PCM on stdout."""
    proc = subprocess.run(
        ["piper", "--model", PIPER_MODEL, "--output-raw"],
        input=b"Integration test.\n",
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=60,
    )
    assert proc.returncode == 0
    assert len(proc.stdout) > 0  # got audio samples, not an empty stream


@pytest.mark.parametrize("player", PLAYERS)
def test_player_accepts_our_raw_invocation(player, audio_server, monkeypatch):
    """The exact argv _player_cmd builds is accepted by the real player.

    This is the check that would have settled the paplay-vs-pacat question:
    we feed a short, finite silent PCM buffer through the actual command and
    require a clean exit, which fails loudly if the binary rejects our flags.
    """
    if not shutil.which(player):
        pytest.skip(f"{player} not installed")

    # Force _player_cmd to select exactly this player, regardless of priority.
    real_which = shutil.which
    monkeypatch.setattr(
        "easyspeak.core.main.shutil.which",
        lambda name: real_which(name) if name == player else None,
    )
    rate = 22050
    cmd = EasySpeak()._player_cmd(rate)
    assert cmd[0] == player

    # ~0.3s of finite silence so the player consumes the stream and exits.
    pcm = b"\x00\x00" * int(rate * 0.3)
    proc = subprocess.run(
        cmd,
        input=pcm,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=15,
    )
    assert proc.returncode == 0, f"{player} rejected our raw-PCM invocation"
