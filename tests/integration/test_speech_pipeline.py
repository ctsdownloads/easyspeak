"""Real-execution checks for the text-to-speech pipeline.

The unit suite asserts that ``_player_cmd`` *returns* the right argv; nothing
there proves the chosen binary actually accepts that invocation. These tests
close that gap by running the commands for real. They are tiered by how much
environment preparation each needs:

- ``piper`` synthesis: needs the ``piper`` binary + voice model; no audio device.
- ``kokoro`` synthesis: needs the Kokoro wheels (``easyspeak[tts-kokoro]`` on
  Python < 3.14) + the provisioned model files; no audio device.
- player playback:      needs the player binary *and* a running audio server.
"""

import importlib.util
import os
import select
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from easyspeak.core import config
from easyspeak.core.config import PIPER_MODEL
from easyspeak.core.kokoro_worker import SPEAK_SAMPLE_RATE
from easyspeak.core.speech import SpeechPipeline

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


@pytest.mark.skipif(
    sys.version_info >= (3, 14) or importlib.util.find_spec("kokoro_onnx") is None,
    reason=(
        "kokoro-onnx not installed for this interpreter — "
        "run `easyspeak --provision-kokoro` under Python < 3.14"
    ),
)
@pytest.mark.skipif(
    not (config.KOKORO_MODEL.is_file() and config.KOKORO_VOICES.is_file()),
    reason=f"Kokoro model files missing under {config.KOKORO_DIR} — "
    f"run `easyspeak --provision-kokoro` (or point EASYSPEAK_MODELS_DIR there)",
)
@pytest.mark.skipif(
    config.LANGUAGE not in config.KOKORO_LANGUAGES,
    reason=f"Kokoro has no voice for {config.LANGUAGE!r} (by design, spec §2)",
)
def test_kokoro_worker_streams_raw_pcm():
    """The real Kokoro worker announces ready, then turns a reply line into
    non-empty 24 kHz s16le PCM on stdout — the exact fd protocol the speech
    pipeline speaks (`--ready-fd`, one reply per stdin line)."""
    ready_read, ready_write = os.pipe()
    # stderr to a real file, never a pipe: a chatty worker must not deadlock a
    # parent that is blocked in stdout.read() with a full stderr pipe.
    with tempfile.TemporaryFile() as stderr:
        worker = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "easyspeak.core.kokoro_worker",
                "--model",
                str(config.KOKORO_MODEL),
                "--voices",
                str(config.KOKORO_VOICES),
                "--voice",
                config.KOKORO_VOICES_BY_LANGUAGE[config.LANGUAGE],
                "--lang",
                config.KOKORO_LANGUAGE_CODES[config.LANGUAGE],
                "--ready-fd",
                str(ready_write),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            pass_fds=(ready_write,),
        )
        os.close(ready_write)  # the child holds the only write end now
        try:
            # Cold CUDA init can take seconds; EOF (worker died) ends the read.
            if not select.select([ready_read], [], [], 180)[0]:
                worker.kill()
                pytest.fail("kokoro worker never announced readiness within 180 s")
            ready = os.read(ready_read, 256)
            if not ready.startswith(b"ready provider="):
                stderr.seek(0)
                pytest.fail(f"kokoro worker died before ready:\n{stderr.read()!s}")
            provider = ready.decode().split("provider=", 1)[1].strip()

            pcm, _ = worker.communicate(b"Integration test.\n", timeout=120)
        finally:
            os.close(ready_read)
            if worker.poll() is None:  # a failed assert must not leak the worker
                worker.kill()
                worker.wait(timeout=10)

    assert worker.returncode == 0
    assert len(pcm) > 0, f"no audio for the reply line (provider={provider})"
    assert len(pcm) % 2 == 0  # whole s16 frames, never a torn sample
    assert len(pcm) / (SPEAK_SAMPLE_RATE * 2) >= 0.1  # a spoken phrase, not a blip


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
        "easyspeak.core.speech.shutil.which",
        lambda name: real_which(name) if name == player else None,
    )
    rate = 22050
    cmd = SpeechPipeline()._player_cmd(rate)
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
