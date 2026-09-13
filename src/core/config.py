"""Central tuning constants and the speech-model factory for EasySpeak.

Holds the wake-word, audio, silent-hotkey, speech-model, and desktop-sound
settings the daemon reads at import, alongside `load_parakeet_model()` and
`load_whisper_model()`, which build the speech model from them. Most are plain
constants; these honor an `EASYSPEAK_*` environment variable:

- `EASYSPEAK_HOTKEY`
- `EASYSPEAK_LANGUAGE`
- `EASYSPEAK_MODELS_DIR`
- `EASYSPEAK_OFFLINE`
- `EASYSPEAK_PIPER_BIN`
- `EASYSPEAK_PIPER_MODEL`
- `EASYSPEAK_SOUNDS_DIR`
- `EASYSPEAK_STT`
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
from typing import Any

from faster_whisper import WhisperModel

# The codes faster-whisper's `transcribe()` accepts; validated here, at startup,
# rather than at the first dictation.
from faster_whisper.tokenizer import _LANGUAGE_CODES as LANGUAGE_CODES

from .vocabulary import load_table

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
# What the daemon should tell the user about the language setting, right after
# its "Loading Whisper (..., language=...)" line, so the two are read together.
LANGUAGE_WARNINGS: list[str] = []


def _language():
    """Return the language the user dictates in, English unless a valid code is set.

    `EASYSPEAK_LANGUAGE` (and the `--language` option, which sets it) selects the
    installed language pack's Whisper model, the reply catalog and the voice, and
    the words the commands take where a plugin has a vocabulary table for it;
    the English words work in every language. A code Whisper does not know is
    reported and English used.
    """
    code = os.environ.get("EASYSPEAK_LANGUAGE", "en").strip().lower() or "en"
    if code not in LANGUAGE_CODES:
        LANGUAGE_WARNINGS.append(
            f"EASYSPEAK_LANGUAGE={code!r} is not a language code Whisper knows; "
            "using English"
        )
        return "en"
    return code


LANGUAGE = _language()


# --- Models ---
# The .deb/.rpm ship the models and `piper` beside the venv, so these defaults
# locate them from our interpreter; pip/source installs fall back to a download.
# A language pack installs its models under `models/<language>/`.
MODELS_DIR = Path(
    os.environ.get("EASYSPEAK_MODELS_DIR") or Path(sys.prefix).parent / "models"
)


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


def _translated(language):
    """Whether the replies have a catalog for `language`, in the core or a plugin."""
    src = Path(__file__).parent.parent
    return any(src.glob(f"*/locale/{language}/LC_MESSAGES/*.po")) or any(
        src.glob(f"plugins/*/locale/{language}/LC_MESSAGES/*.po")
    )


def _voiced(language):
    """Whether a language pack with a Piper voice for `language` is installed."""
    return _bundled_model(language, "piper", "*.onnx", default=None) is not None


# The language the spoken replies are in, which is the language the voice must
# be for: a German voice reads an English "Done" with German phonemes, and an
# English voice reads a German one no better. The replies are written in
# English and spoken in the user's language where a translation and that
# language's voice both exist (see `core.i18n`).
REPLY_LANGUAGE = (
    LANGUAGE
    if LANGUAGE == "en" or (_translated(LANGUAGE) and _voiced(LANGUAGE))
    else "en"
)
if REPLY_LANGUAGE != LANGUAGE:
    _missing = [
        f"no {LANGUAGE!r} {what}"
        for what, missing in (
            ("translation", not _translated(LANGUAGE)),
            ("language pack", not _voiced(LANGUAGE)),
        )
        if missing
    ]
    LANGUAGE_WARNINGS.append(
        f"Dictation in {LANGUAGE!r}, replies in English ({', '.join(_missing)})"
    )


PIPER_MODEL = os.environ.get("EASYSPEAK_PIPER_MODEL") or _bundled_model(
    REPLY_LANGUAGE,
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

# Commands are transcribed in the user's language once the core's vocabulary
# table exists for it, English otherwise; the English phrases are accepted in
# every language. The table also carries the number words and the words that
# bias Whisper towards the commands.
_LOCALE = Path(__file__).with_name("locale")
COMMAND_LANGUAGE = LANGUAGE if load_table(_LOCALE, LANGUAGE) else "en"
_vocabularies = {
    code: load_table(_LOCALE, code) for code in dict.fromkeys((COMMAND_LANGUAGE, "en"))
}
COMMAND_PROMPTS = {
    code: ", ".join(table["commands"]["prompt"])
    for code, table in _vocabularies.items()
}
COMMAND_PROMPT = COMMAND_PROMPTS[COMMAND_LANGUAGE]
NUMBER_WORDS = frozenset(
    word for table in _vocabularies.values() for word in table["numbers"]
)


# --- Speech recognition backend ---
# Parakeet TDT v3 (NVIDIA, through onnx-asr) is the default: one multilingual
# model for the 25 languages it covers, several times faster than Whisper on a
# short command, punctuation and capitalization of its own, no prompt biasing.
# Whisper (faster-whisper, one model per language pack) remains for the other
# languages, and takes over when the Parakeet model is neither installed nor
# downloadable, so a language pack alone still gives a working EasySpeak.
STT_BACKENDS = ("whisper", "parakeet")
STT_WARNINGS: list[str] = []
PARAKEET_MODEL = "nemo-parakeet-tdt-0.6b-v3"
PARAKEET_MODEL_DIR = MODELS_DIR / "parakeet"
# The 25 languages the model tells apart by itself; any other one needs Whisper.
PARAKEET_LANGUAGES = frozenset(
    "bg hr cs da nl en et fi fr de el hu it lv lt mt pl pt ro sk sl es sv ru uk".split()  # noqa: SIM905
)
PARAKEET_QUANTIZATION = "int8"
PARAKEET_FILES = (
    "config.json",
    "vocab.txt",
    f"encoder-model.{PARAKEET_QUANTIZATION}.onnx",
    f"decoder_joint-model.{PARAKEET_QUANTIZATION}.onnx",
)


def parakeet_installed(model_dir: Path = PARAKEET_MODEL_DIR) -> bool:
    """Whether every file of the Parakeet model is in `model_dir`.

    A directory left behind by an interrupted download has some of them, and
    counts as not installed.
    """
    return all((model_dir / name).is_file() for name in PARAKEET_FILES)


STT = os.environ.get("EASYSPEAK_STT", "").strip().lower()
if STT and STT not in STT_BACKENDS:
    STT_WARNINGS.append(
        f"Unknown speech recognition backend {STT!r} (EASYSPEAK_STT), using the default"
    )
    STT = ""
if STT != "whisper" and LANGUAGE not in PARAKEET_LANGUAGES:
    STT = "whisper"
    STT_WARNINGS.append(f"Parakeet does not cover {LANGUAGE!r}, using Whisper")
if not STT:
    if parakeet_installed() or NETWORK_ALLOWED:
        STT = "parakeet"
    else:
        STT = "whisper"
        STT_WARNINGS.append(
            f"Parakeet model not installed in {PARAKEET_MODEL_DIR}, using Whisper; "
            "set EASYSPEAK_OFFLINE=relaxed to download it"
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


def load_parakeet_model(model_dir: Path = PARAKEET_MODEL_DIR) -> Any:
    """Build the Parakeet TDT v3 recognizer from the ONNX files in `model_dir`.

    A directory holding the whole model loads offline; a missing one is fetched
    from Hugging Face into it when `EASYSPEAK_OFFLINE=relaxed`, and refused
    otherwise, like the Whisper models. An incomplete one, left by an interrupted
    download, is reported for the user to delete: onnx-asr never downloads into
    a directory that exists. Whatever else onnx-asr refuses to load is reported
    the same way, as a `RuntimeError` the daemon turns into a clean exit.
    """
    import onnx_asr

    if not parakeet_installed(model_dir):
        if model_dir.exists():
            msg = (
                f"speech model {PARAKEET_MODEL!r} is incomplete in {model_dir}; "
                "delete that directory to download it again"
            )
            raise RuntimeError(msg)
        if not NETWORK_ALLOWED:
            msg = (
                f"speech model {PARAKEET_MODEL!r} is not installed in {model_dir}; "
                "set EASYSPEAK_OFFLINE=relaxed to download it"
            )
            raise RuntimeError(msg)
        logger.warning(
            "Speech model %r is not installed; downloading it from Hugging Face "
            "into %s. Set EASYSPEAK_OFFLINE=strict to keep EasySpeak offline.",
            PARAKEET_MODEL,
            model_dir,
        )
    try:
        return onnx_asr.load_model(
            PARAKEET_MODEL, model_dir, quantization=PARAKEET_QUANTIZATION
        )
    except (onnx_asr.utils.ModelLoadingError, ValueError) as exc:
        msg = f"speech model {PARAKEET_MODEL!r} in {model_dir} cannot be loaded: {exc}"
        raise RuntimeError(msg) from exc
