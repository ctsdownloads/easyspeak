"""Tests for the core main module."""

import sys
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch
import numpy as np

# Mock all external dependencies before importing the module
sys.modules["pyaudio"] = MagicMock()
sys.modules["openwakeword"] = MagicMock()
sys.modules["openwakeword.model"] = MagicMock()
sys.modules["faster_whisper"] = MagicMock()

from easyspeak.core.main import EasySpeak  # noqa: E402


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
            ["echo", "test"], capture_output=True, text=True
        )
        assert result == mock_result

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

    @patch("subprocess.run")
    @patch("subprocess.Popen")
    @patch("os.remove")
    @patch("tempfile.NamedTemporaryFile")
    def test_speak(self, mock_tempfile, mock_remove, mock_popen, mock_run, capsys):
        """Test speak method."""
        easy = EasySpeak()

        # Mock temporary file
        mock_file = Mock()
        mock_file.name = "/tmp/test.wav"
        mock_tempfile.return_value.__enter__.return_value = mock_file

        # Mock piper process
        mock_piper = Mock()
        mock_piper.communicate.return_value = (b"", b"")
        mock_popen.return_value = mock_piper

        easy.speak("Hello world")

        # Check that text was printed
        captured = capsys.readouterr()
        assert "💬 Hello world" in captured.out

        # Check that piper was called
        mock_popen.assert_called_once()
        assert mock_piper.communicate.called

        # Check that ffplay was called
        mock_run.assert_called_once()

        # Check that temp file was removed
        mock_remove.assert_called_once_with("/tmp/test.wav")


class TestEasySpeakPlugins:
    """Tests for EasySpeak plugin management."""

    @patch("importlib.import_module")
    @patch("sys.path")
    def test_load_plugins_no_directory(self, mock_syspath, mock_import, capsys):
        """Test load_plugins when plugins directory doesn't exist."""
        easy = EasySpeak()

        # Mock plugins directory to not exist
        with patch.object(Path, "exists", return_value=False):
            easy.load_plugins()

        captured = capsys.readouterr()
        assert "No plugins directory found" in captured.out
        assert easy.plugins == []

    @patch("importlib.import_module")
    @patch("sys.path")
    def test_load_plugins_valid_plugin(
        self, mock_syspath, mock_import, mock_test_plugin_with_setup, capsys
    ):
        """Test load_plugins with a valid plugin."""
        easy = EasySpeak()

        mock_import.return_value = mock_test_plugin_with_setup

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
        assert easy.plugins[0] == mock_test_plugin_with_setup
        mock_test_plugin_with_setup.setup.assert_called_once_with(easy)

        captured = capsys.readouterr()
        assert "✓ Loaded: TestPlugin" in captured.out

    @patch("importlib.import_module")
    @patch("sys.path")
    def test_load_plugins_skip_underscore_files(
        self, mock_syspath, mock_import, capsys
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
    def test_load_plugins_invalid_plugin(self, mock_syspath, mock_import, capsys):
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

        captured = capsys.readouterr()
        assert "Invalid plugin: invalid_plugin.py" in captured.out

    @patch("importlib.import_module")
    @patch("sys.path")
    def test_load_plugins_import_error(self, mock_syspath, mock_import, capsys):
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

        captured = capsys.readouterr()
        assert "Failed to load broken_plugin.py" in captured.out

    def test_get_all_commands_empty(self):
        """Test get_all_commands with no plugins."""
        easy = EasySpeak()

        commands = easy.get_all_commands()

        assert commands == []

    def test_get_all_commands_with_plugins(self, mock_test_plugin_with_commands):
        """Test get_all_commands with plugins that have commands."""
        easy = EasySpeak()

        # Create additional plugin with commands
        plugin2 = Mock()
        plugin2.COMMANDS = ["cmd3", "cmd4"]

        plugin3 = Mock(spec=[])  # Plugin without COMMANDS

        easy.plugins = [mock_test_plugin_with_commands, plugin2, plugin3]

        commands = easy.get_all_commands()

        assert commands == ["cmd1", "cmd2", "cmd3", "cmd4"]


class TestEasySpeakRouteCommand:
    """Tests for EasySpeak command routing."""

    def test_route_command_empty(self):
        """Test route_command with empty command."""
        easy = EasySpeak()

        result = easy.route_command("")

        assert result is True

    def test_route_command_strip_wake_words(self, mock_test_plugin):
        """Test that route_command strips wake words."""
        easy = EasySpeak()
        easy.plugins = [mock_test_plugin]

        # Test various wake word formats
        easy.route_command("hey jarvis test command")
        mock_test_plugin.handle.assert_called_with("test command", easy)

        easy.route_command("hey, jarvis, test command")
        mock_test_plugin.handle.assert_called_with("test command", easy)

        easy.route_command("jarvis test command")
        mock_test_plugin.handle.assert_called_with("test command", easy)

    def test_route_command_strip_punctuation(self, mock_test_plugin):
        """Test that route_command strips punctuation."""
        easy = EasySpeak()
        easy.plugins = [mock_test_plugin]

        easy.route_command("test command...")
        mock_test_plugin.handle.assert_called_with("test command", easy)

    def test_route_command_plugin_handles_true(self, mock_test_plugin):
        """Test route_command when plugin handles command and returns True."""
        easy = EasySpeak()
        easy.plugins = [mock_test_plugin]

        result = easy.route_command("test command")

        assert result is True
        mock_test_plugin.handle.assert_called_once()

    def test_route_command_plugin_handles_false(self, mock_test_plugin_exit):
        """Test route_command when plugin handles command and returns False (exit)."""
        easy = EasySpeak()
        easy.plugins = [mock_test_plugin_exit]

        result = easy.route_command("exit")

        assert result is False
        mock_test_plugin_exit.handle.assert_called_once()

    @patch.object(EasySpeak, "speak")
    def test_route_command_no_matching_plugin(
        self, mock_speak, mock_test_plugin_no_handle
    ):
        """Test route_command when no plugin handles the command."""
        easy = EasySpeak()
        easy.plugins = [mock_test_plugin_no_handle]

        result = easy.route_command("unknown command")

        assert result is True
        mock_speak.assert_called_once_with(
            "I didn't understand. Say help for commands."
        )

    @patch.object(EasySpeak, "speak")
    def test_route_command_plugin_error(
        self, mock_speak, mock_plugin_with_error, capsys
    ):
        """Test route_command when plugin raises an exception."""
        easy = EasySpeak()
        easy.plugins = [mock_plugin_with_error]

        result = easy.route_command("test command")

        captured = capsys.readouterr()
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

    @patch("easyspeak.core.main.WakeWordModel")
    @patch("easyspeak.core.main.WhisperModel")
    @patch.object(EasySpeak, "load_plugins")
    def test_run_no_plugins(
        self, mock_load_plugins, mock_whisper_model, mock_wakeword_model, capsys
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
        captured = capsys.readouterr()
        assert "No plugins loaded. Exiting." in captured.out

    @patch("subprocess.run")
    @patch("easyspeak.core.main.pyaudio")
    @patch("easyspeak.core.main.WakeWordModel")
    @patch("easyspeak.core.main.WhisperModel")
    @patch.object(EasySpeak, "load_plugins")
    def test_run_with_keyboard_interrupt(
        self,
        mock_load_plugins,
        mock_whisper_model,
        mock_wakeword_model,
        mock_pyaudio,
        mock_subprocess_run,
        mock_test_plugin,
        capsys,
    ):
        """Test run method handles KeyboardInterrupt gracefully."""
        easy = EasySpeak()
        easy.plugins = [mock_test_plugin]

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
        captured = capsys.readouterr()
        assert "Bye!" in captured.out

    @patch("subprocess.run")
    @patch("time.time")
    @patch("easyspeak.core.main.pyaudio")
    @patch("easyspeak.core.main.WakeWordModel")
    @patch("easyspeak.core.main.WhisperModel")
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
        mock_test_plugin,
        capsys,
    ):
        """Test run method when wake word is detected and command is processed."""
        easy = EasySpeak()
        easy.plugins = [mock_test_plugin]

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

        # Mock speech detection and transcription
        mock_wait.return_value = b"audio_data"
        mock_record.return_value = b"more_audio"
        mock_transcribe.return_value = "test command"
        mock_route_command.return_value = True

        easy.run()

        # Check that wake word was detected
        captured = capsys.readouterr()
        assert "Wake!" in captured.out
        assert "test command" in captured.out

        # Check that methods were called
        mock_wait.assert_called_once_with(timeout=5)
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
    @patch("easyspeak.core.main.WhisperModel")
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
        mock_test_plugin,
        capsys,
    ):
        """Test run method when wake word is detected but no speech follows."""
        easy = EasySpeak()
        easy.plugins = [mock_test_plugin]

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

        # Check that "I didn't hear anything" was spoken
        mock_speak.assert_called_once_with("I didn't hear anything.")

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
    @patch("easyspeak.core.main.WhisperModel")
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
        mock_test_plugin,
        capsys,
    ):
        """Test run method respects wake word cooldown period."""
        easy = EasySpeak()
        easy.plugins = [mock_test_plugin]

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

        # Mock speech detection and transcription
        mock_wait.return_value = b"audio_data"
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
    @patch("easyspeak.core.main.WhisperModel")
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
        mock_test_plugin,
        capsys,
    ):
        """Test run method exits when route_command returns False."""
        easy = EasySpeak()
        easy.plugins = [mock_test_plugin]

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
    @patch("easyspeak.core.main.WhisperModel")
    @patch.object(EasySpeak, "load_plugins")
    def test_run_audio_buffer_management(
        self,
        mock_load_plugins,
        mock_whisper_model,
        mock_wakeword_model,
        mock_pyaudio,
        mock_time,
        mock_subprocess_run,
        mock_test_plugin,
        capsys,
    ):
        """Test run method manages audio buffer correctly when it exceeds 50 items."""
        easy = EasySpeak()
        easy.plugins = [mock_test_plugin]

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
