"""Tests for the core main module."""

import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pytest
from easyspeak.core.main import EasySpeak
from easyspeak.core.tray import TrayAction


class TestEasySpeakInit:
    """Tests for EasySpeak initialization."""

    def test_init(self):
        """Test that EasySpeak initializes with correct default values."""
        easy = EasySpeak()

        assert easy.plugins == []
        assert easy.whisper is None
        assert easy.wakeword is None
        assert easy.audio is None
        assert easy.stream is None
        assert easy.last_wake_time == 0


class TestEasySpeakUtilities:
    """Tests for EasySpeak utility methods."""

    @patch("subprocess.run")
    def test_host_run_foreground(self, mock_run):
        """Test host_run method in foreground mode."""
        easy = EasySpeak()
        mock_result = Mock(returncode=0, stdout="output", stderr="")
        mock_run.return_value = mock_result

        result = easy.host_run(["echo", "test"], background=False)

        mock_run.assert_called_once_with(
            ["echo", "test"], capture_output=True, text=True, env=None
        )
        assert result == mock_result

    @patch.dict(
        "os.environ",
        {
            "LD_LIBRARY_PATH": "/flake/lib",
            "GI_TYPELIB_PATH": "/flake/gi",
            "PATH": "/bin",
        },
        clear=True,
    )
    @patch("subprocess.Popen")
    def test_host_run_clean_env_strips_injected_paths(self, mock_popen):
        """clean_env drops EasySpeak's library paths so child apps use their own."""
        easy = EasySpeak()

        easy.host_run(["nautilus"], background=True, clean_env=True)

        env = mock_popen.call_args[1]["env"]
        assert "LD_LIBRARY_PATH" not in env
        assert "GI_TYPELIB_PATH" not in env
        assert env["PATH"] == "/bin"

    @patch("subprocess.Popen")
    def test_host_run_background(self, mock_popen):
        """Test host_run method in background mode."""
        easy = EasySpeak()
        mock_process = Mock()
        mock_popen.return_value = mock_process

        result = easy.host_run(["echo", "test"], background=True)

        mock_popen.assert_called_once()
        call_args = mock_popen.call_args
        assert call_args[0][0] == ["echo", "test"]
        assert call_args[1]["stdout"] == subprocess.DEVNULL
        assert call_args[1]["stderr"] == subprocess.DEVNULL
        assert result == mock_process

    def test_speak_delegates_to_pipeline(self):
        """EasySpeak.speak is a thin delegate to the speech pipeline."""
        easy = EasySpeak()
        easy.speech = Mock()

        easy.speak("hello")

        easy.speech.speak.assert_called_once_with("hello")

    def test_tap_key_returns_true_on_injection(self):
        """tap_key delegates to mediakeys and reports success."""
        easy = EasySpeak()

        with patch("easyspeak.core.mediakeys.tap_key") as mock_tap:
            result = easy.tap_key(115)

        assert result is True
        mock_tap.assert_called_once_with(115)

    def test_tap_key_returns_false_when_unavailable(self):
        """tap_key reports failure when injection raises (e.g. non-GNOME session)."""
        easy = EasySpeak()

        with patch("easyspeak.core.mediakeys.tap_key", side_effect=Exception):
            result = easy.tap_key(115)

        assert result is False

    def test_deactivate_delegates_to_tray(self):
        """EasySpeak.deactivate just queues a sleep on the tray controller."""
        easy = EasySpeak()
        easy.tray = Mock()

        easy.deactivate()

        easy.tray.request_sleep.assert_called_once()


class TestEasySpeakPlugins:
    """Tests for EasySpeak plugin management."""

    @patch("importlib.import_module")
    @patch("sys.path")
    def test_load_plugins_no_directory(self, mock_syspath, mock_import, readlog):
        """Test load_plugins when plugins directory doesn't exist."""
        easy = EasySpeak()

        # Mock plugins directory to not exist
        with patch.object(Path, "exists", return_value=False):
            easy.load_plugins()

        captured = readlog()
        assert "No plugins directory found" in captured.out
        assert easy.plugins == []

    @patch("importlib.import_module")
    @patch("sys.path")
    def test_load_plugins_valid_plugin(
        self, mock_syspath, mock_import, mock_plugin_with_setup, readlog
    ):
        """Test load_plugins with a valid plugin."""
        easy = EasySpeak()

        mock_import.return_value = mock_plugin_with_setup

        # Mock plugins directory
        mock_file = Mock()
        mock_file.name = "test_plugin.py"
        mock_file.stem = "test_plugin"

        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "glob", return_value=[mock_file]),
        ):
            easy.load_plugins()

        # Check that plugin was loaded
        assert len(easy.plugins) == 1
        assert easy.plugins[0] == mock_plugin_with_setup
        mock_plugin_with_setup.setup.assert_called_once_with(easy)

        captured = readlog()
        assert "✓ Loaded: TestPlugin" in captured.out

    @patch("importlib.import_module")
    @patch("sys.path")
    def test_load_plugins_skip_underscore_files(
        self, mock_syspath, mock_import, readlog
    ):
        """Test that files starting with underscore are skipped."""
        easy = EasySpeak()

        # Mock plugins directory with underscore file
        mock_file = Mock()
        mock_file.name = "_test_plugin.py"
        mock_file.stem = "_test_plugin"

        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "glob", return_value=[mock_file]),
        ):
            easy.load_plugins()

        # Check that no plugins were loaded
        assert easy.plugins == []
        mock_import.assert_not_called()

    @patch("importlib.import_module")
    @patch("sys.path")
    def test_load_plugins_invalid_plugin(self, mock_syspath, mock_import, readlog):
        """Test load_plugins with an invalid plugin (missing NAME or handle)."""
        easy = EasySpeak()

        # Mock plugin module without NAME or handle
        mock_plugin = Mock(spec=[])
        mock_import.return_value = mock_plugin

        # Mock plugins directory
        mock_file = Mock()
        mock_file.name = "invalid_plugin.py"
        mock_file.stem = "invalid_plugin"

        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "glob", return_value=[mock_file]),
        ):
            easy.load_plugins()

        # Check that plugin was not loaded
        assert easy.plugins == []

        captured = readlog()
        assert "Invalid plugin: invalid_plugin.py" in captured.out

    @patch("importlib.import_module")
    @patch("sys.path")
    def test_load_plugins_import_error(self, mock_syspath, mock_import, readlog):
        """Test load_plugins when import fails."""
        easy = EasySpeak()

        # Mock import to raise an exception
        mock_import.side_effect = ImportError("Test error")

        # Mock plugins directory
        mock_file = Mock()
        mock_file.name = "broken_plugin.py"
        mock_file.stem = "broken_plugin"

        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "glob", return_value=[mock_file]),
        ):
            easy.load_plugins()

        # Check that plugin was not loaded
        assert easy.plugins == []

        captured = readlog()
        assert "Failed to load broken_plugin.py" in captured.out

    def test_load_plugins_loads_all_shipped_plugins(self):
        """All shipped plugins are discovered against the real filesystem layout."""
        easy = EasySpeak()

        easy.load_plugins()
        loaded = {module.__name__.rsplit(".", 1)[-1] for module in easy.plugins}

        assert loaded == {
            "00_eyetrack",
            "00_mousegrid",
            "apps",
            "browser",
            "dictation",
            "files",
            "media",
            "sleep",
            "system",
            "zz_base",
        }

    def test_get_all_commands_empty(self):
        """Test get_all_commands with no plugins."""
        easy = EasySpeak()

        commands = easy.get_all_commands()

        assert commands == []

    def test_get_all_commands_with_plugins(
        self,
        mock_plugin_with_commands_12,
        mock_plugin_with_commands_34,
        mock_plugin_without_commands,
    ):
        """Test get_all_commands with plugins that have commands."""
        easy = EasySpeak()

        easy.plugins = [
            mock_plugin_with_commands_12,
            mock_plugin_with_commands_34,
            mock_plugin_without_commands,
        ]

        commands = easy.get_all_commands()

        assert commands == ["cmd1", "cmd2", "cmd3", "cmd4"]


class TestEasySpeakRouteCommand:
    """Tests for EasySpeak command routing."""

    def test_route_command_empty(self):
        """Test route_command with empty command."""
        easy = EasySpeak()

        result = easy.route_command("")

        assert result is True

    def test_route_command_strip_wake_words(self, mock_plugin):
        """Test that route_command strips wake words."""
        easy = EasySpeak()
        easy.plugins = [mock_plugin]

        # Test various wake word formats
        easy.route_command("hey jarvis test command")
        mock_plugin.handle.assert_called_with("test command", easy)

        easy.route_command("hey, jarvis, test command")
        mock_plugin.handle.assert_called_with("test command", easy)

        easy.route_command("jarvis test command")
        mock_plugin.handle.assert_called_with("test command", easy)

    def test_route_command_strip_punctuation(self, mock_plugin):
        """Test that route_command strips punctuation."""
        easy = EasySpeak()
        easy.plugins = [mock_plugin]

        easy.route_command("test command...")
        mock_plugin.handle.assert_called_with("test command", easy)

    def test_route_command_plugin_handles_true(self, mock_plugin):
        """Test route_command when plugin handles command and returns True."""
        easy = EasySpeak()
        easy.plugins = [mock_plugin]

        result = easy.route_command("test command")

        assert result is True
        mock_plugin.handle.assert_called_once()

    def test_route_command_plugin_handles_false(self, mock_plugin_exit):
        """Test route_command when plugin handles command and returns False (exit)."""
        easy = EasySpeak()
        easy.plugins = [mock_plugin_exit]

        result = easy.route_command("exit")

        assert result is False
        mock_plugin_exit.handle.assert_called_once()

    @patch.object(EasySpeak, "speak")
    def test_route_command_no_matching_plugin(self, mock_speak, mock_plugin_no_handle):
        """Test route_command when no plugin handles the command."""
        easy = EasySpeak()
        easy.plugins = [mock_plugin_no_handle]

        result = easy.route_command("unknown command")

        assert result is True
        mock_speak.assert_called_once_with("Sorry, I didn't understand.")
        assert easy.keep_listening is False

    @patch.object(EasySpeak, "speak")
    def test_route_command_plugin_error(
        self, mock_speak, mock_plugin_with_error, readlog
    ):
        """Test route_command when plugin raises an exception."""
        easy = EasySpeak()
        easy.plugins = [mock_plugin_with_error]

        result = easy.route_command("test command")

        captured = readlog()
        assert "Plugin error (TestPlugin)" in captured.out
        assert result is True
        mock_speak.assert_called_once()

    def test_route_command_multiple_plugins(self, mock_multiple_plugins):
        """Test route_command with multiple plugins."""
        easy = EasySpeak()
        easy.plugins = mock_multiple_plugins
        result = easy.route_command("test command")

        assert result is True
        mock_multiple_plugins[0].handle.assert_called_once()
        mock_multiple_plugins[1].handle.assert_called_once()

    @patch.object(EasySpeak, "_show_help")
    @patch.object(EasySpeak, "speak")
    @patch("time.time")
    def test_route_command_second_miss_shows_help_and_keeps_listening(
        self, mock_time, mock_speak, mock_show_help, mock_plugin_no_handle
    ):
        """A second miss (spaced past the grace window) escalates to help and
        re-arms listening."""
        easy = EasySpeak()
        easy.plugins = [mock_plugin_no_handle]
        mock_time.side_effect = [100.0, 200.0]

        easy.route_command("first gibberish")
        result = easy.route_command("second gibberish")

        assert result is True
        assert mock_speak.call_args_list == [
            (("Sorry, I didn't understand.",),),
            (("I didn't understand.",),),
        ]
        mock_show_help.assert_called_once_with()
        assert easy.keep_listening is True
        assert easy.help_shown is True

    @patch.object(EasySpeak, "_show_help")
    @patch.object(EasySpeak, "speak")
    @patch("time.time")
    def test_route_command_does_not_repeat_help_after_first_escalation(
        self, mock_time, mock_speak, mock_show_help, mock_plugin_no_handle
    ):
        """Once help has been shown, further misses only apologise (no repeat)
        but still keep the mic open for another try."""
        easy = EasySpeak()
        easy.plugins = [mock_plugin_no_handle]
        mock_time.side_effect = [100.0, 200.0, 300.0]

        easy.route_command("miss one")
        easy.route_command("miss two")
        easy.keep_listening = False
        easy.route_command("miss three")

        mock_show_help.assert_called_once_with()
        assert mock_speak.call_args_list == [
            (("Sorry, I didn't understand.",),),
            (("I didn't understand.",),),
            (("I didn't understand.",),),
        ]
        assert easy.keep_listening is True

    @patch.object(EasySpeak, "speak")
    @patch("time.time")
    def test_route_command_drops_misses_inside_the_grace_window(
        self, mock_time, mock_speak, mock_plugin_no_handle
    ):
        """A miss arriving within the grace window of the last one (e.g. the mic
        hearing our own apology) is silently dropped — no feedback, no escalation."""
        easy = EasySpeak()
        easy.plugins = [mock_plugin_no_handle]
        mock_time.side_effect = [100.0, 101.0]  # 1s apart, inside the grace window

        easy.route_command("real miss")
        easy.route_command("sorry i didn't understand")

        mock_speak.assert_called_once_with("Sorry, I didn't understand.")
        assert easy.misunderstand_count == 1
        assert easy.help_shown is False
        assert easy.keep_listening is False
        assert easy.unrecognized is False

    @patch.object(EasySpeak, "_show_help")
    @patch.object(EasySpeak, "speak")
    @patch("time.time")
    def test_route_command_understood_resets_streak_and_help(
        self, mock_time, mock_speak, mock_show_help, mock_plugin_no_handle, mock_plugin
    ):
        """An understood command clears the streak and re-arms help for next
        time (a successful 'help' command therefore lets it show again)."""
        easy = EasySpeak()
        easy.plugins = [mock_plugin_no_handle]
        mock_time.side_effect = [100.0, 200.0]

        easy.route_command("miss one")
        easy.route_command("miss two")
        assert easy.misunderstand_count == 2
        assert easy.help_shown is True

        easy.plugins = [mock_plugin]  # this one handles it
        easy.route_command("good command")

        assert easy.misunderstand_count == 0
        assert easy.help_shown is False

    def test_show_help_delegates_to_plugin_that_provides_it(self):
        """_show_help calls show_help on the first plugin that exposes it."""
        easy = EasySpeak()
        without = Mock(spec=[])  # no show_help attribute
        with_help = Mock(spec=["show_help"])
        easy.plugins = [without, with_help]

        easy._show_help()

        with_help.show_help.assert_called_once_with(easy)


class TestEasySpeakAudio:
    """Tests for EasySpeak audio methods."""

    def test_flush_stream_success(self):
        """Test flush_stream successfully flushes audio buffer."""
        easy = EasySpeak()

        # Mock stream
        easy.stream = Mock()
        easy.stream.get_read_available.return_value = 1280
        easy.stream.read.return_value = b"\x00\x00" * 1280

        easy.flush_stream()

        # Verify stream was read
        easy.stream.get_read_available.assert_called_once()
        easy.stream.read.assert_called_once_with(1280, exception_on_overflow=False)

    def test_flush_stream_exception(self):
        """Test flush_stream handles exceptions gracefully."""
        easy = EasySpeak()

        # Mock stream that raises exception
        easy.stream = Mock()
        easy.stream.get_read_available.return_value = 1280
        easy.stream.read.side_effect = Exception("Stream error")

        # Should not raise exception
        easy.flush_stream()

        # Verify read was attempted
        easy.stream.read.assert_called_once()

    def test_close_stream_releases_microphone(self):
        """_close_stream stops and closes the open stream, then clears it so the
        mic (and GNOME's privacy indicator) is freed."""
        easy = EasySpeak()
        stream = Mock()
        easy.stream = stream

        easy._close_stream()

        stream.stop_stream.assert_called_once()
        stream.close.assert_called_once()
        assert easy.stream is None

    def test_close_stream_swallows_oserror(self):
        """A failing stop_stream is ignored, close() still runs to release the
        resources, and the handle is cleared."""
        easy = EasySpeak()
        stream = Mock()
        stream.stop_stream.side_effect = OSError("already closed")
        easy.stream = stream

        easy._close_stream()  # must not raise

        stream.close.assert_called_once()
        assert easy.stream is None

    def test_close_stream_noop_when_already_closed(self):
        """With no stream open, _close_stream is a safe no-op."""
        easy = EasySpeak()
        easy.stream = None

        easy._close_stream()

        assert easy.stream is None

    def test_is_silence_true(self):
        """Test is_silence returns True for quiet audio."""
        easy = EasySpeak()

        # Create quiet audio chunk
        audio_chunk = np.array([10, -10, 5, -5], dtype=np.int16)

        result = easy.is_silence(audio_chunk)

        # Use == instead of is because numpy returns np.bool_ type
        assert result == True  # noqa: E712

    def test_is_silence_false(self):
        """Test is_silence returns False for loud audio."""
        easy = EasySpeak()

        # Create loud audio chunk
        audio_chunk = np.array([1000, -1000, 500, -500], dtype=np.int16)

        result = easy.is_silence(audio_chunk)

        # Use == instead of is because numpy returns np.bool_ type
        assert result == False  # noqa: E712

    def test_record_until_silence(self):
        """Test record_until_silence method."""
        easy = EasySpeak()

        # Mock stream
        easy.stream = Mock()

        # Create audio data - first few chunks are loud, then silent
        loud_audio = np.array([1000] * 1600, dtype=np.int16).tobytes()
        silent_audio = np.array([10] * 1600, dtype=np.int16).tobytes()

        # Return loud audio for first 10 chunks, then silent
        audio_sequence = [loud_audio] * 10 + [silent_audio] * 10
        easy.stream.read = Mock(side_effect=audio_sequence)

        result = easy.record_until_silence()

        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_wait_for_speech_found(self):
        """Test wait_for_speech when speech is detected."""
        easy = EasySpeak()

        # Mock stream
        easy.stream = Mock()

        # First chunk is silent, second is loud
        silent_audio = np.array([10] * 1600, dtype=np.int16).tobytes()
        loud_audio = np.array([1000] * 1600, dtype=np.int16).tobytes()

        easy.stream.read = Mock(side_effect=[silent_audio, loud_audio])

        result = easy.wait_for_speech(timeout=5)

        assert result == loud_audio

    def test_wait_for_speech_timeout(self):
        """Test wait_for_speech when no speech is detected (timeout)."""
        easy = EasySpeak()

        # Mock stream
        easy.stream = Mock()

        # All chunks are silent
        silent_audio = np.array([10] * 1600, dtype=np.int16).tobytes()
        easy.stream.read = Mock(return_value=silent_audio)

        result = easy.wait_for_speech(timeout=0.1)  # Short timeout for testing

        assert result is None

    @patch("wave.open")
    @patch("os.remove")
    @patch("tempfile.NamedTemporaryFile")
    def test_transcribe(self, mock_tempfile, mock_remove, mock_wave):
        """Test transcribe method."""
        easy = EasySpeak()

        # Mock whisper model
        easy.whisper = Mock()
        mock_segment = Mock()
        mock_segment.text = "Hello world"
        easy.whisper.transcribe = Mock(return_value=([mock_segment], None))

        # Mock temporary file
        mock_file = Mock()
        mock_file.name = "/tmp/test.wav"
        mock_tempfile.return_value.__enter__.return_value = mock_file

        # Mock wave file
        mock_wf = Mock()
        mock_wave.return_value.__enter__.return_value = mock_wf

        # Test transcription
        audio_data = b"test audio data"
        result = easy.transcribe(audio_data)

        assert result == "Hello world"
        mock_remove.assert_called_once_with("/tmp/test.wav")

    @patch("wave.open")
    @patch("os.remove")
    @patch("tempfile.NamedTemporaryFile")
    def test_transcribe_with_custom_prompt(self, mock_tempfile, mock_remove, mock_wave):
        """Test transcribe method with custom prompt."""
        easy = EasySpeak()

        # Mock whisper model
        easy.whisper = Mock()
        mock_segment = Mock()
        mock_segment.text = "Custom prompt test"
        easy.whisper.transcribe = Mock(return_value=([mock_segment], None))

        # Mock temporary file
        mock_file = Mock()
        mock_file.name = "/tmp/test.wav"
        mock_tempfile.return_value.__enter__.return_value = mock_file

        # Mock wave file
        mock_wf = Mock()
        mock_wave.return_value.__enter__.return_value = mock_wf

        # Test transcription with custom prompt
        audio_data = b"test audio data"
        custom_prompt = "custom prompt"
        result = easy.transcribe(audio_data, prompt=custom_prompt)

        assert result == "Custom prompt test"

        # Check that whisper was called with custom prompt
        call_args = easy.whisper.transcribe.call_args
        assert call_args[1]["initial_prompt"] == custom_prompt

    @patch("wave.open")
    @patch("os.remove")
    @patch("tempfile.NamedTemporaryFile")
    def test_transcribe_multiple_segments(self, mock_tempfile, mock_remove, mock_wave):
        """Test transcribe method with multiple segments."""
        easy = EasySpeak()

        # Mock whisper model with multiple segments
        easy.whisper = Mock()
        segment1 = Mock()
        segment1.text = "Hello"
        segment2 = Mock()
        segment2.text = " world"
        easy.whisper.transcribe = Mock(return_value=([segment1, segment2], None))

        # Mock temporary file
        mock_file = Mock()
        mock_file.name = "/tmp/test.wav"
        mock_tempfile.return_value.__enter__.return_value = mock_file

        # Mock wave file
        mock_wf = Mock()
        mock_wave.return_value.__enter__.return_value = mock_wf

        # Test transcription
        audio_data = b"test audio data"
        result = easy.transcribe(audio_data)

        # The join adds a space between segments
        assert result == "Hello  world"


class TestEasySpeakRun:
    """Tests for EasySpeak run method."""

    @pytest.fixture(autouse=True)
    def _stub_speech_warmup(self):
        """Keep run() from spawning the real piper/player pipeline at startup."""
        with patch("easyspeak.core.speech.SpeechPipeline.ensure") as mock_ensure:
            yield mock_ensure

    @pytest.fixture(autouse=True)
    def _stub_speech_speak(self):
        """Silence the startup greeting (tray.started speaks); the warmup stub
        leaves the pipeline with no process for it to write to."""
        with patch("easyspeak.core.speech.SpeechPipeline.speak") as mock_speak:
            yield mock_speak

    @pytest.fixture(autouse=True)
    def _stub_ensure_extension(self):
        """Keep run() from touching gnome-extensions / systemctl at startup."""
        with patch("easyspeak.core.main.ensure_extension") as mock_ensure_ext:
            yield mock_ensure_ext

    @pytest.fixture(autouse=True)
    def _stub_hotkey(self):
        """Keep run() from reading real /dev/input; hotkey has its own tests.

        take_activation() defaults to False so the loop never enters the
        push-to-talk branch unless a test opts in.
        """
        with patch("easyspeak.core.main.HotkeyListener") as mock_cls:
            listener = mock_cls.return_value
            listener.take_activation.return_value = False
            yield listener

    @patch("subprocess.run")
    @patch("easyspeak.core.main.pyaudio")
    @patch("easyspeak.core.main.WakeWordModel")
    @patch("easyspeak.core.main.load_whisper_model")
    @patch.object(EasySpeak, "load_plugins")
    @patch.object(EasySpeak, "_reset_detector")
    @patch.object(EasySpeak, "_run_push_to_talk")
    def test_run_hotkey_activation_runs_push_to_talk(
        self,
        mock_ptt,
        mock_reset,
        mock_load_plugins,
        mock_whisper_model,
        mock_wakeword_model,
        mock_pyaudio,
        mock_subprocess_run,
        mock_plugin,
        _stub_hotkey,
    ):
        """A hotkey press runs push-to-talk and skips wake-word detection."""
        easy = EasySpeak()
        easy.plugins = [mock_plugin]

        # Fire the hotkey on the first iteration, then fall through to a read
        # that ends the loop on the next iteration.
        _stub_hotkey.take_activation.side_effect = [True, False]

        mock_stream = Mock()
        mock_stream.read.side_effect = KeyboardInterrupt()
        mock_audio = Mock()
        mock_audio.open.return_value = mock_stream
        mock_pyaudio.PyAudio.return_value = mock_audio

        easy.run()

        mock_ptt.assert_called_once_with()
        _stub_hotkey.start.assert_called_once_with()
        _stub_hotkey.stop.assert_called_once_with()

    @patch("easyspeak.core.main.WakeWordModel")
    @patch("easyspeak.core.main.load_whisper_model")
    @patch.object(EasySpeak, "load_plugins")
    def test_run_ensures_extension(
        self,
        mock_load_plugins,
        mock_whisper_model,
        mock_wakeword_model,
        _stub_ensure_extension,
    ):
        """run() installs/enables the GNOME extension before loading plugins."""
        easy = EasySpeak()
        easy.plugins = []  # exit early after the ensure call

        easy.run()

        _stub_ensure_extension.assert_called_once_with()

    @patch("easyspeak.core.main.WakeWordModel")
    @patch("easyspeak.core.main.load_whisper_model")
    @patch.object(EasySpeak, "load_plugins")
    def test_run_no_plugins(
        self, mock_load_plugins, mock_whisper_model, mock_wakeword_model, readlog
    ):
        """Test run method exits early when no plugins are loaded."""
        easy = EasySpeak()

        # Mock that no plugins were loaded
        mock_load_plugins.return_value = None
        easy.plugins = []

        easy.run()

        # Check that models were initialized
        mock_wakeword_model.assert_called_once()
        mock_whisper_model.assert_called_once()
        mock_load_plugins.assert_called_once()

        # Check output
        captured = readlog()
        assert "No plugins loaded. Exiting." in captured.out

    @patch("subprocess.run")
    @patch("easyspeak.core.main.pyaudio")
    @patch("easyspeak.core.main.WakeWordModel")
    @patch("easyspeak.core.main.load_whisper_model")
    @patch.object(EasySpeak, "load_plugins")
    def test_run_warms_up_speech(
        self,
        mock_load_plugins,
        mock_whisper_model,
        mock_wakeword_model,
        mock_pyaudio,
        mock_subprocess_run,
        mock_plugin,
        _stub_speech_warmup,
    ):
        """When run starts with plugins then the speech pipeline is warmed up once."""
        easy = EasySpeak()
        easy.plugins = [mock_plugin]

        mock_stream = Mock()
        mock_stream.read.side_effect = KeyboardInterrupt()
        mock_audio = Mock()
        mock_audio.open.return_value = mock_stream
        mock_pyaudio.PyAudio.return_value = mock_audio

        easy.run()

        _stub_speech_warmup.assert_called_once()

    @patch("subprocess.run")
    @patch("easyspeak.core.main.pyaudio")
    @patch("easyspeak.core.main.WakeWordModel")
    @patch("easyspeak.core.main.load_whisper_model")
    @patch.object(EasySpeak, "load_plugins")
    def test_run_survives_speech_warmup_failure(
        self,
        mock_load_plugins,
        mock_whisper_model,
        mock_wakeword_model,
        mock_pyaudio,
        mock_subprocess_run,
        mock_plugin,
        _stub_speech_warmup,
        readlog,
    ):
        """When warmup fails (e.g. piper missing) then run still starts."""
        _stub_speech_warmup.side_effect = OSError()
        easy = EasySpeak()
        easy.plugins = [mock_plugin]

        mock_stream = Mock()
        mock_stream.read.side_effect = KeyboardInterrupt()
        mock_audio = Mock()
        mock_audio.open.return_value = mock_stream
        mock_pyaudio.PyAudio.return_value = mock_audio

        easy.run()  # must not raise

        assert "Speech unavailable" in readlog().out

    @patch("subprocess.run")
    @patch("easyspeak.core.main.pyaudio")
    @patch("easyspeak.core.main.WakeWordModel")
    @patch("easyspeak.core.main.load_whisper_model")
    @patch.object(EasySpeak, "load_plugins")
    def test_run_with_keyboard_interrupt(
        self,
        mock_load_plugins,
        mock_whisper_model,
        mock_wakeword_model,
        mock_pyaudio,
        mock_subprocess_run,
        mock_plugin,
        readlog,
    ):
        """Test run method handles KeyboardInterrupt gracefully."""
        easy = EasySpeak()
        easy.plugins = [mock_plugin]

        # Mock PyAudio and stream
        mock_audio = Mock()
        mock_stream = Mock()
        mock_stream.read.side_effect = KeyboardInterrupt()
        mock_audio.open.return_value = mock_stream
        mock_pyaudio.PyAudio.return_value = mock_audio

        easy.run()

        # Check that audio was properly terminated
        mock_stream.stop_stream.assert_called_once()
        mock_stream.close.assert_called_once()
        mock_audio.terminate.assert_called_once()

        # Check output
        captured = readlog()
        assert "Bye!" in captured.out

    @patch("subprocess.run")
    @patch("time.time")
    @patch("easyspeak.core.main.pyaudio")
    @patch("easyspeak.core.main.WakeWordModel")
    @patch("easyspeak.core.main.load_whisper_model")
    @patch.object(EasySpeak, "load_plugins")
    @patch.object(EasySpeak, "wait_for_speech")
    @patch.object(EasySpeak, "record_until_silence")
    @patch.object(EasySpeak, "transcribe")
    @patch.object(EasySpeak, "route_command")
    @patch.object(EasySpeak, "flush_stream")
    def test_run_wake_word_detected_with_command(
        self,
        mock_flush_stream,
        mock_route_command,
        mock_transcribe,
        mock_record,
        mock_wait,
        mock_load_plugins,
        mock_whisper_model,
        mock_wakeword_model,
        mock_pyaudio,
        mock_time,
        mock_subprocess_run,
        mock_plugin,
        readlog,
    ):
        """Test run method when wake word is detected and command is processed."""
        easy = EasySpeak()
        easy.plugins = [mock_plugin]

        # Mock time for cooldown
        mock_time.return_value = 100.0

        # Mock PyAudio and stream
        mock_audio = Mock()
        mock_stream = Mock()

        # Need multiple reads: initial loop read, second loop (interrupt)
        pcm_data = b"\x00\x00" * 1280
        mock_stream.read.side_effect = [
            pcm_data,  # First read in main loop
            KeyboardInterrupt(),  # Second loop iteration
        ]
        mock_audio.open.return_value = mock_stream
        mock_pyaudio.PyAudio.return_value = mock_audio

        # Mock wake word model to detect wake word on first call
        mock_wakeword_instance = Mock()
        mock_wakeword_instance.predict.return_value = {"hey_jarvis": 0.8}
        mock_wakeword_model.return_value = mock_wakeword_instance

        # Speech once (handled), then silence ends the follow-up window.
        mock_wait.side_effect = [b"audio_data", None]
        mock_record.return_value = b"more_audio"
        mock_transcribe.return_value = "test command"
        mock_route_command.return_value = True

        easy.run()

        # Check that wake word was detected
        captured = readlog()
        assert "Wake!" in captured.out
        assert "test command" in captured.out

        # Check that methods were called
        mock_wait.assert_called_with(timeout=5)
        mock_record.assert_called_once()
        mock_transcribe.assert_called_once()
        mock_route_command.assert_called_once()

        # Check that flush_stream was called (3 times: after wake, after beep, after command)
        assert mock_flush_stream.call_count == 3

        # Check cleanup
        mock_stream.stop_stream.assert_called_once()
        mock_stream.close.assert_called_once()
        mock_audio.terminate.assert_called_once()

    @patch("subprocess.run")
    @patch("time.time")
    @patch("easyspeak.core.main.pyaudio")
    @patch("easyspeak.core.main.WakeWordModel")
    @patch("easyspeak.core.main.load_whisper_model")
    @patch.object(EasySpeak, "load_plugins")
    @patch.object(EasySpeak, "wait_for_speech")
    @patch.object(EasySpeak, "record_until_silence")
    @patch.object(EasySpeak, "transcribe")
    @patch.object(EasySpeak, "route_command")
    @patch.object(EasySpeak, "flush_stream")
    def test_run_keeps_listening_after_help(
        self,
        mock_flush_stream,
        mock_route_command,
        mock_transcribe,
        mock_record,
        mock_wait,
        mock_load_plugins,
        mock_whisper_model,
        mock_wakeword_model,
        mock_pyaudio,
        mock_time,
        mock_subprocess_run,
        mock_plugin,
    ):
        """When route_command re-arms keep_listening (help shown), the loop
        drains speech and listens for a follow-up command without a new wake
        word."""
        easy = EasySpeak()
        easy.plugins = [mock_plugin]
        easy.speech = Mock()
        mock_time.return_value = 100.0

        mock_audio = Mock()
        mock_stream = Mock()
        pcm_data = b"\x00\x00" * 1280
        mock_stream.read.side_effect = [pcm_data, KeyboardInterrupt()]
        mock_audio.open.return_value = mock_stream
        mock_pyaudio.PyAudio.return_value = mock_audio

        mock_wakeword_instance = Mock()
        mock_wakeword_instance.predict.return_value = {"hey_jarvis": 0.8}
        mock_wakeword_model.return_value = mock_wakeword_instance

        mock_wait.return_value = b"audio_data"
        mock_record.return_value = b"more_audio"
        mock_transcribe.return_value = "gibberish"

        def route(_cmd):
            """First call mimics a help-miss (re-arms the loop); the second
            speaks a reply, which ends the session rather than keeping the mic."""
            if mock_route_command.call_count == 1:
                easy.unrecognized = True
                easy.keep_listening = True
            else:
                easy.speak("done")
            return True

        mock_route_command.side_effect = route

        easy.run()

        assert mock_route_command.call_count == 2
        assert mock_wait.call_count == 2
        # Once between the two captures, once on shutdown.
        assert easy.speech.drain.call_count == 2

    @patch("subprocess.run")
    @patch("time.time")
    @patch("easyspeak.core.main.pyaudio")
    @patch("easyspeak.core.main.WakeWordModel")
    @patch("easyspeak.core.main.load_whisper_model")
    @patch.object(EasySpeak, "load_plugins")
    @patch.object(EasySpeak, "wait_for_speech")
    @patch.object(EasySpeak, "record_until_silence")
    @patch.object(EasySpeak, "transcribe")
    @patch.object(EasySpeak, "route_command")
    @patch.object(EasySpeak, "flush_stream")
    def test_run_drains_after_an_unrecognised_command(
        self,
        mock_flush_stream,
        mock_route_command,
        mock_transcribe,
        mock_record,
        mock_wait,
        mock_load_plugins,
        mock_whisper_model,
        mock_wakeword_model,
        mock_pyaudio,
        mock_time,
        mock_subprocess_run,
        mock_plugin,
    ):
        """A single unrecognised command drains speech before resuming the wake
        word, so the still-playing apology can't be misheard into an escalation.
        """
        easy = EasySpeak()
        easy.plugins = [mock_plugin]
        easy.speech = Mock()
        mock_time.return_value = 100.0

        mock_audio = Mock()
        mock_stream = Mock()
        pcm_data = b"\x00\x00" * 1280
        mock_stream.read.side_effect = [pcm_data, KeyboardInterrupt()]
        mock_audio.open.return_value = mock_stream
        mock_pyaudio.PyAudio.return_value = mock_audio

        mock_wakeword_instance = Mock()
        mock_wakeword_instance.predict.return_value = {"hey_jarvis": 0.8}
        mock_wakeword_model.return_value = mock_wakeword_instance

        mock_wait.return_value = b"audio_data"
        mock_record.return_value = b"more_audio"
        mock_transcribe.return_value = "gibberish"

        def route(_cmd):
            """A soft-apology miss: sets unrecognized but never keep_listening."""
            easy.unrecognized = True
            return True

        mock_route_command.side_effect = route

        easy.run()

        assert easy.keep_listening is False
        # Once after the miss, once on shutdown — though we never kept listening.
        assert easy.speech.drain.call_count == 2

    @patch("subprocess.run")
    @patch("time.time")
    @patch("easyspeak.core.main.pyaudio")
    @patch("easyspeak.core.main.WakeWordModel")
    @patch("easyspeak.core.main.load_whisper_model")
    @patch.object(EasySpeak, "load_plugins")
    @patch.object(EasySpeak, "wait_for_speech")
    @patch.object(EasySpeak, "record_until_silence")
    @patch.object(EasySpeak, "transcribe")
    @patch.object(EasySpeak, "route_command")
    @patch.object(EasySpeak, "flush_stream")
    def test_run_follow_up_pumps_silent_commands_then_idles_out(
        self,
        mock_flush_stream,
        mock_route_command,
        mock_transcribe,
        mock_record,
        mock_wait,
        mock_load_plugins,
        mock_whisper_model,
        mock_wakeword_model,
        mock_pyaudio,
        mock_time,
        mock_subprocess_run,
        mock_plugin,
    ):
        """A silent recognized command keeps the mic open; an empty follow-up
        (e.g. the volume chime) is tolerated, and the session ends once the
        quiet rounds reach the idle limit — no new wake word in between."""
        easy = EasySpeak()
        easy.plugins = [mock_plugin]
        mock_time.return_value = 100.0

        mock_audio = Mock()
        mock_stream = Mock()
        pcm_data = b"\x00\x00" * 1280
        mock_stream.read.side_effect = [pcm_data, KeyboardInterrupt()]
        mock_audio.open.return_value = mock_stream
        mock_pyaudio.PyAudio.return_value = mock_audio

        mock_wakeword_instance = Mock()
        mock_wakeword_instance.predict.return_value = {"hey_jarvis": 0.8}
        mock_wakeword_model.return_value = mock_wakeword_instance

        # "louder" (handled) then two empty rounds (chime / quiet) end it.
        mock_wait.return_value = b"audio_data"
        mock_record.return_value = b"more_audio"
        mock_transcribe.side_effect = ["louder", "", ""]
        mock_route_command.return_value = True  # silent: never calls speak

        easy.run()

        # The command fired once; the empty rounds drove the idle-out, no wake.
        mock_route_command.assert_called_once()
        assert mock_transcribe.call_count == 3
        assert easy.keep_listening is False

    @patch("subprocess.run")
    @patch("time.time")
    @patch("easyspeak.core.main.pyaudio")
    @patch("easyspeak.core.main.WakeWordModel")
    @patch("easyspeak.core.main.load_whisper_model")
    @patch.object(EasySpeak, "load_plugins")
    @patch.object(EasySpeak, "wait_for_speech")
    @patch.object(EasySpeak, "speak")
    @patch.object(EasySpeak, "flush_stream")
    def test_run_wake_word_detected_no_speech(
        self,
        mock_flush_stream,
        mock_speak,
        mock_wait,
        mock_load_plugins,
        mock_whisper_model,
        mock_wakeword_model,
        mock_pyaudio,
        mock_time,
        mock_subprocess_run,
        mock_plugin,
        readlog,
    ):
        """Test run method when wake word is detected but no speech follows."""
        easy = EasySpeak()
        easy.plugins = [mock_plugin]

        # Mock time for cooldown
        mock_time.return_value = 100.0

        # Mock PyAudio and stream
        mock_audio = Mock()
        mock_stream = Mock()

        # Multiple reads: initial loop read, second loop (interrupt)
        pcm_data = b"\x00\x00" * 1280
        mock_stream.read.side_effect = [
            pcm_data,  # First read in main loop
            KeyboardInterrupt(),  # Second loop iteration
        ]
        mock_audio.open.return_value = mock_stream
        mock_pyaudio.PyAudio.return_value = mock_audio

        # Mock wake word model to detect wake word
        mock_wakeword_instance = Mock()
        mock_wakeword_instance.predict.return_value = {"hey_jarvis": 0.8}
        mock_wakeword_model.return_value = mock_wakeword_instance

        # Mock no speech detected
        mock_wait.return_value = None

        easy.run()

        # The startup greeting precedes the loop's "didn't hear anything".
        assert mock_speak.call_args_list == [
            (("Welcome! I'm ready.",),),
            (("I didn't hear anything.",),),
        ]

        # Check that flush_stream was called (2 times: after wake, after beep)
        assert mock_flush_stream.call_count == 2

        # Check cleanup
        mock_stream.stop_stream.assert_called_once()
        mock_stream.close.assert_called_once()
        mock_audio.terminate.assert_called_once()

    @patch("subprocess.run")
    @patch("time.time")
    @patch("easyspeak.core.main.pyaudio")
    @patch("easyspeak.core.main.WakeWordModel")
    @patch("easyspeak.core.main.load_whisper_model")
    @patch.object(EasySpeak, "load_plugins")
    @patch.object(EasySpeak, "wait_for_speech")
    @patch.object(EasySpeak, "record_until_silence")
    @patch.object(EasySpeak, "transcribe")
    @patch.object(EasySpeak, "route_command")
    @patch.object(EasySpeak, "flush_stream")
    def test_run_wake_word_cooldown(
        self,
        mock_flush_stream,
        mock_route_command,
        mock_transcribe,
        mock_record,
        mock_wait,
        mock_load_plugins,
        mock_whisper_model,
        mock_wakeword_model,
        mock_pyaudio,
        mock_time,
        mock_subprocess_run,
        mock_plugin,
    ):
        """Test run method respects wake word cooldown period."""
        easy = EasySpeak()
        easy.plugins = [mock_plugin]

        # Mock time to simulate cooldown - first call within cooldown, second after
        mock_time.side_effect = [
            100.0,
            101.0,
            105.0,
        ]  # 101 is within cooldown, 105 is after
        easy.last_wake_time = 100.0

        # Mock PyAudio and stream
        mock_audio = Mock()
        mock_stream = Mock()

        # Multiple reads: first triggers cooldown skip, second triggers processing, then interrupt
        pcm_data = b"\x00\x00" * 1280
        mock_stream.read.side_effect = [
            pcm_data,  # First read - within cooldown, skip
            pcm_data,  # Second read - after cooldown, process
            pcm_data,  # Loop back for next iteration
            KeyboardInterrupt(),  # Exit
        ]
        mock_audio.open.return_value = mock_stream
        mock_pyaudio.PyAudio.return_value = mock_audio

        # Mock wake word model to detect wake word on both calls
        mock_wakeword_instance = Mock()
        mock_wakeword_instance.predict.return_value = {"hey_jarvis": 0.8}
        mock_wakeword_model.return_value = mock_wakeword_instance

        # Speech once (handled), then silence ends the follow-up window.
        mock_wait.side_effect = [b"audio_data", None]
        mock_record.return_value = b"more_audio"
        mock_transcribe.return_value = "test command"
        mock_route_command.return_value = True

        easy.run()

        # Check that command was only processed once (first wake word was within cooldown)
        assert mock_route_command.call_count == 1

        # Check cleanup
        mock_stream.stop_stream.assert_called_once()
        mock_stream.close.assert_called_once()
        mock_audio.terminate.assert_called_once()

    @patch("subprocess.run")
    @patch("time.time")
    @patch("easyspeak.core.main.pyaudio")
    @patch("easyspeak.core.main.WakeWordModel")
    @patch("easyspeak.core.main.load_whisper_model")
    @patch.object(EasySpeak, "load_plugins")
    @patch.object(EasySpeak, "wait_for_speech")
    @patch.object(EasySpeak, "record_until_silence")
    @patch.object(EasySpeak, "transcribe")
    @patch.object(EasySpeak, "route_command")
    def test_run_exit_command(
        self,
        mock_route_command,
        mock_transcribe,
        mock_record,
        mock_wait,
        mock_load_plugins,
        mock_whisper_model,
        mock_wakeword_model,
        mock_pyaudio,
        mock_time,
        mock_subprocess_run,
        mock_plugin,
        readlog,
    ):
        """Test run method exits when route_command returns False."""
        easy = EasySpeak()
        easy.plugins = [mock_plugin]

        # Mock time
        mock_time.return_value = 100.0

        # Mock PyAudio and stream
        mock_audio = Mock()
        mock_stream = Mock()

        pcm_data = b"\x00\x00" * 1280
        mock_stream.read.return_value = pcm_data
        mock_stream.get_read_available.return_value = 0
        mock_audio.open.return_value = mock_stream
        mock_pyaudio.PyAudio.return_value = mock_audio

        # Mock wake word model to detect wake word
        mock_wakeword_instance = Mock()
        mock_wakeword_instance.predict.return_value = {"hey_jarvis": 0.8}
        mock_wakeword_model.return_value = mock_wakeword_instance

        # Mock speech detection and transcription
        mock_wait.return_value = b"audio_data"
        mock_record.return_value = b"more_audio"
        mock_transcribe.return_value = "exit"
        mock_route_command.return_value = False  # Exit command

        easy.run()

        # Check that route_command was called and returned False
        mock_route_command.assert_called_once()

        # Check cleanup
        mock_stream.stop_stream.assert_called_once()
        mock_stream.close.assert_called_once()
        mock_audio.terminate.assert_called_once()

    @patch("subprocess.run")
    @patch("time.time")
    @patch("easyspeak.core.main.pyaudio")
    @patch("easyspeak.core.main.WakeWordModel")
    @patch("easyspeak.core.main.load_whisper_model")
    @patch.object(EasySpeak, "load_plugins")
    def test_run_audio_buffer_management(
        self,
        mock_load_plugins,
        mock_whisper_model,
        mock_wakeword_model,
        mock_pyaudio,
        mock_time,
        mock_subprocess_run,
        mock_plugin,
        readlog,
    ):
        """Test run method manages audio buffer correctly when it exceeds 50 items."""
        easy = EasySpeak()
        easy.plugins = [mock_plugin]

        # Mock time
        mock_time.return_value = 100.0

        # Mock PyAudio and stream
        mock_audio = Mock()
        mock_stream = Mock()

        # Create a long sequence of reads to fill buffer > 50
        pcm_data = b"\x00\x00" * 1280
        # 52 reads to ensure buffer management is triggered (first pop happens at 51st iteration)
        read_sequence = [pcm_data] * 52 + [KeyboardInterrupt()]
        mock_stream.read.side_effect = read_sequence
        mock_stream.get_read_available.return_value = 0
        mock_audio.open.return_value = mock_stream
        mock_pyaudio.PyAudio.return_value = mock_audio

        # Mock wake word model to never detect (score below threshold)
        mock_wakeword_instance = Mock()
        mock_wakeword_instance.predict.return_value = {
            "hey_jarvis": 0.3
        }  # Below threshold
        mock_wakeword_model.return_value = mock_wakeword_instance

        easy.run()

        # Verify that the buffer was managed (should have read enough times to trigger buffer management)
        # The buffer pop happens after 51st item, so we verify that many reads happened
        assert mock_stream.read.call_count >= 52

        # Check cleanup
        mock_stream.stop_stream.assert_called_once()
        mock_stream.close.assert_called_once()
        mock_audio.terminate.assert_called_once()

    @patch("easyspeak.core.main.pyaudio")
    @patch("easyspeak.core.main.WakeWordModel")
    @patch("easyspeak.core.main.load_whisper_model")
    @patch.object(EasySpeak, "load_plugins")
    def test_run_quit_from_tray(
        self,
        mock_load_plugins,
        mock_whisper_model,
        mock_wakeword_model,
        mock_pyaudio,
        mock_plugin,
    ):
        """When the tray controller returns QUIT then the loop exits and cleans
        up without ever reading audio."""
        easy = EasySpeak()
        easy.plugins = [mock_plugin]
        easy.tray = Mock()
        easy.tray.poll.return_value = TrayAction.QUIT

        mock_stream = Mock()
        mock_audio = Mock()
        mock_audio.open.return_value = mock_stream
        mock_pyaudio.PyAudio.return_value = mock_audio

        easy.run()

        mock_stream.read.assert_not_called()
        mock_stream.stop_stream.assert_called_once()
        mock_stream.close.assert_called_once()
        mock_audio.terminate.assert_called_once()

    @patch.object(EasySpeak, "flush_stream")
    @patch("easyspeak.core.main.pyaudio")
    @patch("easyspeak.core.main.WakeWordModel")
    @patch("easyspeak.core.main.load_whisper_model")
    @patch.object(EasySpeak, "load_plugins")
    def test_run_resume_from_tray_restarts_iteration(
        self,
        mock_load_plugins,
        mock_whisper_model,
        mock_wakeword_model,
        mock_pyaudio,
        mock_flush_stream,
        mock_plugin,
    ):
        """A RESUME (woke from sleep) resets the detector and flushes the mic so
        it starts fresh, skips the audio read, and loops again; the next
        CONTINUE proceeds to read."""
        easy = EasySpeak()
        easy.plugins = [mock_plugin]
        easy.tray = Mock()
        easy.tray.poll.side_effect = [TrayAction.RESUME, TrayAction.CONTINUE]

        mock_stream = Mock()
        mock_stream.read.side_effect = KeyboardInterrupt()
        mock_audio = Mock()
        mock_audio.open.return_value = mock_stream
        mock_pyaudio.PyAudio.return_value = mock_audio
        mock_wakeword_instance = Mock()
        mock_wakeword_model.return_value = mock_wakeword_instance

        easy.run()

        # Resume behaves like a fresh start: detector reset and mic flushed,
        # without consuming the main-loop read (only CONTINUE reaches the mic).
        mock_wakeword_instance.reset.assert_called_once()
        mock_flush_stream.assert_called_once()
        mock_stream.read.assert_called_once()

    @patch("easyspeak.core.main.pyaudio")
    @patch("easyspeak.core.main.WakeWordModel")
    @patch("easyspeak.core.main.load_whisper_model")
    @patch.object(EasySpeak, "load_plugins")
    def test_run_polls_tray_with_stream_callbacks(
        self,
        mock_load_plugins,
        mock_whisper_model,
        mock_wakeword_model,
        mock_pyaudio,
        mock_plugin,
    ):
        """The loop hands the tray its stream open/close callbacks so the
        controller can release/reacquire the mic without touching audio."""
        easy = EasySpeak()
        easy.plugins = [mock_plugin]
        easy.tray = Mock()
        easy.tray.poll.return_value = TrayAction.QUIT

        mock_audio = Mock()
        mock_audio.open.return_value = Mock()
        mock_pyaudio.PyAudio.return_value = mock_audio

        easy.run()

        easy.tray.poll.assert_called_with(easy._close_stream, easy._open_stream)


class TestEasySpeakShouldContinue:
    """Tests for the push-to-talk-aware capture guards."""

    def test_wait_for_speech_stops_when_should_continue_false(self):
        """A False predicate ends the wait immediately, reading nothing."""
        easy = EasySpeak()
        easy.stream = Mock()

        result = easy.wait_for_speech(timeout=5, should_continue=lambda: False)

        assert result is None
        easy.stream.read.assert_not_called()

    def test_wait_for_speech_runs_while_should_continue_true(self):
        """A True predicate lets the wait proceed and return detected speech."""
        easy = EasySpeak()
        easy.stream = Mock()
        loud = np.array([1000] * 1600, dtype=np.int16).tobytes()
        easy.stream.read = Mock(return_value=loud)

        result = easy.wait_for_speech(timeout=5, should_continue=lambda: True)

        assert result == loud

    def test_record_until_silence_stops_when_should_continue_false(self):
        """A False predicate cuts the recording short before reading."""
        easy = EasySpeak()
        easy.stream = Mock()

        result = easy.record_until_silence(should_continue=lambda: False)

        assert result == b""
        easy.stream.read.assert_not_called()

    def test_record_until_silence_runs_while_should_continue_true(self):
        """A True predicate records normally until the silence window."""
        easy = EasySpeak()
        easy.stream = Mock()
        loud = np.array([1000] * 1600, dtype=np.int16).tobytes()
        silent = np.array([10] * 1600, dtype=np.int16).tobytes()
        easy.stream.read = Mock(side_effect=[loud] * 6 + [silent] * 10)

        result = easy.record_until_silence(should_continue=lambda: True)

        assert isinstance(result, bytes)
        assert len(result) > 0


class TestEasySpeakPushToTalk:
    """Tests for hotkey-driven dictation hand-off."""

    def test_register_push_to_talk_stores_handler(self):
        """The dictation plugin's registration is kept for the hotkey to run."""
        easy = EasySpeak()
        handler = Mock()

        easy.register_push_to_talk(handler)

        assert easy._push_to_talk is handler

    def test_run_push_to_talk_without_handler_warns(self, readlog):
        """With no dictation plugin registered the press warns and no-ops."""
        easy = EasySpeak()
        easy._push_to_talk = None

        with patch.object(easy, "_play_wake_chime") as chime:
            easy._run_push_to_talk()

        assert "no dictation handler" in readlog().err.lower()
        chime.assert_not_called()

    @patch("subprocess.run")
    def test_run_push_to_talk_acks_then_runs_handler(self, mock_run):
        """A press chimes (no spoken prompt) and runs the handler gated on hold."""
        easy = EasySpeak()
        easy.speak = Mock()  # the silent path must speak no prompt
        handler = Mock()
        easy.register_push_to_talk(handler)

        with (
            patch.object(easy, "_reset_detector") as reset,
            patch.object(easy, "_play_wake_chime") as chime,
        ):
            easy._run_push_to_talk()

        reset.assert_called_once_with()
        chime.assert_called_once_with()
        handler.assert_called_once_with(easy.hotkey.is_held)
        easy.speak.assert_not_called()


class TestOpenStream:
    """Tests for opening the microphone input stream."""

    def test_open_stream_success(self):
        """A working capture device stores the opened stream."""
        easy = EasySpeak()
        easy.audio = Mock()
        stream = easy.audio.open.return_value

        easy._open_stream()

        assert easy.stream is stream

    def test_open_stream_no_device_exits_cleanly(self):
        """A missing capture device exits with a message, not a raw traceback."""
        easy = EasySpeak()
        easy.audio = Mock()
        easy.audio.open.side_effect = OSError(-9996, "Invalid input device")

        with pytest.raises(SystemExit) as exc_info:
            easy._open_stream()

        assert exc_info.value.code == 1
        assert easy.stream is None
