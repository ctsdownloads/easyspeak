"""Tests for the core speech module (persistent piper -> player pipeline)."""

import os
import subprocess
from unittest.mock import Mock, mock_open, patch

import pytest
from easyspeak.core import config
from easyspeak.core.speech import SpeechPipeline


class TestSpeechPipeline:
    """Tests for the persistent piper -> player speech pipeline."""

    @pytest.fixture(autouse=True)
    def _no_spawn_grace(self):
        """Skip the post-spawn liveness wait so pipeline tests stay instant."""
        with patch("easyspeak.core.speech.SPEECH_SPAWN_GRACE", 0):
            yield

    @pytest.fixture(autouse=True)
    def _audio_player(self, tmp_path, monkeypatch):
        """Put an audio player on the path, as on a desktop with sound.

        The processes are mocked, so it never runs; tests about choosing the
        player patch `shutil.which` themselves.
        """
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        (bin_dir / "pw-play").touch(mode=0o755)
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    @pytest.fixture(autouse=True)
    def voice_model(self, tmp_path):
        """Point piper at a voice model that exists, as an installed pack provides."""
        model = tmp_path / "voice.onnx"
        model.touch()
        with patch("easyspeak.core.speech.PIPER_MODEL", str(model)):
            yield model

    @patch("subprocess.Popen")
    def test_ensure_names_a_missing_voice_model(self, mock_popen, voice_model):
        """When the voice model isn't there then nothing is spawned and the error
        says where it was looked for, as piper takes too long to fail on it."""
        voice_model.unlink()

        with pytest.raises(OSError, match=f"^no voice model at {voice_model}$"):
            SpeechPipeline().ensure()

        mock_popen.assert_not_called()

    @patch("shutil.which", return_value="/usr/bin/pw-play")
    @patch("subprocess.Popen")
    def test_speak(self, mock_popen, mock_which, readlog):
        """When speak is called then it streams the phrase to a warm piper process."""
        pipe = SpeechPipeline()

        # Two Popen calls: the player, then piper (whose stdin we write to).
        mock_player = Mock()
        mock_player.poll.return_value = None
        mock_piper = Mock()
        mock_piper.poll.return_value = None
        mock_popen.side_effect = [mock_player, mock_piper]

        pipe.speak("Hello world")

        # Check that text was printed
        captured = readlog()
        assert "💬 Hello world" in captured.out

        # Pipeline spawned: player + piper
        assert mock_popen.call_count == 2
        piper_cmd = mock_popen.call_args_list[1].args[0]
        # Compared against the resolved binary, not the literal "piper": config
        # points at the venv's own piper when one is installed and only falls back
        # to the bare name when it isn't, so hardcoding the fallback made this test
        # pass only on machines without Piper.
        assert piper_cmd[0] == config.PIPER_BIN
        assert "--output-raw" in piper_cmd

        # Phrase was written to piper's stdin (newline-terminated)
        mock_piper.stdin.write.assert_called_once_with(b"Hello world\n")
        assert mock_piper.stdin.flush.called

    @patch("subprocess.Popen")
    def test_speak_reuses_warm_piper(self, mock_popen, readlog):
        """When speak is called twice then the piper process is reused (model loaded once)."""
        pipe = SpeechPipeline()
        mock_player = Mock()
        mock_player.poll.return_value = None
        mock_piper = Mock()
        mock_piper.poll.return_value = None
        mock_popen.side_effect = [mock_player, mock_piper]

        pipe.speak("first")
        pipe.speak("second")

        # Pipeline spawned only once across both phrases
        assert mock_popen.call_count == 2
        assert mock_piper.stdin.write.call_count == 2

    @patch("shutil.which", return_value="/usr/bin/pw-play")
    @patch("subprocess.Popen")
    def test_ensure_rebuilds_when_player_dies(self, mock_popen, mock_which):
        """When the player exits but piper survives then the stale pipeline is
        killed and rebuilt (no leaked player)."""
        pipe = SpeechPipeline()
        old_player = Mock()
        # Alive at the post-spawn liveness check, dead by the next ensure().
        old_player.poll.side_effect = [None, 0]
        old_piper = Mock()
        old_piper.poll.return_value = None  # piper still alive
        new_player, new_piper = Mock(), Mock()
        new_player.poll.return_value = new_piper.poll.return_value = None
        mock_popen.side_effect = [old_player, old_piper, new_player, new_piper]

        pipe.ensure()  # spawns old pair
        pipe.ensure()  # player dead -> rebuild

        old_piper.kill.assert_called_once()
        old_player.kill.assert_called_once()
        assert pipe._piper is new_piper and pipe._player is new_player

    @patch("shutil.which", return_value="/usr/bin/pw-play")
    @patch("subprocess.Popen")
    def test_ensure_cleans_up_when_piper_spawn_fails(self, mock_popen, mock_which):
        """When the player spawns but piper fails (e.g. missing binary) then the
        partial pipeline is torn down and the error propagates (no leaked player)."""
        pipe = SpeechPipeline()
        player = Mock()
        mock_popen.side_effect = [player, FileNotFoundError("piper")]

        with pytest.raises(FileNotFoundError):
            pipe.ensure()

        player.kill.assert_called_once()
        assert pipe._piper is None and pipe._player is None

    @patch("shutil.which", return_value="/usr/bin/pw-play")
    @patch("subprocess.Popen")
    def test_ensure_raises_when_pipeline_dies_immediately(self, mock_popen, mock_which):
        """When piper exits right after spawn (e.g. bad model) then the dead
        pipeline is torn down and OSError is raised so warmup can report it."""
        pipe = SpeechPipeline()
        player = Mock()
        player.poll.return_value = None  # player alive
        piper = Mock()
        piper.poll.return_value = 1  # piper died on startup
        mock_popen.side_effect = [player, piper]

        with pytest.raises(OSError):
            pipe.ensure()

        player.kill.assert_called_once()
        piper.kill.assert_called_once()
        assert pipe._piper is None and pipe._player is None

    @patch("shutil.which", return_value="/usr/bin/pw-play")
    @patch("subprocess.Popen")
    def test_ensure_says_why_the_pipeline_died(self, mock_popen, mock_which):
        """When piper exits right after spawn then the error carries the last line
        it wrote to stderr, and the player still running isn't blamed."""
        player = Mock()
        player.poll.return_value = None
        piper = Mock()
        piper.poll.return_value = 1

        def spawn(cmd, **kwargs):
            if cmd[0] == "pw-play":
                return player
            kwargs["stderr"].write(b"Loading model\nUnable to open model file\n")
            return piper

        mock_popen.side_effect = spawn

        with pytest.raises(OSError, match=r"^piper quit: Unable to open model file$"):
            SpeechPipeline().ensure()

    @patch("shutil.which", return_value="/usr/bin/pw-play")
    @patch("subprocess.Popen")
    def test_ensure_falls_back_to_the_exit_code(self, mock_popen, mock_which):
        """When a process that died wrote nothing to stderr then its exit code
        is the reason, for each process that died."""
        player = Mock()
        player.poll.return_value = 2
        piper = Mock()
        piper.poll.return_value = 1
        mock_popen.side_effect = [player, piper]

        with pytest.raises(
            OSError, match=r"^piper quit: exit code 1; pw-play quit: exit code 2$"
        ):
            SpeechPipeline().ensure()

    def test_kill_speech_swallows_reap_failure(self):
        """When wait() after kill() fails then _kill_speech still resets state."""
        pipe = SpeechPipeline()
        piper = Mock()
        piper.wait.side_effect = subprocess.TimeoutExpired("piper", 1)
        pipe._piper = piper

        pipe._kill_speech()  # must not raise

        piper.kill.assert_called_once()
        assert pipe._piper is None and pipe._player is None

    def test_kill_speech_closes_parent_pipes(self):
        """_kill_speech closes the parent-side stdin handles so a rebuilt
        pipeline doesn't leak a pipe fd per cycle."""
        pipe = SpeechPipeline()
        piper, player = Mock(), Mock()
        pipe._piper, pipe._player = piper, player

        pipe._kill_speech()

        piper.stdin.close.assert_called_once()
        player.stdin.close.assert_called_once()

    def test_kill_speech_swallows_pipe_close_failure(self):
        """A handle whose close() raises (e.g. already-broken pipe) is ignored,
        and _kill_speech still kills and resets state."""
        pipe = SpeechPipeline()
        piper = Mock()
        piper.stdin.close.side_effect = OSError("broken pipe")
        pipe._piper = piper

        pipe._kill_speech()  # must not raise

        piper.kill.assert_called_once()
        assert pipe._piper is None and pipe._player is None

    def test_kill_speech_tolerates_malformed_handle(self):
        """A handle missing stdin/stdout/stderr (and kill) is reaped without
        raising, as _reap's docstring promises."""
        pipe = SpeechPipeline()
        pipe._piper = object()  # no stdin/stdout/stderr/kill attributes

        pipe._kill_speech()  # must not raise

        assert pipe._piper is None and pipe._player is None

    @patch("subprocess.Popen")
    def test_drain_waits_for_playback(self, mock_popen):
        """When draining then piper stdin is closed and the pipeline is awaited."""
        pipe = SpeechPipeline()
        mock_player = Mock()
        mock_player.poll.return_value = None
        mock_piper = Mock()
        mock_piper.poll.return_value = None
        mock_popen.side_effect = [mock_player, mock_piper]

        pipe.speak("Goodbye.")
        pipe.drain()

        mock_piper.stdin.close.assert_called_once()
        mock_piper.wait.assert_called_once()
        # The player's stdin is closed twice: once by ensure() at spawn (so a
        # dying piper can't leave the player hung on a pipe the parent still
        # holds open) and again by drain()'s _close. close() is idempotent.
        assert mock_player.stdin.close.call_count == 2
        mock_player.wait.assert_called_once()
        assert pipe._piper is None and pipe._player is None

    @patch("subprocess.Popen")
    def test_speak_ignores_blank_text(self, mock_popen):
        """When speak is given blank text then no pipeline is spawned."""
        pipe = SpeechPipeline()

        pipe.speak("   ")

        mock_popen.assert_not_called()

    def test_speak_rebuilds_pipeline_on_broken_pipe(self):
        """When the pipeline write fails then speak rebuilds it and retries once."""
        pipe = SpeechPipeline()
        broken = Mock()
        broken.poll.return_value = None
        broken.stdin.write.side_effect = BrokenPipeError()
        healthy = Mock()
        healthy.poll.return_value = None
        pipers = [broken, healthy]

        def fake_ensure():
            pipe._piper = pipers.pop(0)

        with patch.object(pipe, "ensure", side_effect=fake_ensure):
            pipe.speak("hello")

        # The rebuilt (healthy) piper received the phrase.
        healthy.stdin.write.assert_called_once_with(b"hello\n")

    def test_speak_gives_up_after_two_failures(self):
        """When the pipeline keeps failing then speak gives up without raising."""
        pipe = SpeechPipeline()

        def fake_ensure():
            piper = Mock()
            piper.poll.return_value = None
            piper.stdin.write.side_effect = OSError()
            pipe._piper = piper

        with patch.object(pipe, "ensure", side_effect=fake_ensure) as mock_ensure:
            pipe.speak("hello")  # must not raise

        # Tried to (re)build the pipeline twice before giving up.
        assert mock_ensure.call_count == 2

    def test_speak_logs_why_it_dropped_the_phrase(self, readlog):
        """When the pipeline can't come up then the dropped phrase is logged with
        the reason, for the verbose output."""
        pipe = SpeechPipeline()

        with patch.object(pipe, "ensure", side_effect=OSError("piper quit: boom")):
            pipe.speak("hello")

        assert (
            "speech pipeline unavailable (piper quit: boom); dropped phrase: hello"
            in readlog().out
        )

    def test_piper_sample_rate_reads_model_json(self):
        """When the model json is readable then its sample rate is used."""
        pipe = SpeechPipeline()

        with patch(
            "builtins.open", mock_open(read_data='{"audio": {"sample_rate": 16000}}')
        ):
            assert pipe._piper_sample_rate() == 16000

    def test_piper_sample_rate_defaults_on_error(self):
        """When the model json is unreadable then the rate defaults to 22050."""
        pipe = SpeechPipeline()

        with patch("builtins.open", side_effect=OSError()):
            assert pipe._piper_sample_rate() == 22050

    def test_player_cmd_prefers_pw_play(self):
        """When pw-play is available then it is used to stream raw audio."""
        pipe = SpeechPipeline()

        with patch(
            "shutil.which",
            side_effect=lambda p: "/bin/pw-play" if p == "pw-play" else None,
        ):
            cmd = pipe._player_cmd(22050)

        assert cmd[0] == "pw-play"
        assert "--raw" in cmd and "22050" in cmd

    def test_player_cmd_falls_back_to_paplay(self):
        """When only paplay is available then it is used."""
        pipe = SpeechPipeline()

        with patch(
            "shutil.which",
            side_effect=lambda p: "/bin/paplay" if p == "paplay" else None,
        ):
            cmd = pipe._player_cmd(16000)

        assert cmd[0] == "paplay"
        assert "--rate=16000" in cmd

    def test_player_cmd_falls_back_to_ffplay(self):
        """When no PipeWire/PulseAudio player exists then ffplay is the last resort."""
        pipe = SpeechPipeline()

        with patch(
            "shutil.which",
            side_effect=lambda p: "/bin/ffplay" if p == "ffplay" else None,
        ):
            cmd = pipe._player_cmd(22050)

        assert cmd[0] == "ffplay"
        assert "-ar" in cmd and "22050" in cmd

    def test_player_cmd_names_the_players_when_none_is_installed(self):
        """When no audio player is installed then the error names the ones to install."""
        pipe = SpeechPipeline()

        with (
            patch("shutil.which", return_value=None),
            pytest.raises(OSError, match="pw-play, paplay or ffplay"),
        ):
            pipe._player_cmd(22050)

    def test_drain_kills_pipeline_on_timeout(self):
        """When the pipeline does not exit in time then both processes are killed."""
        pipe = SpeechPipeline()
        piper = Mock()
        piper.wait.side_effect = subprocess.TimeoutExpired("piper", 15)
        player = Mock()
        player.wait.side_effect = subprocess.TimeoutExpired("player", 15)
        pipe._piper = piper
        pipe._player = player

        pipe.drain()

        piper.kill.assert_called_once()
        player.kill.assert_called_once()

    def test_drain_noop_when_idle(self):
        """When nothing has been spoken then draining does nothing."""
        pipe = SpeechPipeline()

        pipe.drain()  # must not raise

        assert pipe._piper is None and pipe._player is None


class TestSuppressedCStderr:
    """Tests for the PortAudio stderr-noise suppressor."""

    def test_passes_through_when_stderr_has_no_fileno(self):
        """When stderr has no real fd (e.g. captured) the helper is a no-op."""
        from easyspeak.core.speech import suppressed_c_stderr

        broken = Mock()
        broken.fileno.side_effect = ValueError("no fd")
        with (
            patch("easyspeak.core.speech.sys.stderr", broken),
            suppressed_c_stderr(),  # must not raise
        ):
            pass

    def test_passes_through_when_fd_snapshot_fails(self):
        """When os.dup can't snapshot the fd (e.g. fd exhaustion) the helper
        degrades to a no-op rather than aborting the caller."""
        from easyspeak.core.speech import suppressed_c_stderr

        stderr = Mock()
        stderr.fileno.return_value = 2
        with (
            patch("easyspeak.core.speech.sys.stderr", stderr),
            patch("easyspeak.core.speech.os.dup", side_effect=OSError("too many fds")),
            patch("easyspeak.core.speech.os.dup2") as mock_dup2,
            suppressed_c_stderr(),
        ):  # must not raise
            pass

        mock_dup2.assert_not_called()  # never got far enough to redirect

    def test_passes_through_when_redirect_fails(self):
        """When the fd swap to /dev/null fails (e.g. fd 2 closed/invalid) the
        helper runs the body unsuppressed rather than aborting the caller, and
        still closes the snapshot fd so it isn't leaked."""
        from easyspeak.core.speech import suppressed_c_stderr

        stderr = Mock()
        stderr.fileno.return_value = 2
        with (
            patch("easyspeak.core.speech.sys.stderr", stderr),
            patch("easyspeak.core.speech.os.dup", return_value=99),
            patch("easyspeak.core.speech.os.dup2", side_effect=OSError("bad fd")),
            patch("easyspeak.core.speech.os.close") as mock_close,
            patch("builtins.open", mock_open()),
        ):
            ran = False
            with suppressed_c_stderr():  # must not raise
                ran = True

        assert ran  # body executed despite the failed redirect
        mock_close.assert_called_once_with(99)  # snapshot fd not leaked

    def test_restore_failure_does_not_propagate(self):
        """When the swap-back fails after a successful redirect, the failure is
        swallowed rather than leaking out of the context manager exit."""
        from easyspeak.core.speech import suppressed_c_stderr

        stderr = Mock()
        stderr.fileno.return_value = 2
        with (
            patch("easyspeak.core.speech.sys.stderr", stderr),
            patch("easyspeak.core.speech.os.dup", return_value=99),
            patch(
                "easyspeak.core.speech.os.dup2",
                side_effect=[None, OSError("bad fd")],
            ),
            patch("easyspeak.core.speech.os.close"),
            patch("builtins.open", mock_open()),
            suppressed_c_stderr(),
        ):  # must not raise
            pass

    def test_flushes_stderr_before_redirecting(self):
        """Buffered stderr is flushed before the fd is swapped, so pending output
        isn't lost to /dev/null."""
        from easyspeak.core.speech import suppressed_c_stderr

        order = []
        stderr = Mock()
        stderr.fileno.return_value = 2
        stderr.flush.side_effect = lambda: order.append("flush")
        with (
            patch("easyspeak.core.speech.sys.stderr", stderr),
            patch("easyspeak.core.speech.os.dup", return_value=99),
            patch(
                "easyspeak.core.speech.os.dup2",
                side_effect=lambda *a: order.append("dup2"),
            ),
            patch("easyspeak.core.speech.os.close"),
            patch("builtins.open", mock_open()),
            suppressed_c_stderr(),
        ):
            pass

        assert order.index("flush") < order.index("dup2")
