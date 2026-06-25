# EasySpeak [![PyPI](https://img.shields.io/pypi/v/easyspeak-linux)](https://pypi.org/project/easyspeak-linux/)

Voice control for Linux desktops. Fully local, no cloud, Wayland-native.

Say "Hey Jarvis" and control your desktop with your voice.

[![License](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](https://github.com/ctsdownloads/easyspeak/blob/main/LICENSE)
[![Platform](https://img.shields.io/badge/platform-Linux-lightgrey.svg)](https://ctsdownloads.github.io/easyspeak/installation/)
[![Desktop](https://img.shields.io/badge/desktop-GNOME%20%7C%20Wayland-green.svg)](https://ctsdownloads.github.io/easyspeak/how-it-works/)
[![Status](https://img.shields.io/badge/status-Alpha-orange.svg)](https://github.com/ctsdownloads/easyspeak/releases)
[![Pipeline](https://github.com/ctsdownloads/easyspeak/actions/workflows/pipeline.yml/badge.svg)](https://github.com/ctsdownloads/easyspeak/actions/workflows/pipeline.yml)
[![Safety](https://github.com/ctsdownloads/easyspeak/actions/workflows/safety.yml/badge.svg)](https://github.com/ctsdownloads/easyspeak/actions/workflows/safety.yml)
[![Publish](https://github.com/ctsdownloads/easyspeak/actions/workflows/publish.yml/badge.svg)](https://github.com/ctsdownloads/easyspeak/actions/workflows/publish.yml)
[![Release](https://github.com/ctsdownloads/easyspeak/actions/workflows/release.yml/badge.svg)](https://github.com/ctsdownloads/easyspeak/actions/workflows/release.yml)
[![Benchmarks](https://img.shields.io/badge/%F0%9F%90%B0%20Bencher-performance-FD7E14.svg)](https://bencher.dev/perf/easyspeak)
[![Docs](https://github.com/ctsdownloads/easyspeak/actions/workflows/docs.yml/badge.svg)](https://ctsdownloads.github.io/easyspeak/)

> ⚠️ **Early development.** This project works but is not polished. Expect bugs, incomplete docs, and changes without notice.

## Why EasySpeak?

Linux desktop voice control is a gap. Talon exists but has a steep learning curve and costs money for the full version. Most other tools are X11-only, abandoned, or cloud-dependent.

EasySpeak is **free and open source** (GPL-3.0), **fully local** (no cloud, no accounts), **Wayland-native**, **simple** ("Hey Jarvis, open downloads"), and **extensible** (drop a Python file in `plugins/`). Built for people with RSI, accessibility needs, hands-busy workflows, or anyone who wants to talk to their computer.

- Wake word activation ("Hey Jarvis")
- Mouse grid and experimental head tracking
- Browser control, dictation, app launcher, media and system controls
- OpenWakeWord + Whisper + Piper, all on-device

## Demo

[![Demo](https://img.youtube.com/vi/dl5m2Zo1oIE/maxresdefault.jpg)](https://www.youtube.com/watch?v=dl5m2Zo1oIE)

## Quickstart

Requirements: Linux with GNOME Shell 47+ on Wayland, Python 3.12, a microphone, and ~2 GB disk for models. Tested on Fedora 43.

```bash
# 1. System packages (Fedora; see the docs for the full list)
sudo dnf install python3.12 python3.12-devel gcc portaudio-devel \
  pipewire-utils wireplumber at-spi2-core python3-gobject libadwaita qutebrowser \
  glib2 ffmpeg-free pulseaudio-utils sound-theme-freedesktop

# 2. Get EasySpeak and run it (uv manages the virtualenv for you)
git clone https://github.com/ctsdownloads/easyspeak.git ~/easyspeak
cd ~/easyspeak
uv run easyspeak
```

You also need [Piper TTS](https://ctsdownloads.github.io/easyspeak/installation/#3-piper-tts) installed for voice feedback. See the **[Installation guide](https://ctsdownloads.github.io/easyspeak/installation/)** for the venv-based path, head tracking, and full details.

Prefer prebuilt packages? Grab the `easyspeak` app `.deb`/`.rpm` **plus a language
pack** (e.g. `easyspeak-lang-en`) from the
[Releases page](https://github.com/ctsdownloads/easyspeak/releases) and install them
together — a self-contained, offline install (Python runtime, `piper`, GNOME
extension, and speech models). See the
**[Packaging guide](https://ctsdownloads.github.io/easyspeak/packaging/)**.

Then say "Hey Jarvis" followed by a command. Say "help" to list all commands.

## Documentation

- **[Installation](https://ctsdownloads.github.io/easyspeak/installation/)** — system packages, Python, Piper TTS
- **[Usage](https://ctsdownloads.github.io/easyspeak/usage/)** — running the daemon, CLI flags, configuration
- **[Commands](https://ctsdownloads.github.io/easyspeak/commands/)** — the full command reference
- **[Writing plugins](https://ctsdownloads.github.io/easyspeak/plugins/)** — extend EasySpeak with a Python file
- **[Troubleshooting](https://ctsdownloads.github.io/easyspeak/troubleshooting/)** — common problems and fixes
- **[How it works](https://ctsdownloads.github.io/easyspeak/how-it-works/)** — the architecture
- **[API reference](https://ctsdownloads.github.io/easyspeak/reference/core/)** — generated from the source docstrings
- **[Contributing](https://ctsdownloads.github.io/easyspeak/contributing/)** — how to set up a dev environment and submit changes
- **[License](https://ctsdownloads.github.io/easyspeak/license/)** — GPL-3.0

## Acknowledgments

- [OpenWakeWord](https://github.com/dscripka/openWakeWord) — Wake word detection
- [faster-whisper](https://github.com/guillaumekln/faster-whisper) — Speech recognition
- [Piper](https://github.com/OHF-Voice/piper1-gpl) — Text-to-speech (we use the last standalone binary from the original [rhasspy/piper](https://github.com/rhasspy/piper) repo)
- [Talon](https://talonvoice.com/) — Inspiration for voice control concepts
