"""EasySpeak Core - Voice Control for Linux.

Loads plugins from plugins/ folder automatically.
Uses pyopen-wakeword for fast wake detection.
"""

import contextlib
import importlib
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pyaudio

from .config import (
    COMMAND_PROMPT,
    FOLLOWUP_IDLE_ROUNDS,
    HOTKEY_COMBO,
    MAX_RECORD_SECONDS,
    MISUNDERSTAND_GRACE,
    REQUIRE_WAKE_WORD,
    SILENCE_CALIBRATION_SECONDS,
    SILENCE_DURATION,
    SILENCE_NOISE_MARGIN,
    SILENCE_THRESHOLD,
    SILENCE_THRESHOLD_MAX,
    WAKE_COOLDOWN,
    WAKE_SOUND,
    WAKE_THRESHOLD,
    WAKE_WORD_SPOKEN,
    WHISPER_COMPUTE_TYPE,
    WHISPER_CPU_THREADS,
    WHISPER_MODEL,
    load_whisper_model,
)
from .gnome_extension import ensure_extension
from .hotkey import HotkeyListener
from .speech import SpeechPipeline, suppressed_c_stderr
from .tray import Tray, TrayAction
from .wakeword import WakeWordModel

logger = logging.getLogger(__name__)

SOUND_PLAYERS = (["paplay"], ["pw-play"], ["canberra-gtk-play", "-f"])
SOUND_TIMEOUT = 5.0

WAKE_PREFIXES = (
    "hey jarvis",
    "hey jarvis,",
    "hey, jarvis",
    "hey, jarvis,",
    "hey jarvis.",
    "jarvis",
    "jarvis,",
)


def strip_wake_words(cmd):
    """Remove a leading spoken wake word and surrounding punctuation.

    Only a prefix is removed. Replacing every occurrence anywhere in the utterance
    -- which is what this did -- eats the word out of the middle of a command, so
    "search jarvis" became "search" and a URL containing it lost part of itself.
    Longest prefix first, so "hey jarvis," is matched before "jarvis".
    """
    cmd = cmd.lower().strip()
    for wake in sorted(WAKE_PREFIXES, key=len, reverse=True):
        if cmd == wake:
            return ""
        if cmd.startswith(wake):
            rest = cmd[len(wake) :]
            # Only a prefix if a word actually ends here.
            if not rest or rest[0] in " ,.!?":
                cmd = rest.strip()
                break
    return cmd.strip(".,!? ")


# =============================================================================
# CORE CLASS
# =============================================================================


class EasySpeak:
    """The voice-control daemon: wake detection, transcription, and routing.

    Owns the audio pipeline (wake word -> Whisper), the loaded plugins, the
    text-to-speech pipeline, and the panel indicator, and exposes the small
    plugin-facing API ([`speak`][core.main.EasySpeak.speak],
    [`host_run`][core.main.EasySpeak.host_run],
    [`transcribe`][core.main.EasySpeak.transcribe], ...) that plugins use to act on
    commands.
    """

    def __init__(self):
        """Initialise daemon state; models and audio are loaded later in run()."""
        self.plugins = []
        self.whisper = None
        self.wakeword = None
        self.audio = None
        self.stream = None
        self.last_wake_time = 0
        self.misunderstand_count = 0
        self.help_shown = False
        self.keep_listening = False
        self.unrecognized = False
        self.spoke = False
        # Set by listen_modal when the tray asks to quit from inside a plugin's
        # modal mode, so the request survives the unwind back to the main loop.
        self.exit_requested = False
        self.last_misunderstand_time = 0
        self.require_wake_word = REQUIRE_WAKE_WORD
        # Persistent text-to-speech pipeline (piper -> audio player) so the
        # voice model is loaded only once.
        self.speech = SpeechPipeline()
        # GNOME panel indicator: owns the icon and the asleep lifecycle.
        self.tray = Tray(speak=self.speak)
        # Hold-to-dictate keyboard activation; the dictation plugin registers
        # the session to run while the combo is held (see register_push_to_talk).
        self.hotkey = HotkeyListener(HOTKEY_COMBO)
        self._push_to_talk = None
        # Remembered after the first sound plays, so later ones cost one process.
        self._sound_player = None
        # Raised to suit the room by calibrate_silence() once the mic is open.
        self.silence_threshold = SILENCE_THRESHOLD

    # --- Utilities for plugins ---

    def host_run(self, cmd, background=False, clean_env=False):
        """Run a shell command.

        With clean_env, EasySpeak's injected LD_LIBRARY_PATH and GI_TYPELIB_PATH
        are stripped from the child's environment. The dev flake prepends its own
        libraries (glib among them) to those paths for EasySpeak's own
        dependencies; left in place they leak into spawned desktop apps, which
        then load EasySpeak's flake-pinned libraries instead of their own rpath
        ones. A glib/GIO build mismatch there wedges GTK apps such as the file
        manager. Pass clean_env=True when launching external GUI programs so they
        run in the plain host environment.
        """
        env = None
        if clean_env:
            env = {
                k: v
                for k, v in os.environ.items()
                if k not in ("LD_LIBRARY_PATH", "GI_TYPELIB_PATH")
            }
        if background:
            return subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env
            )
        return subprocess.run(cmd, capture_output=True, text=True, env=env)

    def speak(self, text):
        """Speak a phrase.

        Stable plugin-facing API; delegates to the pipeline.
        """
        self.spoke = True
        self.speech.speak(text)

    def tap_key(self, keycode):
        """Replay a multimedia key so the desktop renders its native feedback.

        Returns True if the key was injected, False if unavailable (e.g. a non-GNOME
        session) so the caller can fall back to a silent change. jeepney is imported
        lazily so the dependency isn't needed to load.
        """
        try:
            from . import mediakeys

            mediakeys.tap_key(keycode)
            return True
        except Exception:
            return False

    def deactivate(self):
        """Request the assistant go to sleep (plugin-facing).

        Releases the mic and stops wake detection until reactivated from the tray. The
        actual release happens at the next main-loop iteration (handled by the tray
        controller) so the triggering command can finish, and speak, first.
        """
        self.tray.request_sleep()

    def register_push_to_talk(self, handler):
        """Register the dictation session the hotkey runs while its combo is held.

        Plugin-facing: the dictation plugin registers here in its setup() so core
        can drive keyboard (silent) activation without importing a plugin
        directly. `handler` takes one `should_continue` predicate and runs
        until it returns False (the keys are released).
        """
        self._push_to_talk = handler

    # --- Plugin management ---

    def load_plugins(self):
        """Discover and import every plugin module from the `plugins/` dir.

        Files are loaded in sorted order (numeric prefixes set load order); names
        starting with `_` are skipped. A module is registered only if it exposes `NAME`
        and `handle`; its optional `setup` hook runs once. Import or setup failures are
        logged and skipped, never fatal.
        """
        plugins_dir = Path(__file__).parent.parent / "plugins"
        if not plugins_dir.exists():
            logger.warning("No plugins directory found")
            return

        sys.path.insert(0, str(plugins_dir.parent))

        for file in sorted(plugins_dir.glob("*.py")):
            if file.name.startswith("_"):
                continue

            module_name = f"plugins.{file.stem}"
            try:
                module = importlib.import_module(module_name)

                if hasattr(module, "NAME") and hasattr(module, "handle"):
                    if hasattr(module, "setup"):
                        module.setup(self)

                    self.plugins.append(module)
                    logger.info("  ✓ Loaded: %s", module.NAME)
                else:
                    logger.warning(
                        "  ✗ Invalid plugin: %s (missing NAME or handle)", file.name
                    )
            except Exception as e:
                logger.warning("  ✗ Failed to load %s: %s", file.name, e)

    def get_all_commands(self):
        """Get all commands from all plugins for help text."""
        commands = []
        for plugin in self.plugins:
            if hasattr(plugin, "COMMANDS"):
                commands.extend(plugin.COMMANDS)
        return commands

    def route_command(self, cmd):
        """Route command to appropriate plugin.

        Returns False to exit.
        """
        cmd = strip_wake_words(cmd)
        self.unrecognized = False

        if not cmd:
            return True

        for plugin in self.plugins:
            try:
                result = plugin.handle(cmd, self)
                if result is True:
                    self.misunderstand_count = 0
                    self.help_shown = False
                    return True
                if result is False:
                    return False
            except Exception:
                logger.exception("Plugin error (%s)", plugin.NAME)

        self._report_not_understood()
        return True

    def _report_not_understood(self):
        """Give gentle spoken feedback that no plugin matched the command.

        Misses within MISUNDERSTAND_GRACE of the last one are dropped: that
        burst is almost always the open mic transcribing this very feedback, and
        reacting would cascade into the help screen with no one having spoken; a
        real retry lands after the feedback plays out, past the window. The
        first real miss apologises, the next escalates to the command list
        (shown once per streak), and further misses keep the mic open without
        repeating it. The feedback never says "help" — the open mic would
        transcribe it and fire the help command in a loop.
        """
        now = time.time()
        if now - self.last_misunderstand_time < MISUNDERSTAND_GRACE:
            return
        self.last_misunderstand_time = now

        self.unrecognized = True
        self.misunderstand_count += 1
        if self.misunderstand_count == 1:
            self.speak("Sorry, I didn't understand.")
            return

        self.speak("I didn't understand.")
        if not self.help_shown:
            self._show_help()
            self.help_shown = True
        self.keep_listening = True

    def _show_help(self):
        """Display the command list via the plugin that owns it.

        Delegates to the base plugin's `show_help` so the help text isn't duplicated
        here.
        """
        for plugin in self.plugins:
            if hasattr(plugin, "show_help"):
                plugin.show_help(self)
                return

    # --- Audio ---

    def _open_stream(self):
        """Open the microphone input stream.

        PortAudio probes every ALSA/JACK device on open, spamming stderr about hardware
        this machine lacks; hide that C-level noise while keeping our own Python output
        intact. When there is no capture device at all PortAudio raises a bare OSError
        (e.g. errno -9996); surface that as an actionable message instead of a raw
        traceback, since it commonly means a headless host such as WSL with no
        microphone bridged in.
        """
        try:
            with suppressed_c_stderr():
                self.stream = self.audio.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=16000,
                    input=True,
                    frames_per_buffer=1280,
                )
        except OSError as exc:
            logger.error(  # noqa: TRY400
                "No microphone input device found (%s). EasySpeak needs a working "
                "PipeWire/PulseAudio or ALSA capture device; this is typically "
                "missing under WSL, which bridges no microphone by default.",
                exc,
            )
            raise SystemExit(1) from exc

    def _close_stream(self):
        """Release the microphone so other apps see it as free.

        Also clears GNOME's privacy mic indicator. The PyAudio instance is kept for
        reopening.
        """
        if self.stream is None:
            return
        for release in (self.stream.stop_stream, self.stream.close):
            with contextlib.suppress(OSError):
                release()
        self.stream = None

    def flush_stream(self):
        """Flush any remaining audio data from the stream buffer."""
        # intentionally suppress everything to prevent cleanup failures
        with contextlib.suppress(Exception):
            self.stream.read(
                self.stream.get_read_available(),
                exception_on_overflow=False,
            )

    def calibrate_silence(self):
        """Measure the room's noise floor and set the silence threshold above it.

        A fixed threshold assumes a quiet room. Where the ambient level sits above
        it -- a fan, a desktop, an air conditioner -- `is_silence` never returns
        True, so nothing ever stops recording early: a three-word command took the
        whole five-second cap and a dictated sentence took twenty, which is most of
        the wait between speaking and seeing text.

        Uses the median chunk level so a cough or a passing car doesn't skew the
        measurement, and clamps the result: never below the configured floor, and
        never so high that speech itself would read as silence.
        """
        override = os.environ.get("EASYSPEAK_SILENCE_THRESHOLD")
        if override:
            with contextlib.suppress(ValueError):
                self.silence_threshold = int(override)
                logger.info(
                    "Silence threshold %d (from environment)", self.silence_threshold
                )
                return

        chunks = []
        for _ in range(int(SILENCE_CALIBRATION_SECONDS * 16000 / 1600)):
            with contextlib.suppress(Exception):
                pcm = self.stream.read(1600, exception_on_overflow=False)
                chunks.append(np.abs(np.frombuffer(pcm, dtype=np.int16)).mean())

        if not chunks:
            return  # no audio to measure; the floor stands

        floor = float(np.median(chunks))
        self.silence_threshold = int(
            min(
                max(floor * SILENCE_NOISE_MARGIN, SILENCE_THRESHOLD),
                SILENCE_THRESHOLD_MAX,
            )
        )
        logger.info(
            "Room noise floor %.0f; silence threshold %d",
            floor,
            self.silence_threshold,
        )

    def is_silence(self, audio_chunk):
        """Return True if the audio chunk's mean amplitude is below the threshold."""
        return np.abs(audio_chunk).mean() < self.silence_threshold

    def record_until_silence(
        self, should_continue=None, max_seconds=None, silence_duration=None
    ):
        """Record mic audio until a short silence, or the cap. Plugin-facing.

        Returns the captured PCM bytes. `should_continue` (used by push-to-talk) lets
        a key release cut the recording short instead of waiting out the silence
        window.

        Both limits are adjustable because a command and a dictated sentence need
        very different ones: the command defaults stopped recording during the pause
        in the middle of a sentence, and truncated anything past five seconds.
        """
        max_seconds = MAX_RECORD_SECONDS if max_seconds is None else max_seconds
        if silence_duration is None:
            silence_duration = SILENCE_DURATION

        frames = []
        silent_chunks = 0
        chunks_needed = int(silence_duration * 16000 / 1600)

        for i in range(int(max_seconds * 16000 / 1600)):
            if should_continue is not None and not should_continue():
                break
            pcm = self.stream.read(1600, exception_on_overflow=False)
            frames.append(pcm)

            if i >= 5:
                if self.is_silence(np.frombuffer(pcm, dtype=np.int16)):
                    silent_chunks += 1
                    if silent_chunks >= chunks_needed:
                        break
                else:
                    silent_chunks = 0

        return b"".join(frames)

    def wait_for_speech(self, timeout=5, should_continue=None):
        """Block until speech is heard, returning its first PCM chunk.

        Returns None if nothing is heard within `timeout` seconds. Plugin-facing.
        `should_continue` (used by push-to-talk) returns None early once it goes False,
        so a key release ends the wait.
        """
        for _ in range(int(timeout * 16000 / 1600)):
            if should_continue is not None and not should_continue():
                return None
            pcm = self.stream.read(1600, exception_on_overflow=False)
            if not self.is_silence(np.frombuffer(pcm, dtype=np.int16)):
                return pcm
        return None

    PROMPT_ECHO_MIN_WORDS = 4

    NUMBER_WORDS = frozenset(
        {
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
        }
    )

    @classmethod
    def _is_prompt_echo(cls, text, prompt):
        """Whether `text` is a verbatim, non-numeric run of words from `prompt`."""
        words = re.sub(r"[^\w\s]", " ", text.lower()).split()
        if len(words) < cls.PROMPT_ECHO_MIN_WORDS:
            return False
        if all(w.isdigit() or w in cls.NUMBER_WORDS for w in words):
            return False
        prompt_words = re.sub(r"[^\w\s]", " ", prompt.lower()).split()
        span = len(words)
        return any(
            prompt_words[i : i + span] == words
            for i in range(len(prompt_words) - span + 1)
        )

    def transcribe(self, audio_data, prompt=None, language="en"):
        """Transcribe raw PCM audio to text with Whisper.

        `prompt` biases recognition (defaults to the command vocabulary), and
        `language` is the Whisper language code to transcribe as. Commands are
        English words, so it takes English; dictation passes the user's
        `LANGUAGE`. Plugin-facing.
        An echo of that prompt is dropped as silence: Whisper hands its own
        `initial_prompt` back when given near-silence, and grid mode was executing
        that as a command.
        """
        samples = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0

        use_prompt = prompt or COMMAND_PROMPT
        started = time.monotonic()
        segments, _ = self.whisper.transcribe(
            samples,
            initial_prompt=use_prompt,
            beam_size=1,
            vad_filter=True,
            language=language,
            # Nothing here reads timestamps, and generating them costs tokens.
            without_timestamps=True,
            condition_on_previous_text=False,
        )
        text = " ".join([s.text for s in segments]).strip()
        logger.debug(
            "transcribed %.1fs of audio in %.2fs",
            len(audio_data) / 32000,
            time.monotonic() - started,
        )

        if text and self._is_prompt_echo(text, use_prompt):
            logger.debug("Ignoring prompt echo: %s", text)
            return ""
        return text

    # --- Modal plugin modes ---

    def listen_modal(
        self,
        label,
        prompt=None,
        timeout=10,
        idle_timeout=30,
        max_record_seconds=None,
        silence_duration=None,
        wake_gated=True,
        language="en",
    ):
        """Yield transcribed commands for a plugin's modal mode. Plugin-facing.

        Plugins that take over the microphone (grid, browser, dictation, head
        tracking) each ran their own `while` loop, which starved everything the main
        loop owns: the tray was never polled, so its Quit and Mute entries and the
        Quick Settings toggle did nothing; and with no idle limit a mode never ended
        on its own, so an unattended session stayed in it indefinitely with the wake
        word unreachable. Driving the loop from here keeps those alive — the tray is
        polled between utterances, and the mode ends `idle_timeout` seconds after the
        last command it understood.

        The deadline is wall-clock and only a recognised command pushes it back.
        Counting silent *rounds* instead doesn't work in a real room: any sound over
        the threshold ends the wait early, so ambient noise both resets a round-based
        counter forever and makes each round take an unpredictable amount of time.

        `label` names the mode in the exit log line and the spoken notice, and
        `prompt` biases Whisper towards that mode's vocabulary. `timeout` is how
        long a single listen waits for speech, and `idle_timeout` how long the mode
        survives without a recognised command. `max_record_seconds` and
        `silence_duration` fall back to the command defaults when None; dictation
        passes larger values, since a sentence has pauses in it and runs longer
        than a command. `wake_gated` is False for modes that capture continuous
        speech rather than commands, so `require_wake_word` does not ask for the
        wake word before every dictated sentence. `language` is passed on to
        [`transcribe`][core.main.EasySpeak.transcribe].

        Yields each recognised command, lowercased and stripped of surrounding
        punctuation. The generator simply stops when the mode should end, so a
        caller's `for` loop falls through to its own cleanup.
        """
        if self.spoke:
            self._drain_feedback()
            self.spoke = False

        deadline = time.monotonic() + idle_timeout
        while True:
            # The same poll the wake-word loop runs, so sleep and quit still work
            # while a mode holds the microphone.
            action = self.tray.poll(self._close_stream, self._open_stream)
            if action is TrayAction.QUIT:
                self.exit_requested = True
                return
            if action is TrayAction.RESUME:
                logger.info("%s mode ended: reactivated", label.capitalize())
                self.speak(f"Leaving {label}. Say {WAKE_WORD_SPOKEN} to continue.")
                return

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.info("%s mode ended: idle", label.capitalize())
                self.speak(f"Leaving {label}. Say {WAKE_WORD_SPOKEN} to continue.")
                return

            if (
                wake_gated
                and self.require_wake_word
                and not self.wait_for_wake(timeout=min(timeout, remaining))
            ):
                continue

            self.flush_stream()
            # Never wait past the deadline, so the mode ends on time even when the
            # room is quiet enough that every listen runs its full length.
            first = self.wait_for_speech(timeout=min(timeout, remaining))
            if first is None:
                continue

            rest = self.record_until_silence(
                max_seconds=max_record_seconds, silence_duration=silence_duration
            )
            text = self.transcribe(first + rest, prompt=prompt, language=language)
            if not text:
                # Noise, or an echo of our own prompt. Not a command, so the
                # deadline stands.
                continue

            spoken = strip_wake_words(text)
            if not spoken:
                continue  # the wake word on its own is not a command

            deadline = time.monotonic() + idle_timeout
            self.spoke = False
            yield spoken

            if self.spoke:
                self._drain_feedback()
                self.spoke = False
                deadline = time.monotonic() + idle_timeout

    # --- Main loop ---

    def wait_for_wake(self, timeout):
        """Block until the wake word is heard, then chime. False on timeout.

        The same detector, cooldown and chime the main loop uses, so a mode that
        asks for the wake word behaves exactly like the wake-word loop does.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            pcm = self.stream.read(1280, exception_on_overflow=False)
            score = self.wakeword.predict(pcm)
            if score <= WAKE_THRESHOLD:
                continue
            now = time.time()
            if now - self.last_wake_time < WAKE_COOLDOWN:
                continue
            self.last_wake_time = now
            logger.info("🎤 Wake! (confidence: %.2f)", score)
            self._reset_detector()
            self._play_wake_chime()
            return True
        return False

    def _reset_detector(self):
        """Reset the wake detector and drop buffered mic audio.

        Stale or half-primed state can't then fire a spurious wake.
        """
        self.wakeword.reset()
        self.flush_stream()

    def play_sound(self, sound):
        """Play a short desktop sound, best-effort. Plugin-facing.

        The daemon is voice-first, so an audible cue is often the only signal a
        user gets -- especially with no Piper voice installed, where every spoken
        reply is dropped. Failures are never fatal: this used to be a bare
        `paplay` call, so a machine without pulseaudio-utils took the whole daemon
        down on the first wake word. The working player is remembered after the
        first success, so a mode change costs one process, not three.
        """
        if not Path(sound).exists():
            logger.debug("sound file not found: %s", sound)
            return False
        players = [self._sound_player] if self._sound_player else SOUND_PLAYERS
        for player in players:
            try:
                result = subprocess.run(
                    [*player, str(sound)], capture_output=True, timeout=SOUND_TIMEOUT
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            if result.returncode == 0:
                self._sound_player = player
                return True
        self._sound_player = None
        logger.debug("no working audio player for %s", sound)
        return False

    def _play_wake_chime(self):
        """Play the wake acknowledgement sound, then flush the mic.

        Flushing drops the chime audio that bled into the mic so it isn't mistaken for
        the user speaking.
        """
        self.play_sound(WAKE_SOUND)
        self.flush_stream()

    def _drain_feedback(self):
        """Wait for the "didn't understand" feedback to finish, then flush the mic.

        speak() is non-blocking, so flushing alone leaves the still-playing tail for the
        open mic to transcribe into the next escalation (e.g. opening help) with no one
        having spoken.
        """
        self.speech.drain()
        self.flush_stream()

    def _run_push_to_talk(self):
        """Run a hotkey-triggered dictation session for as long as the keys are held.

        Triggered from the main loop when the silent-activation combo fires.
        Acknowledges with the wake chime — but speaks no prompt, this being the *silent*
        path — then hands off to the registered dictation handler, gating it on the
        still-held key state so releasing the keys ends it. Warns and does nothing if no
        handler is registered (e.g. the dictation plugin didn't load).
        """
        if self._push_to_talk is None:
            logger.warning("Hotkey pressed but no dictation handler is registered.")
            return
        logger.info("⌨️  Hotkey dictation")
        self._reset_detector()
        self._play_wake_chime()
        self._push_to_talk(self.hotkey.is_held)

    def _capture_command_session(self):
        """Capture and route commands after a wake, staying open for follow-ups.

        After a recognized command that gave no spoken reply (e.g. volume), the mic
        stays open so the user can chain commands ("louder", "louder") at their own pace
        without repeating the wake word; the session ends once a couple of quiet listens
        (FOLLOWUP_IDLE_ROUNDS) pass, the wake-time silence times out, or a command
        speaks (whose reply the open mic would otherwise hear). A repeated
        misunderstanding still re-arms keep_listening for the help retry, and its
        feedback is drained before listening again. Returns True if a command asked the
        daemon to exit.
        """
        self.keep_listening = True
        awake = True
        quiet = 0
        while self.keep_listening:
            self.keep_listening = False
            self.unrecognized = False
            self.spoke = False

            heard = self.wait_for_speech(timeout=5)
            if heard is None:
                if awake:
                    self.speak("I didn't hear anything.")
            else:
                cmd = self.transcribe(heard + self.record_until_silence())
                if cmd:
                    logger.info("👂 %s", cmd)
                    if not self.route_command(cmd.lower().strip(".,!? ")):
                        return True
                    # A plugin's modal mode may have taken the tray's Quit while it
                    # held the microphone; honour it now that the stack has unwound.
                    if self.exit_requested:
                        return True
                    self._reset_detector()
                    if not self.unrecognized and not self.spoke:
                        quiet = 0
                        self.keep_listening = True
                elif not awake:
                    quiet += 1
                    self.keep_listening = quiet < FOLLOWUP_IDLE_ROUNDS

            awake = False
            if self.unrecognized:
                self._drain_feedback()
        return False

    def run(self):
        """Load models and plugins, then run the wake-word listen loop forever.

        Blocks until the user quits (voice command, tray, or Ctrl-C), always releasing
        the microphone and draining speech on the way out.
        """
        logger.info("Loading OpenWakeWord...")
        self.wakeword = WakeWordModel()

        logger.info(
            "Loading Whisper (%s, %s, cpu_threads=%s)...",
            WHISPER_MODEL,
            WHISPER_COMPUTE_TYPE,
            WHISPER_CPU_THREADS or "auto",
        )
        try:
            self.whisper = load_whisper_model()
        except RuntimeError as exc:
            logger.error("Cannot start EasySpeak: %s", exc)  # noqa: TRY400
            raise SystemExit(1) from exc

        ensure_extension()

        logger.info("\nLoading plugins...")
        self.load_plugins()

        if not self.plugins:
            logger.error("No plugins loaded. Exiting.")
            return

        # Warm up the text-to-speech pipeline now so the piper model is loaded
        # during startup, not on the first spoken response.
        logger.info("Warming up speech...")
        try:
            self.speech.ensure()
        except OSError:
            logger.warning("Speech unavailable; continuing without it.")

        logger.info("""
╔══════════════════════════════════════════╗
║            EasySpeak                     ║
╠══════════════════════════════════════════╣
║  Wake word: "Hey Jarvis"                 ║
║  Say "help" for available commands       ║
╚══════════════════════════════════════════╝
""")

        try:
            with suppressed_c_stderr():
                self.audio = pyaudio.PyAudio()
            self._open_stream()

            # Measure the room before listening, so silence detection matches it.
            self.calibrate_silence()

            self.tray.started()
            # Start keyboard (silent) activation; no-op if disabled or no
            # /dev/input access. Plugins have registered their handlers by now.
            self.hotkey.start()
            logger.info("Listening for wake word...")
            audio_buffer = []

            while True:
                # The tray controller owns sleep/quit; it releases and reopens
                # the mic via these callbacks so this loop stays about audio.
                action = self.tray.poll(self._close_stream, self._open_stream)
                if action is TrayAction.QUIT:
                    break
                if action is TrayAction.RESUME:
                    self._reset_detector()
                    audio_buffer = []
                    logger.info("Listening for wake word...")
                    continue

                # Keyboard activation bypasses the wake word: dictate while held.
                if self.hotkey.take_activation():
                    self._run_push_to_talk()
                    self._reset_detector()
                    audio_buffer = []
                    logger.info("Listening for wake word...")
                    continue

                pcm = self.stream.read(1280, exception_on_overflow=False)

                audio_buffer.append(pcm)
                if len(audio_buffer) > 50:
                    audio_buffer.pop(0)

                score = self.wakeword.predict(pcm)

                if score > WAKE_THRESHOLD:
                    now = time.time()
                    if now - self.last_wake_time < WAKE_COOLDOWN:
                        continue
                    self.last_wake_time = now

                    logger.info("🎤 Wake! (confidence: %.2f)", score)

                    self._reset_detector()
                    audio_buffer = []
                    self._play_wake_chime()

                    if self._capture_command_session():
                        break

                    audio_buffer = []
                    logger.info("Listening for wake word...")

        except KeyboardInterrupt:
            logger.info("\nBye!")
        finally:
            # Hide the indicator so the daemon's exit doesn't leave a stale icon.
            self.tray.stopped()
            self.hotkey.stop()
            self.speech.drain()
            if self.stream is not None:
                self.stream.stop_stream()
                self.stream.close()
            if self.audio is not None:
                self.audio.terminate()
