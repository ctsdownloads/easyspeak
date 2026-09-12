"""Tests for the core config module."""

import importlib
from pathlib import Path
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
        "EASYSPEAK_LANGUAGE",
        "EASYSPEAK_MODELS_DIR",
        "EASYSPEAK_OFFLINE",
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
    """A locally-present model loads once, offline (local_files_only=True)."""
    with patch("easyspeak.core.config.WhisperModel") as mock_model:
        result = config.load_whisper_model("tiny.en", "float32", 4)

    mock_model.assert_called_once_with(
        "tiny.en", local_files_only=True, compute_type="float32", cpu_threads=4
    )
    assert result is mock_model.return_value


def test_load_whisper_model_uses_module_defaults():
    """Called without args, load_whisper_model uses the module constants."""
    with patch("easyspeak.core.config.WhisperModel") as mock_model:
        config.load_whisper_model()

    mock_model.assert_called_once_with(
        config.WHISPER_MODEL,
        local_files_only=True,
        compute_type=config.WHISPER_COMPUTE_TYPE,
        cpu_threads=config.WHISPER_CPU_THREADS,
    )


def test_load_whisper_model_downloads_when_missing_and_relaxed(monkeypatch, caplog):
    """Relaxed mode: an absent local model is re-fetched with downloads allowed."""
    monkeypatch.setattr(config, "NETWORK_ALLOWED", True)
    downloaded = object()
    with (
        patch(
            "easyspeak.core.config.WhisperModel",
            side_effect=[FileNotFoundError, downloaded],
        ) as mock_model,
        caplog.at_level("WARNING"),
    ):
        result = config.load_whisper_model("base.en", "int8", 0)

    assert result is downloaded
    assert mock_model.call_args_list[0].kwargs["local_files_only"] is True
    assert mock_model.call_args_list[1].kwargs["local_files_only"] is False
    assert "downloading" in caplog.text.lower()


def test_load_whisper_model_strict_raises_when_missing(monkeypatch):
    """Strict mode: an absent local model raises rather than downloading."""
    monkeypatch.setattr(config, "NETWORK_ALLOWED", False)
    with (
        patch(
            "easyspeak.core.config.WhisperModel", side_effect=FileNotFoundError
        ) as mock_model,
        pytest.raises(RuntimeError, match="EASYSPEAK_OFFLINE=relaxed"),
    ):
        config.load_whisper_model("base.en")

    mock_model.assert_called_once()


def test_offline_default_blocks_network(monkeypatch):
    """Unset EASYSPEAK_OFFLINE: defaults to strict, so no network access."""
    monkeypatch.delenv("EASYSPEAK_OFFLINE", raising=False)
    importlib.reload(config)
    assert config.NETWORK_ALLOWED is False


@pytest.mark.parametrize("value", ["relaxed", "RELAXED", "  relaxed  "])
def test_offline_relaxed_allows_network(monkeypatch, value):
    """EASYSPEAK_OFFLINE=relaxed (any case, trimmed) permits network access."""
    monkeypatch.setenv("EASYSPEAK_OFFLINE", value)
    importlib.reload(config)
    assert config.NETWORK_ALLOWED is True


def test_offline_unknown_value_stays_strict(monkeypatch):
    """Any value other than relaxed is treated as strict (no network)."""
    monkeypatch.setenv("EASYSPEAK_OFFLINE", "yes")
    importlib.reload(config)
    assert config.NETWORK_ALLOWED is False


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


def install_pack(models, code, whisper, voice):
    """Fake a language pack: a Whisper model directory and a Piper voice."""
    (models / code / "whisper" / whisper).mkdir(parents=True)
    (models / code / "piper").mkdir()
    (models / code / "piper" / f"{voice}.onnx").touch()


class TestLanguagePacks:
    """Which installed models `EASYSPEAK_LANGUAGE` selects.

    A pack drops its models beside the venv, so these fake that layout under a
    temporary `sys.prefix` and reload the module that reads it.
    """

    @pytest.fixture
    def models(self, tmp_path, monkeypatch):
        """Point the module at a temporary venv; return the models dir beside it."""
        monkeypatch.setattr(config.sys, "prefix", str(tmp_path / "venv"))
        monkeypatch.delenv("EASYSPEAK_MODELS_DIR", raising=False)
        monkeypatch.delenv("EASYSPEAK_WHISPER_MODEL", raising=False)
        monkeypatch.delenv("EASYSPEAK_PIPER_MODEL", raising=False)
        return tmp_path / "models"

    @pytest.fixture
    def packs(self, models):
        """Install an English and a German pack side by side."""
        install_pack(models, "en", "base.en", "en_US-amy-medium")
        install_pack(models, "de", "small", "de_DE-thorsten-medium")
        return models

    def test_defaults_to_english(self, monkeypatch):
        """Unset env: English, as before the setting existed."""
        monkeypatch.delenv("EASYSPEAK_LANGUAGE", raising=False)
        importlib.reload(config)
        assert config.LANGUAGE == "en"

    @pytest.mark.parametrize(
        ("language", "whisper"), [("en", "base.en"), ("de", "small")]
    )
    def test_listens_with_the_pack_of_the_language(
        self, packs, monkeypatch, language, whisper
    ):
        """Each language's Whisper model comes from its own pack directory."""
        monkeypatch.setenv("EASYSPEAK_LANGUAGE", language)
        importlib.reload(config)
        assert Path(config.WHISPER_MODEL) == packs / language / "whisper" / whisper

    def test_replies_with_the_voice_of_their_own_language(self, packs, monkeypatch):
        """A language with a pack but no translation gets English replies, in its voice."""
        install_pack(packs, "xx", "small", "xx_XX-nobody-medium")
        monkeypatch.setenv("EASYSPEAK_LANGUAGE", "xx")
        importlib.reload(config)
        assert config.REPLY_LANGUAGE == "en"
        assert (
            Path(config.PIPER_MODEL) == packs / "en" / "piper" / "en_US-amy-medium.onnx"
        )

    def test_translated_replies_need_their_languages_voice(self, packs, monkeypatch):
        """Italian is translated, but without its pack the replies stay English."""
        monkeypatch.setenv("EASYSPEAK_LANGUAGE", "it")
        importlib.reload(config)
        assert config.REPLY_LANGUAGE == "en"
        assert (
            Path(config.PIPER_MODEL) == packs / "en" / "piper" / "en_US-amy-medium.onnx"
        )

    def test_translated_replies_take_their_languages_voice(self, packs, monkeypatch):
        """German has a translation, so replies are German, in the German voice."""
        monkeypatch.setenv("EASYSPEAK_LANGUAGE", "de")
        importlib.reload(config)
        assert config.REPLY_LANGUAGE == "de"
        assert (
            Path(config.PIPER_MODEL)
            == packs / "de" / "piper" / "de_DE-thorsten-medium.onnx"
        )

    def test_models_dir_env_override(self, models, monkeypatch, tmp_path):
        """`EASYSPEAK_MODELS_DIR` finds packs installed anywhere else."""
        elsewhere = tmp_path / "elsewhere"
        install_pack(elsewhere, "de", "small", "de_DE-thorsten-medium")
        monkeypatch.setenv("EASYSPEAK_MODELS_DIR", str(elsewhere))
        monkeypatch.setenv("EASYSPEAK_LANGUAGE", "de")
        importlib.reload(config)
        assert Path(config.WHISPER_MODEL) == elsewhere / "de" / "whisper" / "small"

    @pytest.mark.parametrize(
        ("language", "whisper"), [("en", "base.en"), ("de", "small")]
    )
    def test_without_its_pack_falls_back_to_downloads(
        self, models, monkeypatch, language, whisper
    ):
        """Another language's pack does not count: the download name and the dev voice path."""
        install_pack(models, "fr", "small", "fr_FR-siwis-medium")
        monkeypatch.setenv("EASYSPEAK_LANGUAGE", language)
        importlib.reload(config)
        assert (config.WHISPER_MODEL, Path(config.PIPER_MODEL)) == (
            whisper,
            Path.home() / ".local/share/piper/en_US-amy-medium.onnx",
        )
