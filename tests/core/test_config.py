"""Tests for the core config module."""

import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest

# Mock the heavy external dep before importing
sys.modules.setdefault("faster_whisper", MagicMock())

from easyspeak.core import config  # noqa: E402


@pytest.fixture(autouse=True)
def _restore_config(monkeypatch):
    """Clear EASYSPEAK_* env vars and reload to defaults after each test.

    Tests below mutate process env + reload config to exercise the
    module-level parsing logic. This fixture restores a clean baseline
    for the next test (and the rest of the suite).
    """
    yield
    for var in [
        "EASYSPEAK_WHISPER_CPU_THREADS",
        "EASYSPEAK_WHISPER_MODEL",
        "EASYSPEAK_WHISPER_COMPUTE_TYPE",
        "EASYSPEAK_PIPER_MODEL",
    ]:
        monkeypatch.delenv(var, raising=False)
    importlib.reload(config)


def test_whisper_cpu_threads_default(monkeypatch):
    """Unset env: defaults to 0 (CTranslate2 auto-pick)."""
    monkeypatch.delenv("EASYSPEAK_WHISPER_CPU_THREADS", raising=False)
    importlib.reload(config)
    assert config.WHISPER_CPU_THREADS == 0


def test_whisper_cpu_threads_valid(monkeypatch):
    """Numeric env value is parsed."""
    monkeypatch.setenv("EASYSPEAK_WHISPER_CPU_THREADS", "4")
    importlib.reload(config)
    assert config.WHISPER_CPU_THREADS == 4


def test_whisper_cpu_threads_invalid_falls_back(monkeypatch):
    """Garbage env value falls back to 0 (covers `except ValueError`)."""
    monkeypatch.setenv("EASYSPEAK_WHISPER_CPU_THREADS", "not-a-number")
    importlib.reload(config)
    assert config.WHISPER_CPU_THREADS == 0


def test_whisper_cpu_threads_negative_clamped(monkeypatch):
    """Negative values are clamped to 0 via max()."""
    monkeypatch.setenv("EASYSPEAK_WHISPER_CPU_THREADS", "-5")
    importlib.reload(config)
    assert config.WHISPER_CPU_THREADS == 0


def test_load_whisper_model_invokes_whisper():
    """load_whisper_model passes its args through to WhisperModel()."""
    with patch("easyspeak.core.config.WhisperModel") as mock_model:
        result = config.load_whisper_model("tiny.en", "float32", 4)

    mock_model.assert_called_once_with("tiny.en", compute_type="float32", cpu_threads=4)
    assert result is mock_model.return_value


def test_load_whisper_model_uses_module_defaults():
    """Called without args, load_whisper_model uses the module constants."""
    with patch("easyspeak.core.config.WhisperModel") as mock_model:
        config.load_whisper_model()

    mock_model.assert_called_once_with(
        config.WHISPER_MODEL,
        compute_type=config.WHISPER_COMPUTE_TYPE,
        cpu_threads=config.WHISPER_CPU_THREADS,
    )


def test_piper_model_env_override(monkeypatch):
    """EASYSPEAK_PIPER_MODEL overrides the default path."""
    monkeypatch.setenv("EASYSPEAK_PIPER_MODEL", "/opt/voices/voice.onnx")
    importlib.reload(config)
    assert config.PIPER_MODEL == "/opt/voices/voice.onnx"


def test_whisper_model_env_override(monkeypatch):
    """EASYSPEAK_WHISPER_MODEL overrides the default model name."""
    monkeypatch.setenv("EASYSPEAK_WHISPER_MODEL", "tiny.en")
    importlib.reload(config)
    assert config.WHISPER_MODEL == "tiny.en"


def test_whisper_compute_type_env_override(monkeypatch):
    """EASYSPEAK_WHISPER_COMPUTE_TYPE overrides the default compute type."""
    monkeypatch.setenv("EASYSPEAK_WHISPER_COMPUTE_TYPE", "float16")
    importlib.reload(config)
    assert config.WHISPER_COMPUTE_TYPE == "float16"
