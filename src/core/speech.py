"""Text-to-speech playback pipeline and audio-device noise suppression.

Extracted from core.main so the orchestration loop isn't tangled up with the
subprocess plumbing that keeps a piper voice model warm. `SpeechPipeline` owns
a persistent `piper -> player` pair; `suppressed_c_stderr` hides the unrelated
ALSA/JACK probe spew PortAudio emits when the input side (PyAudio) starts up.
"""

import contextlib
import json
import os
import shutil
import subprocess
import sys
import time
from subprocess import TimeoutExpired

from .config import PIPER_MODEL

# Seconds to wait after spawning the piper -> player pipeline before trusting
# it: long enough for an immediate failure (bad model, bad flag) to surface,
# short enough to barely register during the one-time warmup.
SPEECH_SPAWN_GRACE = 0.2


@contextlib.contextmanager
def suppressed_c_stderr():
    """Silence the device-probe spew PortAudio dumps when PyAudio starts up.

    Initializing PyAudio makes PortAudio enumerate every ALSA PCM named in the
    system alsa.conf (surround*, hdmi, iec958, ...) and ping JACK. Devices the
    machine doesn't have each print a harmless error, and libasound/libjack
    write them straight to file descriptor 2 from C — Python's sys.stderr never
    sees them, so only redirecting the fd itself can hide them.

    Suppression is best-effort: if stderr has no real fd (e.g. captured in
    tests), the fd can't be snapshotted (e.g. fd exhaustion), or the fd swap
    itself fails (e.g. fd 2 closed/invalid), there's nothing safe to redirect,
    so pass through rather than abort the caller.
    """
    try:
        stderr_fd = sys.stderr.fileno()
        # Flush first so already-buffered Python output lands on the real
        # stderr and not the /dev/null we're about to swap in.
        sys.stderr.flush()
        saved_fd = os.dup(stderr_fd)
    except (AttributeError, OSError, ValueError):
        yield
        return
    try:
        with open(os.devnull, "w") as devnull:
            try:
                os.dup2(devnull.fileno(), stderr_fd)
            except OSError:
                # Couldn't point fd 2 at /dev/null; run the body unsuppressed
                # rather than abort the caller, as the docstring promises.
                yield
                return
            try:
                yield
            finally:
                # Best-effort restore: a failed swap-back must not mask the
                # outcome of the body we just ran.
                with contextlib.suppress(OSError):
                    os.dup2(saved_fd, stderr_fd)
    finally:
        os.close(saved_fd)


class SpeechPipeline:
    """A persistent ``piper -> audio player`` pipeline for low-latency speech.

    Keeping piper alive avoids reloading its voice model (~2s) on every phrase,
    and streaming raw PCM straight to the player means playback starts as soon
    as synthesis does instead of after a temp WAV is fully written.
    """

    def __init__(self):
        self._piper = None
        self._player = None

    def _piper_sample_rate(self):
        """Read the model's output sample rate (defaults to 22050)."""
        try:
            with open(f"{PIPER_MODEL}.json") as f:
                return int(json.load(f)["audio"]["sample_rate"])
        except (OSError, ValueError, KeyError, TypeError):
            return 22050

    def _player_cmd(self, rate):
        """Pick a player that streams raw 16-bit mono PCM from stdin."""
        if shutil.which("pw-play"):
            return [
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
        if shutil.which("paplay"):
            return [
                "paplay",
                "--raw",
                "--format=s16le",
                f"--rate={rate}",
                "--channels=1",
            ]
        # Last resort: ffplay (may quit on long silent gaps between utterances).
        return [
            "ffplay",
            "-f",
            "s16le",
            "-ar",
            str(rate),
            "-ch_layout",
            "mono",
            "-nodisp",
            "-autoexit",
            "-i",
            "-",
        ]

    @staticmethod
    def _alive(proc):
        return proc is not None and proc.poll() is None

    def ensure(self):
        """Spawn the persistent piper -> player pipeline if not already running.

        Raises OSError if the pipeline can't be brought up (missing binary, bad
        model), so callers can warn once rather than silently failing per phrase.
        """
        if self._alive(self._piper) and self._alive(self._player):
            return
        self._kill_speech()  # clear out any half-dead pipeline first
        rate = self._piper_sample_rate()
        try:
            self._player = subprocess.Popen(
                self._player_cmd(rate),
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._piper = subprocess.Popen(
                ["piper", "--model", PIPER_MODEL, "--output-raw"],
                stdin=subprocess.PIPE,
                stdout=self._player.stdin,
                stderr=subprocess.DEVNULL,
            )
            # Hand the write end of the player's input pipe entirely to piper.
            # If the parent kept its own copy open, the player would never see
            # EOF when piper exits and would hang forever in read() (a dead
            # piper leaving an immortal pw-play behind), wedging the pipeline.
            self._player.stdin.close()
            # A bad model path or unsupported player flag lets Popen succeed but
            # the process dies milliseconds later. Give it a brief grace period
            # and confirm both are still alive, so warmup reports the failure
            # once instead of speak() rebuilding a dead pipeline on every phrase.
            time.sleep(SPEECH_SPAWN_GRACE)
            if not (self._alive(self._piper) and self._alive(self._player)):
                raise OSError("speech pipeline exited immediately after start")
        except Exception:
            self._kill_speech()  # don't leak a half-spawned pipeline
            raise

    def speak(self, text):
        """Text-to-speech output.

        Non-blocking: the phrase is handed to a warm piper process that streams
        audio to the player, so this returns immediately and the speech plays
        concurrently with whatever the caller does next.
        """
        text = text.strip()
        if not text:
            return
        print(f"💬 {text}")
        for _ in range(2):
            try:
                self.ensure()
                self._piper.stdin.write((text + "\n").encode())
                self._piper.stdin.flush()
                return
            except (BrokenPipeError, OSError, ValueError):
                self._kill_speech()  # tear down the broken pipeline, then retry

    @staticmethod
    def _reap(proc):
        """Kill a process, close its parent-side pipes, and wait for it, best-effort.

        Both pipeline processes are spawned with stdin=PIPE, so the parent holds
        a pipe fd for each; without closing them here, a repeatedly rebuilt
        pipeline would leak two fds per cycle until it hits the fd limit. kill()
        polls first and suppresses the PID-reuse race internally on Python 3.10+,
        but ProcessLookupError is named anyway to stay safe on other versions;
        AttributeError covers a malformed process handle and TimeoutExpired a
        process that refuses to die.
        """
        for name in ("stdin", "stdout", "stderr"):
            handle = getattr(proc, name, None)  # tolerate a handle missing these
            if handle is not None:
                try:
                    handle.close()
                except (AttributeError, OSError):
                    pass
        try:
            proc.kill()
            proc.wait(timeout=1)
        except (AttributeError, ProcessLookupError, TimeoutExpired):
            pass

    def _kill_speech(self):
        """Stop the pipeline at once (no wait for playback) so it can rebuild."""
        for proc in (self._piper, self._player):
            if proc is not None:
                self._reap(proc)
        self._piper = self._player = None

    @staticmethod
    def _close(proc):
        """Close stdin and wait for the process, killing it if it overruns."""
        try:
            proc.stdin.close()  # flush may raise if the downstream player died
            proc.wait(timeout=15)
        except (AttributeError, OSError, TimeoutExpired):
            SpeechPipeline._reap(proc)

    def drain(self):
        """Flush pending speech and wait for playback to finish, then stop the
        pipeline. Used on shutdown so a final phrase (e.g. "Goodbye.") is heard
        in full before the process exits."""
        piper, player = self._piper, self._player
        self._piper = self._player = None
        if piper is not None:
            self._close(piper)
        if player is not None:
            self._close(player)
