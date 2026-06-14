"""Tuning constants and model factory for EasySpeak.

Override the EASYSPEAK_* environment variables to customise behaviour
without editing source. Plugin-specific host-environment setup lives in
each plugin's own setup() hook, not here.
"""

import os

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

# --- Models ---
PIPER_MODEL = os.environ.get(
    "EASYSPEAK_PIPER_MODEL",
    os.path.expanduser("~/.local/share/piper/en_US-amy-medium.onnx"),
)
WHISPER_MODEL = os.environ.get("EASYSPEAK_WHISPER_MODEL", "base.en")
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
