# How it works

- **Wake word** — pyopen-wakeword detects "Hey Jarvis" instantly
- **Speech-to-text** — faster-whisper transcribes commands locally
- **Text-to-speech** — Piper provides voice feedback
- **Mouse control** — GNOME Shell extension with Clutter virtual input
- **Browser scroll** — JavaScript injection via qutebrowser IPC
- **Dictation** — clipboard and a synthetic paste keystroke, with AT-SPI used to
  check something is focused (and as a fallback where no clipboard tool exists)

All processing happens locally. No data leaves your machine.

## File structure

```
easyspeak/
├── src/
│   ├── core/
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   ├── about.py           # Standalone libadwaita "About" window
│   │   ├── cli.py             # CLI entry point: argument parsing + logging
│   │   ├── config.py          # Tuning constants + Whisper model factory
│   │   ├── gnome_extension.py # Installs/refreshes/enables the extension
│   │   ├── i18n.py            # Spoken-reply translations (gettext .po)
│   │   ├── log.py             # Logging setup
│   │   ├── main.py            # EasySpeak class + main loop
│   │   ├── mediakeys.py       # Replays multimedia keys via Mutter
│   │   ├── speech.py          # Persistent piper -> player pipeline
│   │   └── tray.py            # Panel indicator + asleep lifecycle
│   ├── data/                  # Bundled data files (easyspeak.data), shipped as package data
│   │   ├── __init__.py        # Marks the folder as package data
│   │   ├── easyspeak.desktop  # Desktop entry
│   │   └── easyspeak-autostart.desktop
│   ├── gnome@easyspeak.dev/   # GNOME Shell extension (UUID-named, shipped as package data)
│   │   ├── schemas/           # GSettings schema (+ compiled) for the settings
│   │   ├── __init__.py        # Marks the folder as package data (easyspeak.gnome)
│   │   ├── extension-helpers.js  # Pure JS helpers imported by extension.js
│   │   ├── extension.js       # The extension itself
│   │   ├── grid.js            # Numbered grid overlay + pointer injection primitive
│   │   ├── indicator.js       # Panel indicator + Quick Settings toggle widgets
│   │   ├── metadata.json      # Extension metadata
│   │   ├── prefs.js           # Extension Settings dialog (autostart, Quick Settings)
│   │   ├── screenshot.js      # Screen capture primitive (Wayland framebuffer grab)
│   │   └── windows.js         # Window/workspace operations on the focused window
│   └── plugins/               # one package each: __init__.py + locale/<lang>/LC_MESSAGES/<name>.po
│       ├── __init__.py
│       ├── apps/              # Application launcher
│       ├── base/              # Help and exit (routes last)
│       ├── browser/           # Qutebrowser control + auto-config
│       ├── dictation/         # Voice-to-text + AT-SPI enablement
│       ├── files/             # Folder navigation
│       ├── headtrack/         # Head tracking (experimental)
│       ├── media/             # Playback controls
│       ├── mousegrid/         # Grid overlay mouse control
│       ├── sleep/             # Voice deactivate
│       └── system/            # Volume, brightness, DND
├── tests/
│   ├── acceptance/            # Gherkin scenarios (pytest-bdd)
│   ├── benchmarks/            # pytest-benchmark suites for bencher.dev
│   ├── integration/           # tests against real binaries
│   └── unit/                  # tests for src/core/ and src/plugins/
└── pyproject.toml
```

## GNOME Shell extension

On first start, core auto-installs the GNOME Shell extension to the user-local
extensions directory (unless GNOME already sees it via a system-wide install).
Files copied:

```
~/.local/share/gnome-shell/extensions/gnome@easyspeak.dev/
├── schemas/
│   ├── gschemas.compiled
│   └── org.gnome.shell.extensions.easyspeak.gschema.xml
├── extension-helpers.js
├── extension.js
├── grid.js
├── indicator.js
├── metadata.json
├── prefs.js
├── screenshot.js
└── windows.js
```

The extension exposes the compositor-only primitives — panel indicator,
mouse grid, window operations, and screen capture — that the Python plugins
drive. Its
Settings dialog (`prefs.js`) offers "Show EasySpeak in Quick Settings Menu",
persisted in dconf via the bundled GSettings schema: when on, the asleep
state is surfaced as a Quick Settings toggle — on while listening, off
while asleep — instead of the panel tray icon. On Wayland, GNOME Shell
only scans for extensions at login, so a `oneshot` systemd *user* unit
(installed by EasySpeak) re-copies the bundled files before the shell loads
them at each login. See [`core.gnome_extension`][core.gnome_extension]
for the full lifecycle.
