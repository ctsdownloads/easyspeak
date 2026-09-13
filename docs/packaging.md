# Packaging

EasySpeak ships **distro `.deb` and `.rpm` packages**, split into three:

- **`easyspeak`** (amd64) — the application: a self-contained Python runtime
  (standalone CPython + all wheels, including the `piper` engine and the
  `hey_jarvis` wake word) under `/opt/easyspeak`. No `pip`/`uv` step and no compiler
  at install time. Desktop integration (launcher, GNOME Shell extension, AT-SPI
  dictation helper) is wired to your system's GTK4 / PyGObject / AT-SPI packages,
  declared as dependencies.
- **`easyspeak-stt-parakeet`** (noarch) — the speech recognition model: NVIDIA's
  multilingual Parakeet TDT v3, one int8 ONNX model for the 25 European languages
  it covers, under `/opt/easyspeak/models/parakeet`. EasySpeak uses it by default.
- **`easyspeak-lang-en`** (noarch) — English speech data: the Piper
  `en_US-amy-medium` voice and the Whisper `base.en` recognition model, which
  stands in when the Parakeet pack is not installed, under
  `/opt/easyspeak/models/en`. More languages ship as `easyspeak-lang-*` packages,
  each under its own `/opt/easyspeak/models/<language>`.

Splitting keeps the app small and lets you pick (or add) languages independently
without re-downloading the runtime or the shared recognition model. See
[Language](#language).

> EasySpeak integrates deeply with the host (raw input devices, the AT-SPI bus,
> session D-Bus, a GNOME Shell extension, and spawning host binaries). That is why
> the supported formats are **unconfined distro packages** — sandboxed formats
> (Flatpak/Snap) fight every one of those integration points.

## Install

Download the latest packages from the [Releases page][gh:releases] — the app,
the [Parakeet pack][gh:releases:stt] and a [language pack][gh:releases:lang] —
and install them **together**. Just take the latest of each: a pack is a
separate file (not auto-fetched from GitHub) and is versioned by its models, so
the app and pack version numbers are independent and need not match:

=== "Debian / Ubuntu"

    ```bash
    sudo apt install ./easyspeak_*_amd64.deb ./easyspeak-stt-parakeet_*_all.deb ./easyspeak-lang-en_*_all.deb
    ```

=== "Fedora / RHEL"

    ```bash
    sudo dnf install ./easyspeak-*.x86_64.rpm ./easyspeak-stt-parakeet-*.noarch.rpm ./easyspeak-lang-en-*.noarch.rpm
    ```

This is **fully offline** (assuming the system dependencies — GTK4, PortAudio,
PyGObject, … — are already present, as on any GNOME desktop). Then launch
**EasySpeak** from the applications menu, or run `easyspeak`.

Dictation additionally needs `wl-clipboard`, since it places text by pasting
rather than through the accessibility bridge, which Chromium-based applications
ignore. It is a hard dependency, so it comes with the package.

Installing the app **without** the packs also works: the wake word is built in,
the speech model then downloads on first run if you allow it (see
`EASYSPEAK_OFFLINE` in the [configuration](usage.md#configuration)), and voice
feedback stays off until you add a Piper voice. Without the Parakeet pack and
with downloads off, a language pack's Whisper model does the recognition, more
slowly.

One non-package step remains: **log out and back in once** after the first launch so
GNOME loads the bundled Shell extension (mouse grid + panel indicator).

To use hold-to-dictate, add yourself to the `input` group (raw `/dev/input`
access) and log back in:

```bash
sudo usermod -aG input "$USER"
```

## Speech recognition

`easyspeak-stt-parakeet` carries NVIDIA's Parakeet TDT v3 model, converted to an
int8 ONNX model, which recognizes speech in 25 European languages and tells them
apart by itself. It is one pack for every language, under
`/opt/easyspeak/models/parakeet`, and the recognizer EasySpeak uses by default. The
model is [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); the package
ships the attribution as `/usr/share/doc/easyspeak-stt-parakeet/copyright`.

## Language

The default `easyspeak-lang-en` pack is **US English** — Piper `en_US-amy-medium`
(feedback) and Whisper `base.en` (recognition without the Parakeet pack). The
`hey_jarvis` wake word is built into the app (it ships inside the pyopen-wakeword
wheel), so it stays English regardless of language pack.

`easyspeak-lang-de` is **German** — the multilingual Whisper `small` and Piper
`de_DE-thorsten-medium`: German dictation and German replies in the German voice.
`easyspeak-lang-it` is **Italian** the same way, with Piper `it_IT-paola-medium`,
`easyspeak-lang-fr` **French**, with Piper `fr_FR-siwis-medium`, and
`easyspeak-lang-es` **Spanish**, with Piper `es_ES-davefx-medium`. Most commands
take that language's words too; the English ones work everywhere.

`EASYSPEAK_LANGUAGE` (default `en`) is the language you dictate in, and it picks
the pack installed under `/opt/easyspeak/models/<language>`. To use a language we
ship no package for, install/drop its models and point these environment variables
at them (an explicit value always wins; set them in a systemd user override or your
shell profile):

- `EASYSPEAK_WHISPER_MODEL` — a multilingual faster-whisper model name (e.g. `base`,
  `small`) or a local model directory. The English-only `*.en` models can't
  transcribe other languages.
- `EASYSPEAK_PIPER_MODEL` — path to a Piper voice `.onnx` (with its `.onnx.json`
  next to it).

So adding a language needs no root and no package from us: download any
faster-whisper model and Piper voice, then set the two variables. A different wake
word, however, needs a custom-trained model that pyopen-wakeword can load.

## Build the packages yourself

The packages are built in a clean Ubuntu container, so the result is identical
whether produced locally or in CI — handy on NixOS, where the bundle's standalone
CPython and manylinux wheels can't run on the host:

```bash
just package-app              # -> ./dist/ : the easyspeak app .deb and .rpm
just package-app 1.2.3        # set an explicit app version
just package-lang             # -> ./dist/ : every easyspeak-lang-* .deb and .rpm
just package-lang en          # ... or just the named pack(s)
just package-stt              # -> ./dist/ : the easyspeak-stt-parakeet .deb and .rpm
just package-distro           # all of the above (every distro package)
```

The app and the packs build independently. The app build needs a compiler and
the standalone CPython bundle; a pack is only downloaded speech models, so it
builds in a lighter container with no compiler and carries its own version from
`pins.toml`, independent of the app release. They release on their own cadence
too, but all go through the same `release.yml` workflow on a published GitHub
Release: an application tag builds and attaches the app packages, while a
`lang-<code>-<version>` or `stt-<code>-<version>` tag skips those jobs and
instead builds that pack and attaches it to that release.

## Other distributions

These formats are maintained **outside this repository**. The notes below capture
what each one needs.

### Nix / NixOS

The repository's `flake.nix` is a **development environment only** — a `uv run`
wrapper. It is **not** a deployable package; treat it purely as a reference. A
real Nix package belongs upstream (e.g. nixpkgs) and must, in particular,
**prepare the GTK4/libadwaita "About" dialog separately**: on NixOS its PyGObject
and the GTK4/libadwaita typelibs can't ride inside the app venv and must be wired
in explicitly (the same pattern the flake already uses for the AT-SPI dictation
helper via `atspiPython` / `giTypelibPath`).

### Arch (AUR)

A `PKGBUILD` can reproduce the bundled-venv layout under `/opt/easyspeak`, or
build against Arch's own Python. Declare the same runtime dependencies as the
`.deb`/`.rpm` (PortAudio, GTK4, libadwaita, PyGObject, AT-SPI, and the optional
`piper`/`qutebrowser`/PipeWire/PulseAudio tooling).

### Fedora COPR

A source build from an RPM `.spec` — effectively the `.rpm` recipe, built on
Fedora's infrastructure for multiple Fedora/EPEL targets.

### openSUSE Build Service (OBS)

OBS can build **both** `.deb` and `.rpm` for many distributions from a single
recipe; a good option if broad distro coverage is wanted later.

### Flatpak / Snap

Not provided. EasySpeak needs raw `/dev/input`, the AT-SPI accessibility bus,
broad session D-Bus access (Mutter RemoteDesktop, GNOME Shell, MPRIS), the ability
to install a GNOME Shell extension into your home directory, and to spawn host
binaries (`piper`, `qutebrowser`, `gnome-extensions`, `gsettings`, …). Granting all
of that to a sandbox removes the confinement that is the whole point of those
formats.

[gh:releases]: https://github.com/ctsdownloads/easyspeak/releases
[gh:releases:lang]: https://github.com/ctsdownloads/easyspeak/releases?q=lang
[gh:releases:stt]: https://github.com/ctsdownloads/easyspeak/releases?q=stt
