# Packaging

EasySpeak ships **distro `.deb` and `.rpm` packages**, split into two:

- **`easyspeak`** (amd64) — the application: a self-contained Python runtime
  (standalone CPython + all wheels, including the `piper` engine and the
  `hey_jarvis` wake word) under `/opt/easyspeak`. No `pip`/`uv` step and no compiler
  at install time. Desktop integration (launcher, GNOME Shell extension, AT-SPI
  dictation helper) is wired to your system's GTK4 / PyGObject / AT-SPI packages,
  declared as dependencies.
- **`easyspeak-lang-en`** (noarch) — English speech data: the Whisper `base.en`
  recognition model and the Piper `en_US-amy-medium` voice, under
  `/opt/easyspeak/models`. More languages ship as `easyspeak-lang-*` packages.

Splitting keeps the app small and lets you pick (or add) languages independently
without re-downloading the runtime. See [Language](#language).

> EasySpeak integrates deeply with the host (raw input devices, the AT-SPI bus,
> session D-Bus, a GNOME Shell extension, and spawning host binaries). That is why
> the supported formats are **unconfined distro packages** — sandboxed formats
> (Flatpak/Snap) fight every one of those integration points.

## Install

Download the latest packages from the
[Releases page](https://github.com/ctsdownloads/easyspeak/releases) — grab **both**
the app and a language pack — and install them **together** (the language pack is a
separate file, not auto-fetched from GitHub):

=== "Debian / Ubuntu"

    ```bash
    sudo apt install ./easyspeak_*_amd64.deb ./easyspeak-lang-en_*_all.deb
    ```

=== "Fedora / RHEL"

    ```bash
    sudo dnf install ./easyspeak-*.x86_64.rpm ./easyspeak-lang-en-*.noarch.rpm
    ```

This is **fully offline** (assuming the system dependencies — GTK4, PortAudio,
PyGObject, … — are already present, as on any GNOME desktop). Then launch
**EasySpeak** from the applications menu, or run `easyspeak`.

Installing the app **without** a language pack also works: the wake word is built
in, the Whisper model then downloads automatically on first run, and voice feedback
stays off until you add a Piper voice.

One non-package step remains: **log out and back in once** after the first launch so
GNOME loads the bundled Shell extension (mouse grid + panel indicator).

To use hold-to-dictate, add yourself to the `input` group (raw `/dev/input`
access) and log back in:

```bash
sudo usermod -aG input "$USER"
```

## Language

The default `easyspeak-lang-en` pack is **US English** — Whisper `base.en`
(recognition) and Piper `en_US-amy-medium` (feedback). The `hey_jarvis` wake word is
built into the app (it ships inside the pyopen-wakeword wheel), so it stays English
regardless of language pack.

When present, the English pack is wired up automatically. To use another language —
**whether or not we provide a package for it** — install/drop its models and point
these environment variables at them (an explicit value always wins; set them in a
systemd user override or your shell profile):

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
just package-distro            # -> ./dist/ : app + language .deb and .rpm
just package-distro 1.2.3      # set an explicit version
```

This produces the `easyspeak` app packages and every `easyspeak-lang-*` data
package. CI builds them automatically: `.github/workflows/release.yml` runs the same
script on every published GitHub Release and attaches all archives to it.

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
