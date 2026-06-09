#!/usr/bin/env python3
"""
EasySpeak Core - Voice Control for Linux

Loads plugins from plugins/ folder automatically.
Uses OpenWakeWord for fast wake detection.
"""

import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path
from subprocess import TimeoutExpired

import numpy as np
import pyaudio
from openwakeword.model import Model as WakeWordModel

from .config import (
    COMMAND_PROMPT,
    PIPER_MODEL,
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

# =============================================================================
# CORE CLASS
# =============================================================================

# Seconds to wait after spawning the piper -> player pipeline before trusting
# it: long enough for an immediate failure (bad model, bad flag) to surface,
# short enough to barely register during the one-time warmup.
SPEECH_SPAWN_GRACE = 0.2


class EasySpeak:
    def __init__(self):
        self.plugins = []
        self.whisper = None
        self.wakeword = None
        self.audio = None
        self.stream = None
        self.last_wake_time = 0
        # Persistent text-to-speech pipeline (piper -> audio player) so the
        # voice model is loaded only once.
        self._piper = None
        self._player = None

    # --- Utilities for plugins ---

    def host_run(self, cmd, background=False):
        """Run a shell command."""
        if background:
            return subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        return subprocess.run(cmd, capture_output=True, text=True)

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

    def _ensure_speech(self):
        """Spawn the persistent piper -> player pipeline if not already running.

        Keeping piper alive avoids reloading its model (~2s) on every phrase,
        and streaming raw audio straight to the player means playback starts as
        soon as synthesis does instead of after a temp WAV is fully written.
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
                self._ensure_speech()
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
            EasySpeak._reap(proc)

    def _drain_speech(self):
        """Flush pending speech and wait for playback to finish, then stop the
        pipeline. Used on shutdown so a final phrase (e.g. "Goodbye.") is heard
        in full before the process exits."""
        piper, player = self._piper, self._player
        self._piper = self._player = None
        if piper is not None:
            self._close(piper)
        if player is not None:
            self._close(player)

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

        if not cmd:
            return True

        for plugin in self.plugins:
            try:
                result = plugin.handle(cmd, self)
                if result is True:
                    return True
                elif result is False:
                    return False
            except Exception as e:
                print(f"Plugin error ({plugin.NAME}): {e}")

        self.speak("I didn't understand. Say help for commands.")
        return True

    # --- Audio ---

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

    def run(self):
        print("Loading OpenWakeWord...")
        self.wakeword = WakeWordModel()

        print(
            f"Loading Whisper ({WHISPER_MODEL}, {WHISPER_COMPUTE_TYPE}, "
            f"cpu_threads={WHISPER_CPU_THREADS or 'auto'})..."
        )
        self.whisper = load_whisper_model()

        print("\nLoading plugins...")
        self.load_plugins()

        if not self.plugins:
            print("No plugins loaded. Exiting.")
            return

        # Warm up the text-to-speech pipeline now so the piper model is loaded
        # during startup, not on the first spoken response.
        print("Warming up speech...")
        try:
            self._ensure_speech()
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
            self.audio = pyaudio.PyAudio()
            self.stream = self.audio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=16000,
                input=True,
                frames_per_buffer=1280,
            )

            print("Listening for wake word...")
            audio_buffer = []

            while True:
                pcm = self.stream.read(1280, exception_on_overflow=False)
                audio_data = np.frombuffer(pcm, dtype=np.int16)

                audio_buffer.append(pcm)
                if len(audio_buffer) > 50:
                    audio_buffer.pop(0)

                prediction = self.wakeword.predict(audio_data)
                score = prediction.get(WAKE_WORD, 0)

                if score > WAKE_THRESHOLD:
                    # Cooldown check - ignore if triggered recently
                    now = time.time()
                    if now - self.last_wake_time < WAKE_COOLDOWN:
                        continue
                    self.last_wake_time = now

                    print(f"🎤 Wake! (confidence: {score:.2f})")

                    # Reset everything
                    self.wakeword.reset()
                    audio_buffer = []
                    self.flush_stream()

                    # Audio feedback first
                    subprocess.run(
                        ["paplay", "/usr/share/sounds/freedesktop/stereo/message.oga"],
                        capture_output=True,
                    )

                    # Flush any audio captured during beep
                    self.flush_stream()

                    # Wait for user to start speaking (up to 5 seconds)
                    first = self.wait_for_speech(timeout=5)

                    if first:
                        # User started speaking, record until they stop
                        audio = first + self.record_until_silence()
                        cmd = self.transcribe(audio)
                        if cmd:
                            print(f"👂 {cmd}")
                            if not self.route_command(cmd.lower().strip(".,!? ")):
                                break
                            self.wakeword.reset()
                            self.flush_stream()
                    else:
                        self.speak("I didn't hear anything.")

                    audio_buffer = []
                    print("Listening for wake word...")

        except KeyboardInterrupt:
            print("\nBye!")
        finally:
            self._drain_speech()
            if self.stream is not None:
                self.stream.stop_stream()
                self.stream.close()
            if self.audio is not None:
                self.audio.terminate()


def run():
    """Start the application."""
    app = EasySpeak()
    app.run()
