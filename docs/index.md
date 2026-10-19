# EasySpeak

Voice control for Linux desktops. Fully local, no cloud, Wayland-native.

Say "Hey Jarvis" and control your desktop with your voice.

!!! warning "Early development"
    This project works but is not polished. Expect bugs, incomplete docs, and
    changes without notice.

## Why EasySpeak?

Linux desktop voice control is a gap. Talon exists but has a steep learning
curve and costs money for the full version. Most other tools are X11-only,
abandoned, or cloud-dependent.

EasySpeak is:

- **Free and open source** — GPL-3.0 licensed, no paywalls
- **Fully local** — No cloud, no accounts, no data leaving your machine
- **Wayland-native** — Works on modern GNOME and KDE Plasma desktops where X11 tools fail
- **Simple** — Say "Hey Jarvis, open downloads" and it works
- **Extensible** — Drop a Python file in `plugins/` to add commands

Built for people with RSI, accessibility needs, hands-busy workflows, or anyone
who wants to talk to their computer.

## Features

Current and in active development:

- **Wake word activation** — Hands-free with "Hey Jarvis"
- **Mouse grid** — Navigate anywhere on screen with voice ("grid", "3 7 5", "click")
- **Head tracking** — Control cursor with head movement (experimental)
- **Browser control** — Qutebrowser integration with link hints, tabs, scrolling
- **Dictation** — Voice-to-text in any text field with punctuation commands
- **App launcher** — Open and close applications by name
- **Media control** — Play, pause, skip via MPRIS
- **System controls** — Volume, brightness, do not disturb
- **Fully local** — pyopen-wakeword + Parakeet (or Whisper) + Piper, plus optional Kokoro voices, no cloud services
- **Plugin architecture** — Easy to extend

## Demo

[![EasySpeak demo and new updates](https://img.youtube.com/vi/dl5m2Zo1oIE/maxresdefault.jpg)](https://www.youtube.com/watch?v=2G0Wz1yjRBw)

Matt Hartley walks through [the current state of EasySpeak](https://www.youtube.com/watch?v=2G0Wz1yjRBw).
See also [the first demo](https://www.youtube.com/watch?v=dl5m2Zo1oIE) from the start of the project.

## Where to next?

- [Installation](installation.md) — system packages, Python, Piper TTS, optional Kokoro
- [Usage](usage.md) — running the daemon and the wake word
- [Commands](commands.md) — the full command reference
- [Writing Plugins](plugins.md) — extend EasySpeak with a Python file
- [Troubleshooting](troubleshooting.md) — common problems and fixes
- [How It Works](how-it-works.md) — the architecture
- [API Reference](reference/core.md) — generated from the source docstrings
- [License](license.md)

## Acknowledgments

- [pyopen-wakeword](https://github.com/rhasspy/pyopen-wakeword) — Wake word detection
- [faster-whisper](https://github.com/guillaumekln/faster-whisper) — Speech recognition
- [Piper](https://github.com/OHF-Voice/piper1-gpl) — Text-to-speech (we use the last standalone binary from the original [rhasspy/piper](https://github.com/rhasspy/piper) repo)
- [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) — Optional text-to-speech engine, speaking the [Kokoro-82M](https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX) model you provision with `easyspeak --provision-kokoro`
- [Talon](https://talonvoice.com/) — Inspiration for voice control concepts
