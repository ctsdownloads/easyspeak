#!/usr/bin/env python3
"""
EasySpeak Core - Voice Control for Linux

Loads plugins from plugins/ folder automatically.
Uses OpenWakeWord for fast wake detection.
"""

import importlib
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
from .speech import SpeechPipeline, suppressed_c_stderr
from .tray import Tray, TrayAction

# =============================================================================
# CORE CLASS
# =============================================================================


class EasySpeak:
    def __init__(self):
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
        self.last_misunderstand_time = 0
        # Persistent text-to-speech pipeline (piper -> audio player) so the
        # voice model is loaded only once.
        self.speech = SpeechPipeline()
        # GNOME panel indicator: owns the icon and the asleep lifecycle.
        self.tray = Tray(speak=self.speak)

    # --- Utilities for plugins ---

    def host_run(self, cmd, background=False):
        """Run a shell command."""
        if background:
            return subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        return subprocess.run(cmd, capture_output=True, text=True)

    def speak(self, text):
        """Speak a phrase. Stable plugin-facing API; delegates to the pipeline."""
        self.speech.speak(text)

    def tap_key(self, keycode):
        """Replay a multimedia key so the desktop renders its native feedback.

        Returns True if the key was injected, False if unavailable (e.g. a
        non-GNOME session) so the caller can fall back to a silent change.
        jeepney is imported lazily so the dependency isn't needed to load.
        """
        try:
            from . import mediakeys

            mediakeys.tap_key(keycode)
            return True
        except Exception:
            return False

    def deactivate(self):
        """Request the assistant go to sleep: release the mic and stop wake
        detection until reactivated from the tray. Plugin-facing; the actual
        release happens at the next main-loop iteration (handled by the tray
        controller) so the triggering command can finish, and speak, first."""
        self.tray.request_sleep()

    # --- Plugin management ---

    def load_plugins(self):
        plugins_dir = Path(__file__).parent.parent / "plugins"
        if not plugins_dir.exists():
            print("No plugins directory found")
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
                    print(f"  ✓ Loaded: {module.NAME}")
                else:
                    print(f"  ✗ Invalid plugin: {file.name} (missing NAME or handle)")
            except Exception as e:
                print(f"  ✗ Failed to load {file.name}: {e}")

    def get_all_commands(self):
        """Get all commands from all plugins for help text"""
        commands = []
        for plugin in self.plugins:
            if hasattr(plugin, "COMMANDS"):
                commands.extend(plugin.COMMANDS)
        return commands

    def route_command(self, cmd):
        """Route command to appropriate plugin. Returns False to exit."""
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
                elif result is False:
                    return False
            except Exception as e:
                print(f"Plugin error ({plugin.NAME}): {e}")

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
        """Display the command list via the plugin that owns it (the base
        plugin's ``show_help``), so the help text isn't duplicated here."""
        for plugin in self.plugins:
            if hasattr(plugin, "show_help"):
                plugin.show_help(self)
                return

    # --- Audio ---

    def _open_stream(self):
        """Open the microphone input stream.

        PortAudio probes every ALSA/JACK device on open, spamming stderr about
        hardware this machine lacks; hide that C-level noise while keeping our
        own Python output intact.
        """
        with suppressed_c_stderr():
            self.stream = self.audio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=16000,
                input=True,
                frames_per_buffer=1280,
            )

    def _close_stream(self):
        """Release the microphone so other apps — and GNOME's privacy mic
        indicator — see it as free. The PyAudio instance is kept for reopening."""
        if self.stream is None:
            return
        for release in (self.stream.stop_stream, self.stream.close):
            try:
                release()
            except OSError:
                pass
        self.stream = None

    def flush_stream(self):
        """Flush any remaining audio data from the stream buffer."""
        try:
            self.stream.read(
                self.stream.get_read_available(),
                exception_on_overflow=False,
            )
        except:
            pass  # intentionally catch all to prevent cleanup failures

    def is_silence(self, audio_chunk):
        return np.abs(audio_chunk).mean() < SILENCE_THRESHOLD

    def record_until_silence(self):
        frames = []
        silent_chunks = 0
        chunks_needed = int(SILENCE_DURATION * 16000 / 1600)

        for i in range(int(5 * 16000 / 1600)):
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

    def wait_for_speech(self, timeout=5):
        for _ in range(int(timeout * 16000 / 1600)):
            pcm = self.stream.read(1600, exception_on_overflow=False)
            if not self.is_silence(np.frombuffer(pcm, dtype=np.int16)):
                return pcm
        return None

    def transcribe(self, audio_data, prompt=None):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wf = wave.open(f.name, "wb")
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(audio_data)
            wf.close()

            use_prompt = prompt if prompt else COMMAND_PROMPT
            segments, _ = self.whisper.transcribe(
                f.name, initial_prompt=use_prompt, beam_size=1, vad_filter=True
            )
            text = " ".join([s.text for s in segments]).strip()
            os.remove(f.name)
            return text

    # --- Main loop ---

    def _reset_detector(self):
        """Clear the wake detector's feature buffer and drop buffered mic audio,
        so stale or half-primed state can't fire a spurious wake."""
        self.wakeword.reset()
        self.flush_stream()

    def _play_wake_chime(self):
        """Play the wake acknowledgement sound, then flush the audio it bled
        into the mic so it isn't mistaken for the user speaking."""
        subprocess.run(
            ["paplay", "/usr/share/sounds/freedesktop/stereo/message.oga"],
            capture_output=True,
        )
        self.flush_stream()

    def _drain_feedback(self):
        """Wait for the spoken "didn't understand" feedback to finish playing,
        then flush the mic. speak() is non-blocking, so flushing alone leaves the
        still-playing tail for the open mic to transcribe into the next
        escalation (e.g. opening help) with no one having spoken."""
        self.speech.drain()
        self.flush_stream()

    def _capture_command_session(self):
        """Capture and route commands after a wake until none is pending.

        Usually one command, but a repeated misunderstanding shows help and
        re-arms keep_listening so the user can retry without the wake word.
        After any "didn't understand" the feedback is drained before listening
        again. Returns True if a command asked the daemon to exit.
        """
        self.keep_listening = True
        while self.keep_listening:
            self.keep_listening = False
            self.unrecognized = False

            first = self.wait_for_speech(timeout=5)
            if first:
                audio = first + self.record_until_silence()
                cmd = self.transcribe(audio)
                if cmd:
                    print(f"👂 {cmd}")
                    if not self.route_command(cmd.lower().strip(".,!? ")):
                        return True
                    self.wakeword.reset()
                    self.flush_stream()
            else:
                self.speak("I didn't hear anything.")

            if self.unrecognized:
                self._drain_feedback()
        return False

    def run(self):
        print("Loading OpenWakeWord...")
        self.wakeword = WakeWordModel()

        print(
            f"Loading Whisper ({WHISPER_MODEL}, {WHISPER_COMPUTE_TYPE}, "
            f"cpu_threads={WHISPER_CPU_THREADS or 'auto'})..."
        )
        self.whisper = load_whisper_model()

        # The GNOME Shell extension powers both the panel indicator and the
        # mouse grid, so core (not a plugin) owns installing/refreshing/enabling
        # it before anything starts driving it over D-Bus.
        ensure_extension()

        print("\nLoading plugins...")
        self.load_plugins()

        if not self.plugins:
            print("No plugins loaded. Exiting.")
            return

        # Warm up the text-to-speech pipeline now so the piper model is loaded
        # during startup, not on the first spoken response.
        print("Warming up speech...")
        try:
            self.speech.ensure()
        except OSError:
            print("Speech unavailable; continuing without it.")

        print("""
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
            print("Listening for wake word...")
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
                    print("Listening for wake word...")
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

                    print(f"🎤 Wake! (confidence: {score:.2f})")

                    self._reset_detector()
                    audio_buffer = []
                    self._play_wake_chime()

                    if self._capture_command_session():
                        break

                    audio_buffer = []
                    print("Listening for wake word...")

        except KeyboardInterrupt:
            print("\nBye!")
        finally:
            # Hide the indicator so the daemon's exit doesn't leave a stale icon.
            self.tray.stopped()
            self.speech.drain()
            if self.stream is not None:
                self.stream.stop_stream()
                self.stream.close()
            if self.audio is not None:
                self.audio.terminate()


def run():
    """Start the application."""
    app = EasySpeak()
    app.run()
