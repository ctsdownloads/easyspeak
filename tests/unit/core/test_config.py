"""Tests for the core config module."""

import importlib
from unittest.mock import patch

import pytest
from easyspeak.core import config


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
        "EASYSPEAK_PIPER_BIN",
        "EASYSPEAK_HOTKEY",
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


def test_bundled_model_found(monkeypatch, tmp_path):
    """A model present beside the venv (<prefix>/../models/...) is used."""
    (tmp_path / "models" / "whisper" / "base.en").mkdir(parents=True)
    monkeypatch.setattr(config.sys, "prefix", str(tmp_path / "venv"))
    assert config._bundled_model(
        "models", "whisper", "base.en", default="base.en"
    ) == str(tmp_path / "models" / "whisper" / "base.en")


def test_bundled_model_missing_falls_back(monkeypatch, tmp_path):
    """With no bundled tree, the default (download name / path) is kept."""
    monkeypatch.setattr(config.sys, "prefix", str(tmp_path / "venv"))
    assert (
        config._bundled_model("models", "whisper", "base.en", default="base.en")
        == "base.en"
    )


def test_bundled_bin_found(monkeypatch, tmp_path):
    """A binary present next to the interpreter is used by absolute path."""
    venv_bin = tmp_path / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "piper").touch()
    monkeypatch.setattr(config.sys, "executable", str(venv_bin / "python"))
    assert config._bundled_bin("piper", default="piper") == str(venv_bin / "piper")


def test_bundled_bin_missing_falls_back(monkeypatch, tmp_path):
    """With no co-located binary, the bare name (resolved via PATH) is kept."""
    venv_bin = tmp_path / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    monkeypatch.setattr(config.sys, "executable", str(venv_bin / "python"))
    assert config._bundled_bin("piper", default="piper") == "piper"


def test_piper_bin_env_override(monkeypatch):
    """EASYSPEAK_PIPER_BIN overrides the discovered/default binary."""
    monkeypatch.setenv("EASYSPEAK_PIPER_BIN", "/opt/voices/piper")
    importlib.reload(config)
    assert config.PIPER_BIN == "/opt/voices/piper"


def test_hotkey_default(monkeypatch):
    """EASYSPEAK_HOTKEY defaults to the ctrl+shift combo."""
    monkeypatch.delenv("EASYSPEAK_HOTKEY", raising=False)
    importlib.reload(config)
    assert config.HOTKEY_COMBO == "ctrl+shift"


def test_hotkey_custom_combo(monkeypatch):
    """EASYSPEAK_HOTKEY sets the combo directly."""
    monkeypatch.setenv("EASYSPEAK_HOTKEY", "ctrl+space")
    importlib.reload(config)
    assert config.HOTKEY_COMBO == "ctrl+space"


@pytest.mark.parametrize("value", ["", "off", "none", "OFF", "  none  "])
def test_hotkey_disable_values(monkeypatch, value):
    """An empty value or off/none (any case, trimmed) disables the hotkey."""
    monkeypatch.setenv("EASYSPEAK_HOTKEY", value)
    importlib.reload(config)
    assert config.HOTKEY_COMBO == ""
