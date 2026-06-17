"""Tuning constants and model factory for EasySpeak.

Override the EASYSPEAK_* environment variables to customise behaviour without editing
source. Plugin-specific host-environment setup lives in each plugin's own setup() hook,
not here.
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
# Hold this combo to dictate without the wake word; release to stop. Accepts the
# aliases ctrl/shift/alt/super or raw evdev key names, joined with '+'. Needs
# read access to /dev/input (be in the 'input' group). Set EASYSPEAK_HOTKEY=0
# to turn the feature off.
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


# The .deb/.rpm bundle the speech models beside the venv (under
# /opt/easyspeak/models) and `piper` inside it. The defaults below locate them
# from our own interpreter, so no launcher or PATH setup is needed; pip/source
# installs have no such tree and fall back to a download name / the home dir.
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
    # 0 == let CTranslate2 pick (uses all logical cores, which oversubscribes
    # hyper-threaded CPUs). Set to physical core count for best CPU-only latency.
    WHISPER_CPU_THREADS = max(
        0, int(os.environ.get("EASYSPEAK_WHISPER_CPU_THREADS", "0"))
    )
except ValueError:
    WHISPER_CPU_THREADS = 0

# Prompt to help Whisper recognize common commands
COMMAND_PROMPT = (
    "numbers, scroll, click, open, close, back, forward, volume, brightness, stop"
)


def load_whisper_model(
    model_name: str = WHISPER_MODEL,
    compute_type: str = WHISPER_COMPUTE_TYPE,
    cpu_threads: int = WHISPER_CPU_THREADS,
) -> WhisperModel:
    """Build a faster-whisper model from the configured (or given) settings."""
    return WhisperModel(model_name, compute_type=compute_type, cpu_threads=cpu_threads)
