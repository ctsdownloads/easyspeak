"""EasySpeak Core - Voice Control for Linux.

Loads plugins from plugins/ folder automatically.
Uses OpenWakeWord for fast wake detection.
"""

import contextlib
import importlib
import logging
import os
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np
import pyaudio
from openwakeword.model import Model as WakeWordModel

from .config import (
    COMMAND_PROMPT,
    FOLLOWUP_IDLE_ROUNDS,
    HOTKEY_COMBO,
    HOTKEY_ENABLED,
    MISUNDERSTAND_GRACE,
    SILENCE_DURATION,
    SILENCE_THRESHOLD,
    WAKE_COOLDOWN,
    WAKE_THRESHOLD,
    WAKE_WORD,
    WHISPER_COMPUTE_TYPE,
    WHISPER_CPU_THREADS,
    WHISPER_MODEL,
    load_whisper_model,
)
from .gnome_extension import ensure_extension
from .hotkey import HotkeyListener
from .speech import SpeechPipeline, suppressed_c_stderr
from .tray import Tray, TrayAction

logger = logging.getLogger(__name__)

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
        self.last_misunderstand_time = 0
        # Persistent text-to-speech pipeline (piper -> audio player) so the
        # voice model is loaded only once.
        self.speech = SpeechPipeline()
        # GNOME panel indicator: owns the icon and the asleep lifecycle.
        self.tray = Tray(speak=self.speak)
        # Hold-to-dictate keyboard activation; the dictation plugin registers
        # the session to run while the combo is held (see register_push_to_talk).
        self.hotkey = HotkeyListener(HOTKEY_COMBO, HOTKEY_ENABLED)
        self._push_to_talk = None

    # --- Utilities for plugins ---

    def host_run(self, cmd, background=False):
        """Run a shell command."""
        if background:
            return subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        return subprocess.run(cmd, capture_output=True, text=True)

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
        cmd = cmd.lower()
        for wake in [
            "hey jarvis",
            "hey jarvis,",
            "hey, jarvis",
            "hey, jarvis,",
            "hey jarvis.",
            "jarvis",
            "jarvis,",
        ]:
            cmd = cmd.replace(wake, "").strip()
        cmd = cmd.strip(".,!? ")
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

    def is_silence(self, audio_chunk):
        """Return True if the audio chunk's mean amplitude is below the threshold."""
        return np.abs(audio_chunk).mean() < SILENCE_THRESHOLD

    def record_until_silence(self, should_continue=None):
        """Record mic audio until a short silence, capped at five seconds.

        Returns the captured PCM bytes. Plugin-facing. `should_continue` (used by
        push-to-talk) lets a key release cut the recording short instead of waiting out
        the silence window.
        """
        frames = []
        silent_chunks = 0
        chunks_needed = int(SILENCE_DURATION * 16000 / 1600)

        for i in range(int(5 * 16000 / 1600)):
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

    def transcribe(self, audio_data, prompt=None):
        """Transcribe raw PCM audio to text with Whisper.

        `prompt` biases recognition (defaults to the command vocabulary). Plugin-facing.
        """
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            with wave.open(f.name, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(audio_data)

            use_prompt = prompt or COMMAND_PROMPT
            segments, _ = self.whisper.transcribe(
                f.name, initial_prompt=use_prompt, beam_size=1, vad_filter=True
            )
            text = " ".join([s.text for s in segments]).strip()
            os.remove(f.name)
            return text

    # --- Main loop ---

    def _reset_detector(self):
        """Reset the wake detector and drop buffered mic audio.

        Stale or half-primed state can't then fire a spurious wake.
        """
        self.wakeword.reset()
        self.flush_stream()

    def _play_wake_chime(self):
        """Play the wake acknowledgement sound, then flush the mic.

        Flushing drops the chime audio that bled into the mic so it isn't mistaken for
        the user speaking.
        """
        subprocess.run(
            ["paplay", "/usr/share/sounds/freedesktop/stereo/message.oga"],
            capture_output=True,
        )
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
        self.whisper = load_whisper_model()

        # The GNOME Shell extension powers both the panel indicator and the
        # mouse grid, so core (not a plugin) owns installing/refreshing/enabling
        # it before anything starts driving it over D-Bus.
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
            # PortAudio probes every ALSA/JACK device on init, spamming stderr
            # about hardware this machine lacks; redirect fd 2 to silence that
            # C-level noise. PyAudio init emits no Python stderr of its own; the
            # stream is opened separately by _open_stream().
            with suppressed_c_stderr():
                self.audio = pyaudio.PyAudio()
            self._open_stream()

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
                audio_data = np.frombuffer(pcm, dtype=np.int16)

                audio_buffer.append(pcm)
                if len(audio_buffer) > 50:
                    audio_buffer.pop(0)

                prediction = self.wakeword.predict(audio_data)
                score = prediction.get(WAKE_WORD, 0)

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
