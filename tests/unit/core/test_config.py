"""Tests for the core config module."""

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

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
        "EASYSPEAK_STT",
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


def _install_parakeet(models_dir):
    """Lay down every file of the Parakeet model, empty, and return its directory."""
    model_dir = models_dir / "parakeet"
    model_dir.mkdir()
    for name in config.PARAKEET_FILES:
        (model_dir / name).touch()
    return model_dir


def test_stt_defaults_to_parakeet_when_its_model_is_installed(monkeypatch, tmp_path):
    """Unset EASYSPEAK_STT with the model on disk means Parakeet, no warning."""
    model_dir = _install_parakeet(tmp_path)
    monkeypatch.setenv("EASYSPEAK_MODELS_DIR", str(tmp_path))
    monkeypatch.setenv("EASYSPEAK_STT", "")
    importlib.reload(config)

    assert config.STT == "parakeet"
    assert model_dir == config.PARAKEET_MODEL_DIR
    assert config.STT_WARNINGS == []


def test_stt_defaults_to_parakeet_when_downloads_are_allowed(monkeypatch, tmp_path):
    """Relaxed mode fetches the Parakeet model on first start, as for Whisper."""
    monkeypatch.setenv("EASYSPEAK_MODELS_DIR", str(tmp_path))
    monkeypatch.setenv("EASYSPEAK_OFFLINE", "relaxed")
    importlib.reload(config)

    assert config.STT == "parakeet"
    assert config.STT_WARNINGS == []


@pytest.mark.parametrize("partial", [False, True])
def test_stt_falls_back_to_whisper_when_parakeet_is_missing_offline(
    monkeypatch, tmp_path, partial
):
    """A language pack alone still starts EasySpeak, on Whisper, with a warning.

    A directory left by an interrupted download is not an installed model either.
    """
    if partial:
        (tmp_path / "parakeet").mkdir()
        (tmp_path / "parakeet" / "config.json").touch()
    monkeypatch.setenv("EASYSPEAK_MODELS_DIR", str(tmp_path))
    monkeypatch.delenv("EASYSPEAK_OFFLINE", raising=False)
    importlib.reload(config)

    assert config.STT == "whisper"
    assert len(config.STT_WARNINGS) == 1
    assert "Parakeet model not installed" in config.STT_WARNINGS[0]
    assert "EASYSPEAK_OFFLINE=relaxed" in config.STT_WARNINGS[0]
    assert config.LANGUAGE_WARNINGS == []


@pytest.mark.parametrize("chosen", ["", "parakeet"])
@pytest.mark.parametrize("installed", [True, False])
def test_stt_uses_whisper_for_a_language_parakeet_lacks(
    monkeypatch, tmp_path, chosen, installed
):
    """Parakeet finds the language itself, among 25; Japanese is not one of them.

    That is the one reason given, whether or not the model happens to be there.
    """
    if installed:
        _install_parakeet(tmp_path)
    monkeypatch.setenv("EASYSPEAK_MODELS_DIR", str(tmp_path))
    monkeypatch.delenv("EASYSPEAK_OFFLINE", raising=False)
    monkeypatch.setenv("EASYSPEAK_LANGUAGE", "ja")
    monkeypatch.setenv("EASYSPEAK_STT", chosen)
    importlib.reload(config)

    assert config.STT == "whisper"
    assert config.STT_WARNINGS == ["Parakeet does not cover 'ja', using Whisper"]


def test_stt_stays_parakeet_for_every_pack_language(monkeypatch, tmp_path):
    """The five shipped language packs are all covered."""
    _install_parakeet(tmp_path)
    monkeypatch.setenv("EASYSPEAK_MODELS_DIR", str(tmp_path))
    for language in ["en", "de", "it", "fr", "es"]:
        monkeypatch.setenv("EASYSPEAK_LANGUAGE", language)
        importlib.reload(config)
        assert config.STT == "parakeet", language
        assert config.STT_WARNINGS == [], language


def test_stt_whisper_can_be_chosen_case_insensitively(monkeypatch):
    """`Whisper` and `whisper` select the same backend, without a warning."""
    monkeypatch.setenv("EASYSPEAK_STT", " Whisper ")
    importlib.reload(config)

    assert config.STT == "whisper"
    assert config.STT_WARNINGS == []


def test_unknown_stt_warns_and_uses_the_default(monkeypatch, tmp_path):
    """A typo in the backend name is reported at startup, then the default applies."""
    _install_parakeet(tmp_path)
    monkeypatch.setenv("EASYSPEAK_MODELS_DIR", str(tmp_path))
    monkeypatch.setenv("EASYSPEAK_STT", "vosk")
    importlib.reload(config)

    assert config.STT == "parakeet"
    assert config.STT_WARNINGS == [
        "Unknown speech recognition backend 'vosk' (EASYSPEAK_STT), using the default"
    ]


def test_load_parakeet_model_loads_an_installed_model_offline(tmp_path, caplog):
    """A directory holding the whole model is handed to onnx-asr as is."""
    model_dir = _install_parakeet(tmp_path)
    onnx_asr = MagicMock()
    with patch.dict(sys.modules, {"onnx_asr": onnx_asr}), caplog.at_level("WARNING"):
        result = config.load_parakeet_model(model_dir)

    onnx_asr.load_model.assert_called_once_with(
        config.PARAKEET_MODEL, model_dir, quantization="int8"
    )
    assert result is onnx_asr.load_model.return_value
    assert "downloading" not in caplog.text.lower()


def test_load_parakeet_model_reports_an_incomplete_download(monkeypatch, tmp_path):
    """onnx-asr would load an existing directory offline and fail on the missing file."""
    monkeypatch.setattr(config, "NETWORK_ALLOWED", True)
    model_dir = tmp_path / "parakeet"
    model_dir.mkdir()
    (model_dir / "config.json").touch()
    onnx_asr = MagicMock()
    with (
        patch.dict(sys.modules, {"onnx_asr": onnx_asr}),
        pytest.raises(RuntimeError, match=r"incomplete .* delete that directory"),
    ):
        config.load_parakeet_model(model_dir)

    onnx_asr.load_model.assert_not_called()


def test_load_parakeet_model_reports_what_onnx_asr_refuses(tmp_path):
    """A corrupt model directory ends in the daemon's clean exit, not a traceback."""
    model_dir = _install_parakeet(tmp_path)
    onnx_asr = MagicMock()
    onnx_asr.utils.ModelLoadingError = type("ModelLoadingError", (Exception,), {})
    onnx_asr.load_model.side_effect = onnx_asr.utils.ModelLoadingError("bad vocab")
    with (
        patch.dict(sys.modules, {"onnx_asr": onnx_asr}),
        pytest.raises(RuntimeError, match="cannot be loaded: bad vocab"),
    ):
        config.load_parakeet_model(model_dir)


def test_load_parakeet_model_strict_raises_when_missing(monkeypatch, tmp_path):
    """Strict mode: an absent model directory raises rather than downloading."""
    monkeypatch.setattr(config, "NETWORK_ALLOWED", False)
    onnx_asr = MagicMock()
    with (
        patch.dict(sys.modules, {"onnx_asr": onnx_asr}),
        pytest.raises(RuntimeError, match="EASYSPEAK_OFFLINE=relaxed"),
    ):
        config.load_parakeet_model(tmp_path / "parakeet")

    onnx_asr.load_model.assert_not_called()


def test_load_parakeet_model_downloads_when_missing_and_relaxed(
    monkeypatch, tmp_path, caplog
):
    """Relaxed mode: onnx-asr fetches the model into the directory, with a warning."""
    monkeypatch.setattr(config, "NETWORK_ALLOWED", True)
    onnx_asr = MagicMock()
    target = tmp_path / "parakeet"
    with patch.dict(sys.modules, {"onnx_asr": onnx_asr}), caplog.at_level("WARNING"):
        result = config.load_parakeet_model(target)

    onnx_asr.load_model.assert_called_once_with(
        config.PARAKEET_MODEL, target, quantization=config.PARAKEET_QUANTIZATION
    )
    assert result is onnx_asr.load_model.return_value
    assert "downloading" in caplog.text.lower()


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

    def test_unknown_code_is_reported_and_english_used(self, monkeypatch):
        """A code Whisper does not know would crash the first dictation; say so."""
        monkeypatch.setenv("EASYSPEAK_LANGUAGE", "xyz")
        importlib.reload(config)
        assert config.LANGUAGE == "en"
        assert config.LANGUAGE_WARNINGS == [
            "EASYSPEAK_LANGUAGE='xyz' is not a language code Whisper knows; using English"
        ]

    def test_untranslated_language_is_reported(self, packs, monkeypatch):
        """Portuguese dictation with English replies: the user is told why."""
        install_pack(packs, "pt", "small", "pt_PT-tugao-medium")
        monkeypatch.setenv("EASYSPEAK_LANGUAGE", "pt")
        importlib.reload(config)
        assert config.REPLY_LANGUAGE == "en"
        assert config.LANGUAGE_WARNINGS == [
            "Dictation in 'pt', replies in English (no 'pt' translation)"
        ]

    def test_missing_voice_pack_is_reported(self, packs, monkeypatch):
        """Italian is translated, but without its pack the user is told why."""
        monkeypatch.setenv("EASYSPEAK_LANGUAGE", "it")
        importlib.reload(config)
        assert config.REPLY_LANGUAGE == "en"
        assert config.LANGUAGE_WARNINGS == [
            "Dictation in 'it', replies in English (no 'it' language pack)"
        ]

    def test_both_reasons_in_one_warning(self, packs, monkeypatch):
        """Neither translation nor pack: one line, both reasons."""
        monkeypatch.setenv("EASYSPEAK_LANGUAGE", "pt")
        importlib.reload(config)
        assert config.LANGUAGE_WARNINGS == [
            "Dictation in 'pt', replies in English (no 'pt' translation, no 'pt' language pack)"
        ]

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
        install_pack(packs, "nl", "small", "nl_NL-mls-medium")
        monkeypatch.setenv("EASYSPEAK_LANGUAGE", "nl")
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

    def test_commands_follow_a_language_with_a_core_table(self, monkeypatch):
        """German has a core table: commands are decoded and prompted in German."""
        monkeypatch.setenv("EASYSPEAK_LANGUAGE", "de")
        importlib.reload(config)
        assert config.COMMAND_LANGUAGE == "de"
        assert config.COMMAND_PROMPT.startswith("nummern, scrollen")
        assert config.COMMAND_PROMPTS["en"].startswith("numbers, scroll")
        assert {"eins", "one", "zehn"} <= config.NUMBER_WORDS

    def test_commands_stay_english_without_a_core_table(self, monkeypatch):
        """Dutch has no core table: commands are decoded and prompted in English."""
        monkeypatch.setenv("EASYSPEAK_LANGUAGE", "nl")
        importlib.reload(config)
        assert config.COMMAND_LANGUAGE == "en"
        assert config.COMMAND_PROMPT.startswith("numbers, scroll")
        assert (
            frozenset(
                [
                    "zero",
                    "one",
                    "two",
                    "three",
                    "four",
                    "five",
                    "six",
                    "seven",
                    "eight",
                    "nine",
                    "ten",
                ]
            )
            == config.NUMBER_WORDS
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
