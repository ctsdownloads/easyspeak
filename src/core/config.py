"""Central tuning constants and the speech-model factory for EasySpeak.

Holds the wake-word, audio, silent-hotkey, speech-model, and desktop-sound
settings the daemon reads at import, alongside `load_whisper_model()`, which
builds the faster-whisper model from them. Most are plain constants; these
honor an `EASYSPEAK_*` environment variable:

- `EASYSPEAK_HOTKEY`
- `EASYSPEAK_LANGUAGE`
- `EASYSPEAK_OFFLINE`
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

import logging
import os
import sys
from pathlib import Path

from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

# --- Network policy ---
OFFLINE_MODE = os.environ.get("EASYSPEAK_OFFLINE", "strict").strip().lower()
NETWORK_ALLOWED = OFFLINE_MODE == "relaxed"

# --- Wake word ---
WAKE_WORD = "hey_jarvis"  # OpenWakeWord model name

WAKE_WORD_SPOKEN = "Hey Jarvis"
WAKE_THRESHOLD = 0.5
WAKE_COOLDOWN = 3.0  # Seconds to ignore wake word after trigger

# Modes normally accept a bare command. With this on they wait for the wake word
# first, which keeps a speaker playing video from being transcribed as commands.
_require_wake = os.environ.get("EASYSPEAK_REQUIRE_WAKE_WORD", "").strip().lower()
REQUIRE_WAKE_WORD = _require_wake in {"1", "true", "yes", "on"}

# --- Audio thresholds ---
SILENCE_THRESHOLD = 300

# Never calibrate above this: speech itself sits well above it, and a threshold
# that high would treat a spoken sentence as silence.
SILENCE_THRESHOLD_MAX = 2000

# How long to listen to the room at startup, and how far above the measured floor
# to put the threshold.
SILENCE_CALIBRATION_SECONDS = 1.0
SILENCE_NOISE_MARGIN = 2.5
SILENCE_DURATION = 0.3

# Longest single utterance, in seconds. Commands are a few words, so a short cap
# keeps the daemon responsive.
MAX_RECORD_SECONDS = 5.0


MISUNDERSTAND_GRACE = 4.0  # Seconds to ignore repeat misses after feedback
FOLLOWUP_IDLE_ROUNDS = 2  # Quiet listens tolerated before a command session ends

# --- Keyboard (silent) activation ---
_hotkey = os.environ.get("EASYSPEAK_HOTKEY", "ctrl+shift").strip()
HOTKEY_COMBO = "" if _hotkey.lower() in ("", "off", "none") else _hotkey


# --- Language ---
# The language the user dictates in. Commands stay English words wherever a
# plugin matches them. Also selects which installed language pack's models to use.
LANGUAGE = os.environ.get("EASYSPEAK_LANGUAGE", "en").strip().lower() or "en"


# --- Models ---
# The .deb/.rpm ship the models and `piper` beside the venv, so these defaults
# locate them from our interpreter; pip/source installs fall back to a download.
# A language pack installs its models under `models/<language>/`.
MODELS_DIR = Path(sys.prefix).parent / "models"


def _bundled_model(language, kind, pattern, *, default):
    """Return the `language` pack's `kind` model matching `pattern`, or `default`.

    `kind` is the `whisper` or `piper` directory of the pack. It holds one model,
    so with several dropped in by hand the first by name wins.
    """
    found = sorted((MODELS_DIR / language / kind).glob(pattern))
    return str(found[0]) if found else default


def _bundled_bin(name, *, default):
    """Return a binary path in this venv's `bin/`, or `default` if absent."""
    exe = Path(sys.executable).with_name(name)
    return str(exe) if exe.exists() else default


PIPER_MODEL = os.environ.get("EASYSPEAK_PIPER_MODEL") or _bundled_model(
    LANGUAGE,
    "piper",
    "*.onnx",
    default=str(Path("~/.local/share/piper/en_US-amy-medium.onnx").expanduser()),
)
PIPER_BIN = os.environ.get("EASYSPEAK_PIPER_BIN") or _bundled_bin(
    "piper", default="piper"
)
WHISPER_MODEL = os.environ.get("EASYSPEAK_WHISPER_MODEL") or _bundled_model(
    LANGUAGE, "whisper", "*", default="base.en" if LANGUAGE == "en" else "small"
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
SOUNDS_DIR = Path(
    os.environ.get("EASYSPEAK_SOUNDS_DIR", "/usr/share/sounds/freedesktop/stereo")
)
WAKE_SOUND = SOUNDS_DIR / "message.oga"
ERROR_SOUND = SOUNDS_DIR / "dialog-error.oga"


def load_whisper_model(
    model_name: str = WHISPER_MODEL,
    compute_type: str = WHISPER_COMPUTE_TYPE,
    cpu_threads: int = WHISPER_CPU_THREADS,
) -> WhisperModel:
    """Build a faster-whisper model from the configured (or given) settings.

    A model already on disk — bundled in a language pack or cached from an earlier
    run — loads without any network access. When it is missing, EasySpeak stays
    offline by default and raises an actionable message; setting
    `EASYSPEAK_OFFLINE=relaxed` (see `NETWORK_ALLOWED`) lets it fetch a bare name
    like `base.en` from Hugging Face instead.
    """
    kwargs = {"compute_type": compute_type, "cpu_threads": cpu_threads}
    try:
        return WhisperModel(model_name, local_files_only=True, **kwargs)
    except FileNotFoundError:
        if not NETWORK_ALLOWED:
            msg = (
                f"speech model {model_name!r} is not installed; set "
                "EASYSPEAK_OFFLINE=relaxed to download it, or install a language pack"
            )
            raise RuntimeError(msg) from None
        logger.warning(
            "Speech model %r is not installed; downloading it from Hugging Face. "
            "Install a language pack to avoid this, or set EASYSPEAK_OFFLINE=strict "
            "to keep EasySpeak offline.",
            model_name,
        )
        return WhisperModel(model_name, local_files_only=False, **kwargs)
