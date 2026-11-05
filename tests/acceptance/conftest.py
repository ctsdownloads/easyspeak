"""Setup for the voice-feedback acceptance scenarios (pytest-bdd).

Spoken feedback can't be checked by listening in an automated run, so
these scenarios drive the real EasySpeak object with the subprocess boundary
stubbed. They assert the *observable contract* of speak()/drain — model
loaded once, blank ignored, flushed on shutdown, recovery after a break —
rather than audio leaving a speaker.

**Note:** See integration tests for test-driving external binaries for real.
"""

import os
import sys
from unittest.mock import MagicMock, Mock

import pytest

# easyspeak.core imports pyaudio/pyopen_wakeword/faster_whisper at load time; stub
# them so importing EasySpeak doesn't require the ML/audio stack.
sys.modules["pyaudio"] = MagicMock()
sys.modules["pyopen_wakeword"] = MagicMock()
sys.modules["faster_whisper"] = MagicMock()
sys.modules["faster_whisper.tokenizer"] = MagicMock(
    _LANGUAGE_CODES=("en", "de", "it", "fr", "es", "pt", "nl")
)

from easyspeak.core import main, speech, tray  # noqa: E402


@pytest.fixture(autouse=True)
def _no_noise_filter(monkeypatch):
    """Open the microphone directly: these scenarios stub the processes it starts."""
    monkeypatch.setattr(main, "NOISE_FILTER", False)


@pytest.fixture(autouse=True)
def _no_desktop_notifications(monkeypatch):
    """Keep the startup greeting from popping up notifications on the desktop."""
    monkeypatch.setattr(tray, "notify", Mock(return_value=False))


@pytest.fixture(autouse=True)
def _installed_speech(monkeypatch, tmp_path):
    """Provide what an installed EasySpeak speaks with: a player and a voice model.

    The scenarios stub the processes, so neither ever runs.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "pw-play").touch(mode=0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    model = tmp_path / "voice.onnx"
    model.touch()
    monkeypatch.setattr(speech, "PIPER_MODEL", str(model))
