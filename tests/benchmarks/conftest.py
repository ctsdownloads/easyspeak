"""Shared fixtures for Whisper benchmarks."""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock

# openwakeword isn't a hard dependency on Python 3.13+ (speexdsp-ns wheels
# missing) and the benchmark doesn't exercise the wake-word path. Stub it
# before tests import easyspeak.core.main. Same pattern as tests/unit/core/test_main.py.
sys.modules["openwakeword"] = MagicMock()
sys.modules["openwakeword.model"] = MagicMock()

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from faster_whisper.audio import decode_audio  # noqa: E402

SAMPLE_URL = "https://github.com/SYSTRAN/faster-whisper/raw/master/tests/data/jfk.flac"


@pytest.fixture(scope="session")
def sample_audio(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """JFK FLAC clip (~11s) — the canonical Whisper test sample."""
    path = tmp_path_factory.mktemp("audio") / "jfk.flac"
    with urllib.request.urlopen(SAMPLE_URL, timeout=30) as resp, path.open("wb") as f:
        f.write(resp.read())
    return path


@pytest.fixture(scope="session")
def sample_pcm(sample_audio: Path) -> bytes:
    """Raw 16 kHz mono int16 PCM — the shape EasySpeak.transcribe expects from PyAudio."""
    audio = decode_audio(str(sample_audio), sampling_rate=16000)
    return (audio * 32767).clip(-32768, 32767).astype(np.int16).tobytes()
