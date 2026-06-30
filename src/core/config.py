"""Central tuning constants and the speech-model factory for EasySpeak.

Holds the wake-word, audio, silent-hotkey, speech-model, and desktop-sound
settings the daemon reads at import, alongside `load_whisper_model()`, which
builds the faster-whisper model from them. Most are plain constants; these
honor an `EASYSPEAK_*` environment variable:

- `EASYSPEAK_HOTKEY`
- `EASYSPEAK_HOTKEY_COMBO`
- `EASYSPEAK_PIPER_BIN`
- `EASYSPEAK_PIPER_MODEL`
- `EASYSPEAK_SOUNDS_DIR`
- `EASYSPEAK_WHISPER_COMPUTE_TYPE`
- `EASYSPEAK_WHISPER_CPU_THREADS`
- `EASYSPEAK_WHISPER_MODEL`

See the [Configuration guide](../usage.md#configuration) for what each does, its
default, and EasySpeak's other `EASYSPEAK_*` variables.

A plugin that needs host-environment setup does it in its own `setup()` hook —
see [Writing Plugins](../plugins.md).
"""

import os
import sys
from pathlib import Path

from faster_whisper import WhisperModel

# --- Wake word ---
WAKE_WORD = "hey_jarvis"  # OpenWakeWord model name
WAKE_THRESHOLD = 0.5
WAKE_COOLDOWN = 3.0  # Seconds to ignore wake word after trigger

# --- Audio thresholds ---
SILENCE_THRESHOLD = 300
SILENCE_DURATION = 0.3

MISUNDERSTAND_GRACE = 4.0  # Seconds to ignore repeat misses after feedback
FOLLOWUP_IDLE_ROUNDS = 2  # Quiet listens tolerated before a command session ends

# --- Keyboard (silent) activation ---
HOTKEY_COMBO = os.environ.get("EASYSPEAK_HOTKEY_COMBO", "ctrl+shift")
HOTKEY_ENABLED = os.environ.get("EASYSPEAK_HOTKEY", "1").lower() not in (
    "0",
    "false",
    "no",
    "off",
)


# --- Models ---
def _bundled_model(*parts, default):
    """Return a model path bundled beside the venv, or `default` if absent."""
    path = Path(sys.prefix).parent.joinpath(*parts)
    return str(path) if path.exists() else default


def _bundled_bin(name, *, default):
    """Return a binary path in this venv's `bin/`, or `default` if absent."""
    exe = Path(sys.executable).with_name(name)
    return str(exe) if exe.exists() else default


# The .deb/.rpm ship the models and `piper` beside the venv, so these defaults
# locate them from our interpreter; pip/source installs fall back to a download.
PIPER_MODEL = os.environ.get("EASYSPEAK_PIPER_MODEL") or _bundled_model(
    "models",
    "piper",
    "en_US-amy-medium.onnx",
    default=os.path.expanduser("~/.local/share/piper/en_US-amy-medium.onnx"),
)
PIPER_BIN = os.environ.get("EASYSPEAK_PIPER_BIN") or _bundled_bin(
    "piper", default="piper"
)
WHISPER_MODEL = os.environ.get("EASYSPEAK_WHISPER_MODEL") or _bundled_model(
    "models", "whisper", "base.en", default="base.en"
)
WHISPER_COMPUTE_TYPE = os.environ.get("EASYSPEAK_WHISPER_COMPUTE_TYPE", "int8")
try:
    WHISPER_CPU_THREADS = max(
        0, int(os.environ.get("EASYSPEAK_WHISPER_CPU_THREADS", "0"))
    )
except ValueError:
    WHISPER_CPU_THREADS = 0

# Prompt to help Whisper recognize common commands
COMMAND_PROMPT = (
    "numbers, scroll, click, open, close, back, forward, volume, brightness, stop"
)


# --- Desktop sounds ---
# Default to the FHS sound-theme path; on NixOS the flake overrides
# EASYSPEAK_SOUNDS_DIR to the Nix store copy, which actually exists.
SOUNDS_DIR = os.environ.get(
    "EASYSPEAK_SOUNDS_DIR", "/usr/share/sounds/freedesktop/stereo"
)
WAKE_SOUND = os.path.join(SOUNDS_DIR, "message.oga")
ERROR_SOUND = os.path.join(SOUNDS_DIR, "dialog-error.oga")


def load_whisper_model(
    model_name: str = WHISPER_MODEL,
    compute_type: str = WHISPER_COMPUTE_TYPE,
    cpu_threads: int = WHISPER_CPU_THREADS,
) -> WhisperModel:
    """Build a faster-whisper model from the configured (or given) settings."""
    return WhisperModel(model_name, compute_type=compute_type, cpu_threads=cpu_threads)
