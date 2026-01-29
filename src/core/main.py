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
from faster_whisper import WhisperModel
from openwakeword.model import Model as WakeWordModel

# =============================================================================
# CONFIGURATION
# =============================================================================

WAKE_WORD = "hey_jarvis"  # OpenWakeWord model name
PIPER_MODEL = os.path.expanduser("~/.local/share/piper/en_US-amy-medium.onnx")
WHISPER_MODEL = "base.en"
SILENCE_THRESHOLD = 300
SILENCE_DURATION = 0.3
WAKE_THRESHOLD = 0.5
WAKE_COOLDOWN = 3.0  # Seconds to ignore wake word after trigger

# Prompt to help Whisper recognize common commands
COMMAND_PROMPT = (
    "numbers, scroll, click, open, close, back, forward, volume, brightness, stop"
)

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

    # --- Utilities for plugins ---

    def host_run(self, cmd, background=False):
        """Run a shell command."""
        if background:
            return subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        return subprocess.run(cmd, capture_output=True, text=True)

    def speak(self, text):
        """Text-to-speech output."""
        print(f"💬 {text}")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            output_file = f.name

        subprocess.Popen(
            ["piper", "--model", PIPER_MODEL, "--output_file", output_file],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).communicate(input=text.encode())

        subprocess.run(
            ["ffplay", "-nodisp", "-autoexit", output_file],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        os.remove(output_file)

    # --- Plugin management ---

    def load_plugins(self):
        plugins_dir = Path(__file__).parent / "plugins"
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

        print("Loading Whisper...")
        self.whisper = WhisperModel(WHISPER_MODEL, compute_type="int8")

        print("\nLoading plugins...")
        self.load_plugins()

        if not self.plugins:
            print("No plugins loaded. Exiting.")
            return

        print("""
╔══════════════════════════════════════════╗
║            EasySpeak                     ║
╠══════════════════════════════════════════╣
║  Wake word: "Hey Jarvis"                 ║
║  Say "help" for available commands       ║
╚══════════════════════════════════════════╝
""")

        self.audio = pyaudio.PyAudio()
        self.stream = self.audio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=16000,
            input=True,
            frames_per_buffer=1280,
        )

        try:
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
            self.stream.stop_stream()
            self.stream.close()
            self.audio.terminate()


if __name__ == "__main__":
    app = EasySpeak()
    app.run()
