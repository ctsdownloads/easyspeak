# How it works

- **Wake word** — OpenWakeWord detects "Hey Jarvis" instantly
- **Speech-to-text** — faster-whisper transcribes commands locally
- **Text-to-speech** — Piper provides voice feedback
- **Mouse control** — GNOME Shell extension with Clutter virtual input
- **Browser scroll** — JavaScript injection via qutebrowser IPC
- **Dictation** — AT-SPI accessibility framework

All processing happens locally. No data leaves your machine.

## File structure

```
easyspeak/
├── pyproject.toml
├── src
│   ├── extension.js           # GNOME Shell extension (bundled as package data)
│   ├── extension-helpers.js   # Pure JS helpers imported by extension.js
│   ├── metadata.json          # Extension metadata
│   ├── core
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   ├── about.py           # Standalone libadwaita "About" window
│   │   ├── cli.py             # CLI entry point: argument parsing + logging
│   │   ├── config.py          # Tuning constants + Whisper model factory
│   │   ├── gnome_extension.py # Installs/refreshes/enables the extension
│   │   ├── log.py             # Logging setup
│   │   ├── main.py            # EasySpeak class + main loop
│   │   ├── mediakeys.py       # Replays multimedia keys via Mutter
│   │   ├── speech.py          # Persistent piper -> player pipeline
│   │   └── tray.py            # Panel indicator + asleep lifecycle
│   └── plugins
│       ├── __init__.py
│       ├── 00_eyetrack.py     # Head tracking (experimental)
│       ├── 00_mousegrid.py    # Grid overlay mouse control
│       ├── apps.py            # Application launcher
│       ├── browser.py         # Qutebrowser control + auto-config
│       ├── dictation.py       # Voice-to-text + AT-SPI enablement
│       ├── files.py           # Folder navigation
│       ├── media.py           # Playback controls
│       ├── sleep.py           # Voice deactivate
│       ├── system.py          # Volume, brightness, DND
│       └── zz_base.py         # Help and exit
└── tests
    ├── acceptance             # Gherkin scenarios (pytest-bdd)
    ├── benchmarks             # pytest-benchmark suites for bencher.dev
    ├── integration            # tests against real binaries
    └── unit                   # tests for src/core/ and src/plugins/
```

## GNOME Shell extension

On first start, core auto-installs the GNOME Shell extension to the user-local
extensions directory (unless GNOME already sees it via a system-wide install).
Files copied:

```
~/.local/share/gnome-shell/extensions/easyspeak@local/
├── extension.js
├── extension-helpers.js
└── metadata.json
```

The extension powers both the panel indicator and the mouse grid. On Wayland,
GNOME Shell only scans for extensions at login, so a `oneshot` systemd *user*
unit (installed by EasySpeak) re-copies the bundled files before the shell loads
them at each login. See [`core.gnome_extension`][core.gnome_extension]
for the full lifecycle.
