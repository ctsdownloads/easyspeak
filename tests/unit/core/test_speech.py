"""Tests for the core speech module (persistent piper -> player pipeline)."""

import base64
import hashlib
import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock, mock_open, patch

import pytest
from easyspeak.core import config, speech
from easyspeak.core.speech import SpeechPipeline


class TestSpeechPipeline:
    """Tests for the persistent piper -> player speech pipeline."""

    @pytest.fixture(autouse=True)
    def _no_spawn_grace(self):
        """Skip the post-spawn liveness wait so pipeline tests stay instant."""
        with patch("easyspeak.core.speech.SPEECH_SPAWN_GRACE", 0):
            yield

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

    @patch("shutil.which", return_value="/usr/bin/pw-play")
    @patch("subprocess.Popen")
    def test_piper_spawn_argv_unchanged(self, mock_popen, mock_which):
        """When the engine is piper (the default) then both spawns carry exactly
        the historical argv and kwargs — the Kokoro work must not disturb it."""
        assert config.TTS == "piper"
        pipe = SpeechPipeline()
        mock_player = Mock()
        mock_player.poll.return_value = None
        mock_piper = Mock()
        mock_piper.poll.return_value = None
        mock_popen.side_effect = [mock_player, mock_piper]

        pipe.speak("Done")

        rate = pipe._piper_sample_rate()
        assert mock_popen.call_args_list[0].args[0] == [
            "pw-play",
            "--raw",
            "--format",
            "s16",
            "--rate",
            str(rate),
            "--channels",
            "1",
            "-",
        ]
        assert mock_popen.call_args_list[1].args == (
            [config.PIPER_BIN, "--model", config.PIPER_MODEL, "--output-raw"],
        )
        assert mock_popen.call_args_list[1].kwargs == {
            "stdin": subprocess.PIPE,
            "stdout": mock_player.stdin,
            "stderr": subprocess.DEVNULL,
        }

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

        with patch("shutil.which", return_value=None):
            cmd = pipe._player_cmd(22050)

        assert cmd[0] == "ffplay"
        assert "-ar" in cmd and "22050" in cmd

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


class TestKokoroEngine:
    """Tests for the Kokoro engine: spawn, readiness thread, fence (spec §3.3)."""

    @pytest.fixture(autouse=True)
    def _no_spawn_grace(self):
        """Skip the post-spawn liveness wait so pipeline tests stay instant."""
        with patch("easyspeak.core.speech.SPEECH_SPAWN_GRACE", 0):
            yield

    @pytest.fixture(autouse=True)
    def _kokoro_selected(self, monkeypatch):
        """Select the Kokoro engine the way EASYSPEAK_TTS=kokoro would."""
        monkeypatch.setattr(config, "TTS", "kokoro")

    @patch("easyspeak.core.speech.os.pipe", return_value=(7, 8))
    @patch("easyspeak.core.speech.os.close")
    @patch("shutil.which", return_value="/usr/bin/pw-play")
    @patch("subprocess.Popen")
    def test_kokoro_spawn_command(
        self, mock_popen, mock_which, _close, _pipe, tmp_path, monkeypatch
    ):
        """When the engine is Kokoro then the worker is spawned at Kokoro's rate
        with the ready pipe's write end at its real descriptor number, and the
        parent drops its copy of that end right after the spawn."""
        monkeypatch.setattr(config, "KOKORO_DIR", tmp_path)  # no real drift read
        pipe = SpeechPipeline()
        mock_player = Mock()
        mock_player.poll.return_value = None
        mock_worker = Mock()
        mock_worker.poll.return_value = None
        mock_popen.side_effect = [mock_player, mock_worker]
        with patch.object(SpeechPipeline, "_wait_ready"):
            pipe.speak("Done")

        player_cmd, worker_cmd = (c.args[0] for c in mock_popen.call_args_list)
        assert player_cmd[0] == "pw-play" and "24000" in player_cmd
        assert worker_cmd == [
            sys.executable,
            "-m",
            "easyspeak.core.kokoro_worker",
            "--model",
            str(config.KOKORO_MODEL),
            "--voices",
            str(config.KOKORO_VOICES),
            "--voice",
            config.KOKORO_VOICES_BY_LANGUAGE[config.REPLY_LANGUAGE],
            "--lang",
            config.KOKORO_LANGUAGE_CODES[config.REPLY_LANGUAGE],
            # pass_fds preserves descriptor numbers; it does not remap to 3 —
            # the child must be told the number it actually gets.
            "--ready-fd",
            "8",
        ]
        spawn_kwargs = mock_popen.call_args_list[1].kwargs
        assert spawn_kwargs["pass_fds"] == (8,)
        assert spawn_kwargs["stdin"] == subprocess.PIPE
        assert spawn_kwargs["stdout"] is mock_player.stdin
        assert spawn_kwargs["stderr"] == subprocess.DEVNULL
        # Only the parent's write end is closed here; the read end belongs to
        # the reader thread, which closes it when the spawn's story ends.
        speech.os.close.assert_called_once_with(8)

    @patch("easyspeak.core.speech.os.pipe", return_value=(7, 8))
    @patch("easyspeak.core.speech.os.close")
    def test_kokoro_spawn_failure_closes_both_pipe_ends(
        self, _close, _pipe, tmp_path, monkeypatch
    ):
        """When the worker spawn itself fails then both ready-pipe ends are
        closed — the child never got the write end, so both are still ours."""
        monkeypatch.setattr(config, "KOKORO_DIR", tmp_path)
        pipe = SpeechPipeline()
        pipe._player = Mock()  # stdout=self._player.stdin is read before Popen

        with (
            patch("subprocess.Popen", side_effect=OSError("spawn refused")),
            pytest.raises(OSError),
        ):
            pipe._spawn_kokoro()

        closed = [c.args[0] for c in speech.os.close.call_args_list]
        assert closed == [7, 8]
        assert pipe._piper is None

    @patch("easyspeak.core.speech.os.pipe", return_value=(7, 8))
    @patch("easyspeak.core.speech.os.close")
    def test_thread_start_failure_closes_read_end(
        self, _close, _pipe, tmp_path, monkeypatch
    ):
        """When the reader thread cannot be started then the read end is closed
        here — without the thread, nobody else would ever close it."""
        monkeypatch.setattr(config, "KOKORO_DIR", tmp_path)
        pipe = SpeechPipeline()
        pipe._player = Mock()

        with (
            patch("subprocess.Popen"),
            patch(
                "easyspeak.core.speech.threading.Thread",
                side_effect=RuntimeError("can't start new thread"),
            ),
            pytest.raises(RuntimeError),
        ):
            pipe._spawn_kokoro()

        # Write end closed after the spawn, then the read end by the failure path.
        assert [c.args[0] for c in speech.os.close.call_args_list] == [8, 7]
        assert pipe._piper is not None  # the worker itself came up fine

    @patch("subprocess.Popen")
    def test_fenced_engine_spawns_piper(self, mock_popen):
        """Once fenced, every spawn is piper's — the worker is never spawned again."""
        pipe = SpeechPipeline()
        for _ in range(3):
            pipe.note_not_ready("worker died")
        assert pipe.fenced

        mock_player = Mock()
        mock_player.poll.return_value = None
        mock_piper = Mock()
        mock_piper.poll.return_value = None
        mock_popen.side_effect = [mock_player, mock_piper]

        pipe.speak("Done")

        assert mock_popen.call_args_list[1].args == (
            [config.PIPER_BIN, "--model", config.PIPER_MODEL, "--output-raw"],
        )
        for call in mock_popen.call_args_list:
            assert "easyspeak.core.kokoro_worker" not in str(call.args[0])

    def test_wait_ready_logs_provider_without_strike(self, readlog):
        """When the ready line arrives then the provider is logged and the
        engine counts as up — the EOF that ends this thread here is drain's."""
        pipe = SpeechPipeline()
        ready_read, ready_write = os.pipe()
        os.write(ready_write, b"ready provider=CUDAExecutionProvider\n")
        os.close(ready_write)  # EOF right after the line...
        pipe.begin_teardown()  # ...which is drain()'s deliberate one, not a death
        with patch.object(pipe, "_kill_speech") as kill:
            pipe._wait_ready(ready_read, 1, 0)  # closes the read end itself

        assert "provider=CUDAExecutionProvider" in readlog().out
        assert pipe.strikes == 0 and not pipe.fenced
        kill.assert_not_called()

    def test_wait_ready_eof_before_ready_strikes_and_kills(self, readlog):
        """When the worker dies before the ready line then the outcome strikes
        and the pipeline is killed so the next spawn starts fresh."""
        pipe = SpeechPipeline()
        ready_read, ready_write = os.pipe()
        os.close(ready_write)  # death before ready: EOF, no line
        with patch.object(pipe, "_kill_speech") as kill:
            pipe._wait_ready(ready_read, 2, 0)  # spawn 2: a runtime spawn

        assert "died before announcing readiness" in readlog().out
        kill.assert_called_once()
        assert pipe.strikes == 1 and not pipe.fenced

    def test_wait_ready_budget_expiry_kills_and_strikes(self, readlog):
        """When the worker hangs past the ready budget then the thread kills the
        pipeline and counts a strike — a hang is a death, not a stall."""
        pipe = SpeechPipeline()
        ready_read, ready_write = os.pipe()
        with (
            patch("easyspeak.core.speech.KOKORO_READY_BUDGET", 0.05),
            patch.object(pipe, "_kill_speech") as kill,
        ):
            pipe._wait_ready(ready_read, 2, 0)
        os.close(ready_write)  # the thread closed the read end; this end is ours

        assert "not ready after" in readlog().out
        kill.assert_called_once()
        assert pipe.strikes == 1 and not pipe.fenced

    def test_warmup_failure_primes_then_next_failure_fences(self, readlog):
        """A warm-up not-ready outcome primes the fence without striking; the
        next outcome fences to Piper immediately — at most one silent phrase."""
        pipe = SpeechPipeline()
        ready_read, ready_write = os.pipe()
        os.close(ready_write)
        with patch.object(pipe, "_kill_speech"):
            pipe._wait_ready(ready_read, 1, 0)  # spawn 1 IS the daemon warm-up
        assert pipe.strikes == 0 and not pipe.fenced
        assert "warm-up" in readlog().out

        pipe.note_not_ready("died again")  # the first phrase's rebuild
        assert pipe.fenced

    def test_three_runtime_strikes_fence(self, readlog):
        """Without a warm-up failure, three not-ready outcomes fence the engine,
        with exactly one fence warning naming the way back."""
        pipe = SpeechPipeline()
        pipe.note_not_ready("worker died")
        pipe.note_not_ready("worker died")
        assert not pipe.fenced

        pipe.note_not_ready("worker died")

        assert pipe.fenced
        assert readlog().out.count("--provision-kokoro") == 1

    def test_wait_ready_eof_after_ready_strikes(self, readlog):
        """When the worker dies after coming up then the death warns and strikes
        (session-cumulative); the already-written phrase dies unread."""
        pipe = SpeechPipeline()
        ready_read, ready_write = os.pipe()
        os.write(ready_write, b"ready provider=CPUExecutionProvider\n")
        os.close(ready_write)  # up, then a mid-loop death: EOF after the line
        with patch.object(pipe, "_kill_speech") as kill:
            pipe._wait_ready(ready_read, 2, 0)

        captured = readlog()
        assert "provider=CPUExecutionProvider" in captured.out
        assert "died after starting" in captured.out
        assert pipe.strikes == 1 and not pipe.fenced
        kill.assert_not_called()  # the worker is already dead; nobody hangs

    def test_warmup_spawn_post_ready_death_strikes_not_primes(self, readlog):
        """A death AFTER ready on spawn 1 is a runtime strike, not a warm-up
        prime — coming up proves the engine can start (spec §3.3)."""
        pipe = SpeechPipeline()
        ready_read, ready_write = os.pipe()
        os.write(ready_write, b"ready provider=CPUExecutionProvider\n")
        os.close(ready_write)  # up, then a mid-loop death: EOF after the line
        with patch.object(pipe, "_kill_speech") as kill:
            pipe._wait_ready(ready_read, 1, 0)  # spawn 1, the warm-up spawn

        captured = readlog()
        assert "provider=CPUExecutionProvider" in captured.out
        assert "died after starting" in captured.out
        assert pipe.strikes == 1 and not pipe.fenced and not pipe._primed
        kill.assert_not_called()

    def test_stale_reader_thread_never_strikes(self, readlog):
        """A reader thread superseded by a rebuild stays silent: the EOF it sees
        is our own kill's echo, not an engine death."""
        pipe = SpeechPipeline()
        ready_read, ready_write = os.pipe()
        os.close(ready_write)
        pipe._generation = 5  # kills happened since this spawn
        with patch.object(pipe, "_kill_speech") as kill:
            pipe._wait_ready(ready_read, 2, 3)  # born under generation 3

        kill.assert_not_called()
        assert pipe.strikes == 0 and not pipe.fenced
        assert readlog().out == ""

    def test_teardown_swallows_not_ready(self, readlog):
        """After begin_teardown() a not-ready outcome is a no-op, so drain()'s
        deliberate worker EOF at shutdown never strikes."""
        pipe = SpeechPipeline()
        pipe.begin_teardown()

        pipe.note_not_ready("worker died")

        assert pipe.strikes == 0 and not pipe.fenced
        assert readlog().out == ""

    def test_drain_after_kokoro_spawn_closes_without_strike(
        self, readlog, tmp_path, monkeypatch
    ):
        """Draining a Kokoro pipeline closes the worker's stdin like piper's and
        the reader thread's EOF strikes nothing."""
        # The spawn runs the real drift check; point it at an empty dir so the
        # "empty log" assertion can't trip over a real machine's provisioned.json.
        monkeypatch.setattr(config, "KOKORO_DIR", tmp_path)
        real_pipe, real_dup = os.pipe, os.dup
        ends = {}

        def recording_pipe():
            ends["read"], ends["write"] = real_pipe()
            # The parent closes its write-end copy right after the spawn; the
            # worker's own copy is what keeps the pipe open. A Mock worker holds
            # nothing, so the test holds this dup to stand in for it.
            ends["worker_copy"] = real_dup(ends["write"])
            return ends["read"], ends["write"]

        pipe = SpeechPipeline()
        mock_player, mock_worker = Mock(), Mock()
        with (
            patch("easyspeak.core.speech.os.pipe", side_effect=recording_pipe),
            patch("shutil.which", return_value="/usr/bin/pw-play"),
            patch("subprocess.Popen", side_effect=[mock_player, mock_worker]),
        ):
            pipe.ensure()

        assert pipe._ready_thread is not None
        pipe.drain()
        os.close(ends["worker_copy"])  # in production the worker's exit does this
        pipe._ready_thread.join(timeout=5)

        assert not pipe._ready_thread.is_alive()
        mock_worker.stdin.close.assert_called_once()
        mock_worker.wait.assert_called_once()
        # Spawn-time close (the worker holds the write end now) plus drain's.
        assert mock_player.stdin.close.call_count == 2
        assert pipe.strikes == 0 and not pipe.fenced
        assert readlog().out == ""


class TestFlavorDrift:
    """Tests for the provisioned-flavor drift check (spec §3.3)."""

    def test_warns_once_on_mismatch(self, tmp_path, monkeypatch, readlog):
        """A GPU-provisioned install that lost its GPU wheel warns exactly once
        per pipeline, pointing back at the provisioner."""
        monkeypatch.setattr(config, "KOKORO_DIR", tmp_path)
        (tmp_path / "provisioned.json").write_text(
            '{"flavor": "gpu", "verified": "yes"}', encoding="utf-8"
        )
        monkeypatch.setattr(speech, "_installed_onnxruntime_flavor", lambda: "cpu")
        pipe = SpeechPipeline()

        pipe._check_flavor_drift()
        pipe._check_flavor_drift()  # once per pipeline, not once per spawn

        assert readlog().out.count("--provision-kokoro") == 1

    def test_silent_when_provisioned_file_absent(self, tmp_path, monkeypatch, readlog):
        """Never provisioned (the dev checkout): nothing to drift from, no noise."""
        monkeypatch.setattr(config, "KOKORO_DIR", tmp_path)
        monkeypatch.setattr(speech, "_installed_onnxruntime_flavor", lambda: "cpu")

        SpeechPipeline()._check_flavor_drift()  # must not raise

        assert readlog().out == ""

    def test_silent_when_provisioned_file_corrupt(self, tmp_path, monkeypatch, readlog):
        """A corrupt record is treated as absent — the check reads tolerantly."""
        monkeypatch.setattr(config, "KOKORO_DIR", tmp_path)
        (tmp_path / "provisioned.json").write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(speech, "_installed_onnxruntime_flavor", lambda: "cpu")

        SpeechPipeline()._check_flavor_drift()  # must not raise

        assert readlog().out == ""

    def test_silent_when_flavor_matches(self, tmp_path, monkeypatch, readlog):
        """Provisioned cpu plus installed cpu is the normal machine: silent."""
        monkeypatch.setattr(config, "KOKORO_DIR", tmp_path)
        (tmp_path / "provisioned.json").write_text(
            '{"flavor": "cpu"}', encoding="utf-8"
        )
        monkeypatch.setattr(speech, "_installed_onnxruntime_flavor", lambda: "cpu")

        SpeechPipeline()._check_flavor_drift()

        assert readlog().out == ""

    def test_silent_when_installed_flavor_unknown(self, tmp_path, monkeypatch, readlog):
        """Without an identifiable installed onnxruntime there is nothing to
        accuse, so the check stays silent."""
        monkeypatch.setattr(config, "KOKORO_DIR", tmp_path)
        (tmp_path / "provisioned.json").write_text(
            '{"flavor": "gpu"}', encoding="utf-8"
        )
        monkeypatch.setattr(speech, "_installed_onnxruntime_flavor", lambda: None)

        SpeechPipeline()._check_flavor_drift()

        assert readlog().out == ""

    def test_installed_flavor_from_distribution_name(self):
        """The distribution providing the `onnxruntime` module decides the flavor;
        both wheels install the same module, so the distribution is the tell."""
        cases = [
            ({"onnxruntime": ["onnxruntime"]}, "cpu"),
            ({"onnxruntime": ["onnxruntime-gpu"]}, "gpu"),
            ({}, None),
        ]
        for distributions, expected in cases:
            with patch(
                "easyspeak.core.speech.packages_distributions",
                return_value=distributions,
            ):
                assert speech._installed_onnxruntime_flavor() == expected

    # -- the co-install state (both distribution names present) --------------
    #
    # kokoro-onnx depends on the plain CPU onnxruntime unconditionally, so the
    # provisioner's `kokoro-onnx[gpu]` install lands BOTH dist-infos on every
    # healthy GPU provision — names alone cannot say which flavor runs. These
    # tests build a minimal site-packages (module, capi main library, two
    # dist-info RECORDs) and let the live library's contents decide.

    @staticmethod
    def _coinstalled_site(tmp_path, live_bytes, cpu_bytes, gpu_bytes):
        """Fake a site with both onnxruntime dists and distinct main libraries.

        Each dist-info's RECORD claims its own `libonnxruntime.so` contents;
        `live_bytes` is what the module directory actually holds — the test
        controls whether it matches the cpu RECORD, the gpu RECORD, or neither.
        Returns the site directory.
        """
        site = tmp_path / "site-packages"
        capi = site / "onnxruntime" / "capi"
        capi.mkdir(parents=True)
        library = capi / "libonnxruntime.so.1.31.0"
        library.write_bytes(live_bytes)
        for stem, contents in (
            ("onnxruntime", cpu_bytes),
            ("onnxruntime_gpu", gpu_bytes),
        ):
            digest = (
                base64.urlsafe_b64encode(hashlib.sha256(contents).digest())
                .rstrip(b"=")
                .decode()
            )
            record = site / f"{stem}-1.31.0.dist-info" / "RECORD"
            record.parent.mkdir(parents=True)
            record.write_text(
                f"onnxruntime/capi/{library.name},sha256={digest},{len(contents)}\n",
                encoding="utf-8",
            )
        return site

    def _coinstall_flavor(self, tmp_path, monkeypatch, site):
        """Run the flavor probe against a fake co-installed site tree."""
        monkeypatch.setattr(
            speech.importlib.util,
            "find_spec",
            lambda name: SimpleNamespace(
                origin=str(site / "onnxruntime" / "__init__.py")
            ),
        )
        monkeypatch.setattr(
            speech,
            "packages_distributions",
            lambda: {"onnxruntime": ["onnxruntime", "onnxruntime-gpu"]},
        )
        return speech._installed_onnxruntime_flavor()

    def test_coinstalled_healthy_gpu_provision_is_not_drift(
        self, tmp_path, monkeypatch
    ):
        """Both dists present and the GPU main library live: the probe must say
        gpu — this is every healthy `--provision-kokoro` outcome, and the old
        name-only probe false-alarmed 'cpu installed' on it."""
        site = self._coinstalled_site(
            tmp_path,
            live_bytes=b"gpu-main-lib",
            cpu_bytes=b"cpu",
            gpu_bytes=b"gpu-main-lib",
        )
        assert self._coinstall_flavor(tmp_path, monkeypatch, site) == "gpu"

    def test_coinstalled_cpu_overwrite_is_drift(self, tmp_path, monkeypatch):
        """Both dists present but the CPU main library won (an app update
        reinstalled the deb's CPU wheel over the provisioned GPU one): the
        probe must say cpu, so the drift warning still fires."""
        site = self._coinstalled_site(
            tmp_path,
            live_bytes=b"cpu-main-lib",
            cpu_bytes=b"cpu-main-lib",
            gpu_bytes=b"gpu",
        )
        assert self._coinstall_flavor(tmp_path, monkeypatch, site) == "cpu"

    def test_coinstalled_unidentifiable_library_is_silent_none(
        self, tmp_path, monkeypatch
    ):
        """Neither RECORD matches the live library: unidentifiable — None keeps
        the drift check silent instead of accusing a flavor at random."""
        site = self._coinstalled_site(
            tmp_path, live_bytes=b"???-main-lib", cpu_bytes=b"cpu", gpu_bytes=b"gpu"
        )
        assert self._coinstall_flavor(tmp_path, monkeypatch, site) is None

    def test_coinstalled_without_main_library_is_silent_none(
        self, tmp_path, monkeypatch
    ):
        """A module directory without the shared main library cannot be
        attributed either way — None, and the check stays tolerant."""
        site = self._coinstalled_site(
            tmp_path, live_bytes=b"cpu", cpu_bytes=b"cpu", gpu_bytes=b"gpu"
        )
        (site / "onnxruntime" / "capi" / "libonnxruntime.so.1.31.0").unlink()
        assert self._coinstall_flavor(tmp_path, monkeypatch, site) is None

    def test_record_size_mismatch_short_circuits(self, tmp_path, monkeypatch):
        """A RECORD claiming a different size disagrees without a digest read —
        a 70 KB spread is what separates the two wheels' main libraries."""
        site = self._coinstalled_site(
            tmp_path, live_bytes=b"cpu", cpu_bytes=b"cpu", gpu_bytes=b"gpu"
        )
        library = site / "onnxruntime" / "capi" / "libonnxruntime.so.1.31.0"
        record = site / "onnxruntime-1.31.0.dist-info" / "RECORD"
        digest = (
            base64.urlsafe_b64encode(hashlib.sha256(b"cpu").digest())
            .rstrip(b"=")
            .decode()
        )
        record.write_text(
            f"onnxruntime/capi/{library.name},sha256={digest},999\n",
            encoding="utf-8",
        )
        assert not speech._record_matches(record, library, library.stat().st_size)

    def test_record_with_foreign_digest_scheme_never_matches(self, tmp_path):
        """Wheels standardize on sha256; a record that speaks another digest
        scheme can't be verified, so it doesn't match."""
        site = self._coinstalled_site(
            tmp_path, live_bytes=b"cpu", cpu_bytes=b"cpu", gpu_bytes=b"gpu"
        )
        library = site / "onnxruntime" / "capi" / "libonnxruntime.so.1.31.0"
        record = site / "onnxruntime-1.31.0.dist-info" / "RECORD"
        record.write_text(
            f"onnxruntime/capi/{library.name},md5=abc,{library.stat().st_size}\n",
            encoding="utf-8",
        )
        assert not speech._record_matches(record, library, library.stat().st_size)

    def test_record_without_the_library_row_never_matches(self, tmp_path):
        """A RECORD that doesn't mention the main library at all (a truncated
        install, say) matches nothing — the fall-through, not an exception."""
        site = self._coinstalled_site(
            tmp_path, live_bytes=b"cpu", cpu_bytes=b"cpu", gpu_bytes=b"gpu"
        )
        library = site / "onnxruntime" / "capi" / "libonnxruntime.so.1.31.0"
        record = site / "onnxruntime-1.31.0.dist-info" / "RECORD"
        record.write_text("onnxruntime/__init__.py,sha256=abc,10\n", encoding="utf-8")
        assert not speech._record_matches(record, library, library.stat().st_size)

    def test_coinstalled_without_importable_module_is_silent_none(
        self, tmp_path, monkeypatch
    ):
        """Both dist-infos but no importable onnxruntime module (a broken venv):
        unattributable, so None keeps the drift check quiet."""
        monkeypatch.setattr(speech.importlib.util, "find_spec", lambda name: None)
        monkeypatch.setattr(
            speech,
            "packages_distributions",
            lambda: {"onnxruntime": ["onnxruntime", "onnxruntime-gpu"]},
        )
        assert speech._installed_onnxruntime_flavor() is None

    def test_silent_when_installed_record_is_malformed(
        self, tmp_path, monkeypatch, readlog
    ):
        """A corrupted installer-written RECORD must not cost a spoken phrase:
        the probe degrades to "unknown flavor" and the drift check stays silent
        instead of raising out of the pipeline's warmup path."""
        monkeypatch.setattr(config, "KOKORO_DIR", tmp_path)
        (tmp_path / "provisioned.json").write_text(
            '{"flavor": "gpu"}', encoding="utf-8"
        )
        site = tmp_path / "site-packages"
        capi = site / "onnxruntime" / "capi"
        capi.mkdir(parents=True)
        library = capi / "libonnxruntime.so.1.31.0"
        library.write_bytes(b"whatever")  # contents irrelevant; the RECORD lies
        record = site / "onnxruntime-1.31.0.dist-info" / "RECORD"
        record.parent.mkdir(parents=True)
        # Two malformations, either of which would raise in strict parsing:
        # a blank line (csv yields a row that isn't a 3-tuple) and a garbage
        # size column (int() ValueError).
        record.write_text(
            f"\nonnxruntime/capi/{library.name},sha256=abc,not-a-number\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            speech.importlib.util,
            "find_spec",
            lambda name: SimpleNamespace(
                origin=str(site / "onnxruntime" / "__init__.py")
            ),
        )
        monkeypatch.setattr(
            speech,
            "packages_distributions",
            lambda: {"onnxruntime": ["onnxruntime", "onnxruntime-gpu"]},
        )

        SpeechPipeline()._check_flavor_drift()  # must not raise

        assert readlog().out == ""
