"""Text-to-speech playback pipeline and audio-device noise suppression.

Extracted from core.main so the orchestration loop isn't tangled up with the subprocess
plumbing that keeps a speech engine warm. `SpeechPipeline` owns a persistent
`engine -> player` pair — piper, or the Kokoro worker with its readiness reader
thread; `suppressed_c_stderr` hides the unrelated ALSA/JACK probe spew
PortAudio emits when the input side (PyAudio) starts up.
"""

import base64
import contextlib
import csv
import hashlib
import importlib.util
import json
import logging
import os
import select
import shutil
import subprocess
import sys
import threading
import time
from importlib.metadata import packages_distributions
from pathlib import Path
from subprocess import TimeoutExpired

from . import config
from .config import PIPER_BIN, PIPER_MODEL
from .kokoro_worker import SPEAK_SAMPLE_RATE as KOKORO_SAMPLE_RATE

logger = logging.getLogger(__name__)

SPEECH_SPAWN_GRACE = 0.2

# One readiness budget for every Kokoro spawn — a restart after machine resume
# pays cold CUDA init again, so a tighter "warm" budget would false-expire on
# healthy workers (Kokoro spec §3.3).
KOKORO_READY_BUDGET = 15.0

# Runtime not-ready outcomes that fence the engine to Piper when the warm-up
# spawn came up fine; a warm-up failure instead primes the fence, so the very
# next outcome fences (spec §3.3).
KOKORO_STRIKE_LIMIT = 3

# provisioned.json's flavor vocabulary, mapped to the distribution names that
# provide the `onnxruntime` module (the GPU wheel is a drop-in replacement).
_ONNXRUNTIME_FLAVORS = {"onnxruntime": "cpu", "onnxruntime-gpu": "gpu"}


def _installed_onnxruntime_flavor():
    """Which provisioned flavor the installed onnxruntime distribution is.

    `onnxruntime` and `onnxruntime-gpu` both provide the `onnxruntime` module,
    so the importable module cannot tell them apart — the installed
    *distribution* name can. Returns None when nothing installed provides the
    module, which simply skips the drift check.

    Except that the names alone lie in one case (found live in Task 8's
    acceptance): `kokoro-onnx` depends on the plain CPU wheel UNCONDITIONALLY,
    so `kokoro-onnx[gpu]` — what the provisioner installs — co-installs BOTH
    distributions on every healthy GPU provision. When both names show up, the
    shared main library's contents decide (see
    `_flavor_owning_main_library`); None means "cannot tell", which skips the
    drift check instead of crying wolf over a working GPU engine.
    """
    flavors = {
        flavor
        for distribution in packages_distributions().get("onnxruntime", [])
        if (flavor := _ONNXRUNTIME_FLAVORS.get(distribution)) is not None
    }
    if len(flavors) != 2:
        return next(iter(flavors), None)
    return _flavor_owning_main_library(flavors)


def _flavor_owning_main_library(flavors):
    """Which co-installed flavor's main library is actually on disk.

    Both wheels ship `capi/libonnxruntime.so.*` under the same path with
    different contents, and pip-style installs never remove files another
    distribution owns — so last-write-wins, and only the file itself knows.
    Each candidate dist-info's RECORD carries the wheel-standard urlsafe
    sha256 of the file it installed: compare (size first, digest as
    authority) and return the flavor whose entry matches. None when neither
    matches (a state nothing installed) — unidentifiable, so skip silently.
    """
    spec = importlib.util.find_spec("onnxruntime")
    if spec is None or not spec.origin:
        return None
    capi = Path(spec.origin).parent / "capi"
    libraries = sorted(capi.glob("libonnxruntime.so.*")) or sorted(
        capi.glob("libonnxruntime.*")
    )
    if not libraries:
        return None
    library = libraries[0]
    size = library.stat().st_size
    for record in sorted(capi.parent.parent.glob("*.dist-info/RECORD")):
        # The dist-info DIRECTORY escapes the distribution name's hyphens as
        # underscores (`onnxruntime_gpu-1.31.0.dist-info`); the flavor map keys
        # on the real name, so unescape before looking up.
        flavor = _ONNXRUNTIME_FLAVORS.get(
            record.parent.name.split("-")[0].replace("_", "-")
        )
        if flavor not in flavors:
            continue
        if _record_matches(record, library, size):
            return flavor
    return None


def _record_matches(record, library, size):
    """Whether `record`'s entry for `library` matches the live size + digest."""
    with Path(record).open(encoding="utf-8", newline="") as stream:
        for path, digest, recorded_size in csv.reader(stream):
            if Path(path).name != library.name:
                continue
            claimed = int(recorded_size) if recorded_size else None
            if claimed is not None and claimed != size:
                return False
            algorithm, _, encoded = digest.partition("=")
            if algorithm != "sha256":
                return False
            live = hashlib.sha256(library.read_bytes()).digest()
            expected = base64.urlsafe_b64decode(f"{encoded}===")
            return live == expected
    return False


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
        with open(os.devnull, "w") as devnull:  # noqa: PTH123
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
    """A persistent `engine -> audio player` pipeline for low-latency speech.

    The engine is piper or the Kokoro worker (`config.TTS`), chosen per spawn.
    Keeping the engine alive avoids reloading its model (~2s for piper, several
    more for Kokoro) on every phrase, and streaming raw PCM straight to the
    player means playback starts as soon as synthesis does instead of after a
    temp WAV is fully written.

    The engine process is held in `_piper` — the historical name, kept because
    every shared path (speak, drain, _reap and the tests) holds that handle;
    which engine it points at is purely a spawn-time decision.
    """

    def __init__(self):
        """Create an idle pipeline; the subprocesses are spawned on first use."""
        self._piper = None  # the engine process: piper, or the Kokoro worker
        self._player = None
        # Kokoro engine bookkeeping (spec §3.3): which spawn a reader thread
        # belongs to, how many kills happened since (a superseded thread's EOF
        # is our kill's echo, not an engine death), and the session-cumulative
        # strike/fence state.
        self._spawn_no = 0
        self._generation = 0
        self._ready_thread = None
        # strikes/fenced are public for introspection only (tests, debugging):
        # no production code reads them — the fence decision lives entirely in
        # note_not_ready/_fence.
        self.strikes = 0
        self._primed = False
        self.fenced = False
        self._tearing_down = False
        self._drift_checked = False

    def _piper_sample_rate(self):
        """Read the model's output sample rate (defaults to 22050)."""
        try:
            with open(f"{PIPER_MODEL}.json") as f:  # noqa: PTH123
                return int(json.load(f)["audio"]["sample_rate"])
        except (OSError, ValueError, KeyError, TypeError):
            return 22050

    def _kokoro_cmd(self, ready_fd):
        """The Kokoro worker's argv for this session's language.

        `ready_fd` must be the write end's REAL descriptor number: `pass_fds`
        preserves descriptor numbers across the spawn, it does not remap to 3.
        """
        return [
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
            "--ready-fd",
            str(ready_fd),
        ]

    def _use_kokoro(self):
        """Whether the next spawn brings up the Kokoro worker, not piper."""
        return config.TTS == "kokoro" and not self.fenced

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
        """Spawn the persistent engine -> player pipeline if not already running.

        Raises OSError if the pipeline can't be brought up (missing binary, bad model),
        so callers can warn once rather than silently failing per phrase. With the
        Kokoro engine this surface is spawn mechanics only: readiness belongs to the
        reader thread (see `_wait_ready`), so a worker that never comes up fails
        asynchronously and never raises here.
        """
        if self._alive(self._piper) and self._alive(self._player):
            return
        self._kill_speech()  # clear out any half-dead pipeline first
        kokoro = self._use_kokoro()
        rate = KOKORO_SAMPLE_RATE if kokoro else self._piper_sample_rate()
        try:
            self._player = subprocess.Popen(
                self._player_cmd(rate),
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if kokoro:
                self._spawn_kokoro()
            else:
                self._piper = subprocess.Popen(
                    [PIPER_BIN, "--model", PIPER_MODEL, "--output-raw"],
                    stdin=subprocess.PIPE,
                    stdout=self._player.stdin,
                    stderr=subprocess.DEVNULL,
                )
            self._player.stdin.close()
            if kokoro:
                # The worker may legitimately still be loading its model — that
                # is the whole point of the reader thread — and its death is
                # that thread's finding, never this thread's OSError. Piper
                # keeps its synchronous fast-fail probe below.
                return
            time.sleep(SPEECH_SPAWN_GRACE)
            if not (self._alive(self._piper) and self._alive(self._player)):
                msg = "speech pipeline exited immediately after start"
                raise OSError(msg)
        except Exception:
            self._kill_speech()  # don't leak a half-spawned pipeline
            raise

    def _spawn_kokoro(self):
        """Spawn the Kokoro worker and hand readiness to a reader thread.

        Returns as soon as the processes exist: the phrase that triggered this
        spawn is written into the worker's stdin right after, and the pipe
        buffers it until the worker comes up — the caller never waits.
        """
        self._check_flavor_drift()
        ready_read, ready_write = os.pipe()
        try:
            self._piper = subprocess.Popen(
                self._kokoro_cmd(ready_write),
                stdin=subprocess.PIPE,
                stdout=self._player.stdin,
                stderr=subprocess.DEVNULL,
                # The write end crosses at its real descriptor number — the
                # same number `_kokoro_cmd` already told the child about.
                pass_fds=(ready_write,),
            )
        except Exception:
            # The child never got (or never kept) its copy of the write end, so
            # both ends are still solely ours: close them or leak two fds per
            # failed spawn.
            os.close(ready_read)
            os.close(ready_write)
            raise
        # The child holds its own copy now; keeping ours open would stop the
        # read end from ever seeing the EOF that reports a worker death.
        os.close(ready_write)
        self._spawn_no += 1
        try:
            self._ready_thread = threading.Thread(
                target=self._wait_ready,
                args=(ready_read, self._spawn_no, self._generation),
                name="kokoro-ready",
                daemon=True,
            )
            self._ready_thread.start()
        except Exception:
            # Without a thread nobody will ever read — or close — the read end;
            # close it here or leak one fd per failed thread start.
            with contextlib.suppress(OSError, ValueError):
                os.close(ready_read)
            raise

    def _read_ready_line(self, ready_read, deadline):
        """Read the worker's single ready line, or None on EOF/deadline.

        select() splits the wait against the deadline so a hung worker cannot
        hold the reader thread past its budget — a plain blocking os.read has
        no timeout.
        """
        buf = bytearray()
        while b"\n" not in buf:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            readable, _, _ = select.select([ready_read], [], [], remaining)
            if not readable:
                return None  # budget expired with the worker still warming up
            chunk = os.read(ready_read, 1024)
            if not chunk:
                return None  # the worker died before announcing itself
            buf += chunk
            if len(buf) > 4096:
                return None  # the fd carries one short line; more is a breach
        return bytes(buf[: buf.index(b"\n")])

    def _wait_ready(self, ready_read, spawn_no, generation):
        """Own the ready fd for one spawn, from process start to its EOF.

        Runs on a daemon thread because the main thread must never block on
        readiness — it writes the phrase into the worker's stdin pipe (which
        buffers) and moves on; this thread owns the outcome instead:
        - the `ready provider=<ep>` line: logged, engine counts as up;
        - EOF or budget expiry before the line: a not-ready outcome, plus a
          kill — a hung worker is a death, not a stall;
        - EOF after the line: the worker died mid-stream, a not-ready outcome
          whose already-written phrase dies unread.

        A superseded generation (any `_kill_speech` since this spawn) makes
        every outcome here stale: the EOF this thread is seeing is our own
        kill's echo, and the live spawn owns the accounting now.

        Accounting is single-writer by construction: the generation gate above
        returns stale threads BEFORE any `note_not_ready` call, so only the
        live spawn's thread can mutate the strike/fence state — no lock needed.
        """
        try:
            deadline = time.monotonic() + KOKORO_READY_BUDGET
            line = self._read_ready_line(ready_read, deadline)
            if self._generation != generation:
                return  # superseded by a rebuild; stay silent
            if line is None or not line.startswith(b"ready"):
                if line is None and time.monotonic() >= deadline:
                    why = f"not ready after {KOKORO_READY_BUDGET:.0f}s"
                elif line is None:
                    why = "died before announcing readiness"
                else:
                    why = f"unexpected traffic on the ready fd: {line!r}"
                self.note_not_ready(why, warmup=spawn_no == 1)
                if self._generation == generation:
                    self._kill_speech()  # free the pipeline for the next spawn
                return
            provider = line.decode("utf-8", "replace").split("provider=", 1)[-1]
            logger.info("Kokoro engine ready (provider=%s).", provider.strip())
            while os.read(ready_read, 4096):
                pass  # the fd is silent after the ready line; hold it for death
            if self._generation != generation or self._tearing_down:
                return  # our own kill, or drain()'s deliberate worker EOF
            self.note_not_ready(
                f"worker died after starting (provider={provider.strip()})"
            )
        finally:
            with contextlib.suppress(OSError, ValueError):
                # Same fd-leak discipline `_reap` enforces for the stdio pipes:
                # the read end is this thread's, closed exactly once, always.
                os.close(ready_read)

    def note_not_ready(self, why, *, warmup=False):
        """Count one Kokoro failure; the warm-up failure primes, the rest strike.

        The pipeline's first Kokoro spawn is the daemon's warm-up (main.py calls
        `ensure()` before any phrase), so spawn 1's not-ready outcome is the
        proof the engine cannot start: it primes the fence instead of counting
        toward `KOKORO_STRIKE_LIMIT`, and the next outcome fences immediately —
        at most one silent phrase. Strikes are session-cumulative and are not
        reset by a successful recovery, so an engine that repeatedly dies
        cannot dodge the fence by briefly coming back.

        After `begin_teardown()` (and once fenced) this is a no-op: drain()'s
        deliberate worker EOF at shutdown is a clean exit, not a failure.
        """
        if self._tearing_down or self.fenced:
            return
        if warmup and not self._primed:  # warmup=True comes only from spawn 1,
            self._primed = True  # by ordinal — this branch fires exactly once
            logger.warning(
                "Kokoro failed to start at warm-up (%s); the next failure "
                "switches replies to Piper for this session.",
                why,
            )
            return
        self.strikes += 1
        if self._primed or self.strikes >= KOKORO_STRIKE_LIMIT:
            self._fence(why)
        else:
            logger.warning(
                "Kokoro worker failed (%s); %d of %d failures before fencing to Piper.",
                why,
                self.strikes,
                KOKORO_STRIKE_LIMIT,
            )

    def _fence(self, why):
        """Degrade to Piper for the rest of the session, said exactly once.

        Counts strikes, not outcomes: the priming warm-up failure doesn't
        strike, so the primed path fences at 1 (two outcomes) — saying
        "failed start(s)" there would undercount.
        """
        self.fenced = True
        logger.warning(
            "Kokoro unavailable (%s) after %d strike(s); using Piper "
            "until restart — re-run `easyspeak --provision-kokoro` to re-check.",
            why,
            self.strikes,
        )

    def _check_flavor_drift(self):
        """Warn once when the installed onnxruntime lost the provisioned flavor.

        The provisioner records the flavor it installed in provisioned.json; an
        app update reinstalls the CPU `onnxruntime` the deb build owns,
        silently demoting a GPU engine to CPU. The engine still starts — the
        warning just keeps the loss from being silent. Everything here is
        tolerant: no file, corrupt JSON, an unknown flavor, a malformed
        installer-written RECORD, or an unidentifiable installed distribution
        all skip silently — a probe crash must never cost a spoken phrase.
        """
        if self._drift_checked:
            return
        self._drift_checked = True
        try:
            record = json.loads(
                (config.KOKORO_DIR / "provisioned.json").read_text(encoding="utf-8")
            )
            flavor = record["flavor"]
        except (OSError, ValueError, KeyError, TypeError):
            return
        try:
            installed = _installed_onnxruntime_flavor()
        except Exception:  # best-effort probe: a malformed install must not
            installed = None  # cost a spoken phrase — treat as unknown flavor
        if (
            flavor in _ONNXRUNTIME_FLAVORS.values()
            and installed is not None
            and installed != flavor
        ):
            logger.warning(
                "Kokoro was provisioned for the %s flavor of onnxruntime, but "
                "the %s flavor is installed; re-run `easyspeak "
                "--provision-kokoro` to restore it.",
                flavor,
                installed or "unidentifiable",
            )

    def begin_teardown(self):
        """Mark the pipeline as shutting down: engine EOFs are deliberate now.

        drain() closes the worker's stdin, whose clean exit would otherwise
        look exactly like a mid-stream death to the reader thread — with the
        flag set, `note_not_ready` strikes nothing.
        """
        self._tearing_down = True

    def speak(self, text):
        """Text-to-speech output.

        Non-blocking: the phrase is handed to a warm piper process that streams
        audio to the player, so this returns immediately and the speech plays
        concurrently with whatever the caller does next.
        """
        text = text.strip()
        if not text:
            return
        logger.info("💬 %s", text)
        for _ in range(2):
            try:
                self.ensure()
                self._piper.stdin.write((text + "\n").encode())
                self._piper.stdin.flush()
                return
            except (BrokenPipeError, OSError, ValueError):
                self._kill_speech()  # tear down the broken pipeline, then retry
        logger.debug("speech pipeline unavailable; dropped phrase: %s", text)

    @staticmethod
    def _reap(proc):
        """Kill a process, close its parent-side pipes, and wait for it, best-effort.

        Both pipeline processes are spawned with stdin=PIPE, so the parent holds a pipe
        fd for each; without closing them here, a repeatedly rebuilt pipeline would leak
        two fds per cycle until it hits the fd limit. kill() polls first and suppresses
        the PID-reuse race internally on Python 3.10+, but ProcessLookupError is named
        anyway to stay safe on other versions; AttributeError covers a malformed process
        handle and TimeoutExpired a process that refuses to die.
        """
        for name in ("stdin", "stdout", "stderr"):
            handle = getattr(proc, name, None)  # tolerate a handle missing these
            if handle is not None:
                with contextlib.suppress(AttributeError, OSError):
                    handle.close()
        try:
            proc.kill()
            proc.wait(timeout=1)
        except (AttributeError, ProcessLookupError, TimeoutExpired):
            pass

    def _kill_speech(self):
        """Stop the pipeline at once (no wait for playback) so it can rebuild."""
        # Any reader thread still on the ready fd is about to see the EOF this
        # kill causes; bumping the generation marks that EOF as self-inflicted
        # so it never counts as an engine death. Residual window: a worker that
        # died on its own microseconds before this kill loses its strike to the
        # gate — the next spawn's outcome still counts toward the fence.
        self._generation += 1
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
        """Flush pending speech, wait for playback, then stop the pipeline.

        Used on shutdown so a final phrase (e.g. "Goodbye.") is heard in full before the
        process exits.
        """
        self.begin_teardown()  # the worker's deliberate stdin-EOF exit strikes nothing
        piper, player = self._piper, self._player
        self._piper = self._player = None
        if piper is not None:
            self._close(piper)
        if player is not None:
            self._close(player)
