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
- **Wayland-native** — Works on modern GNOME desktops where X11 tools fail
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
- **Fully local** — OpenWakeWord + Whisper + Piper, no cloud services
- **Plugin architecture** — Easy to extend

## Demo

[![Demo](https://img.youtube.com/vi/dl5m2Zo1oIE/maxresdefault.jpg)](https://www.youtube.com/watch?v=dl5m2Zo1oIE)

## Where to next?

- [Installation](installation.md) — system packages, Python, Piper TTS
- [Usage](usage.md) — running the daemon and the wake word
- [Commands](commands.md) — the full command reference
- [Writing Plugins](plugins.md) — extend EasySpeak with a Python file
- [Troubleshooting](troubleshooting.md) — common problems and fixes
- [How It Works](how-it-works.md) — the architecture
- [API Reference](reference/core.md) — generated from the source docstrings

## License

GPL-3.0 License. See [LICENSE](https://github.com/ctsdownloads/easyspeak/blob/main/LICENSE) for details.

## Acknowledgments

- [OpenWakeWord](https://github.com/dscripka/openWakeWord) — Wake word detection
- [faster-whisper](https://github.com/guillaumekln/faster-whisper) — Speech recognition
- [Piper](https://github.com/OHF-Voice/piper1-gpl) — Text-to-speech (we use the last standalone binary from the original [rhasspy/piper](https://github.com/rhasspy/piper) repo)
- [Talon](https://talonvoice.com/) — Inspiration for voice control concepts
