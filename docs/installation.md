# Installation

## Requirements

- Linux with GNOME Shell 47+ on Wayland
- Working microphone
- ~2 GB disk space for models
- Python 3.10–3.14 — **source install only**; the prebuilt packages bundle their
  own runtime

Tested on Fedora and NixOS.

## Quick install (prebuilt packages)

The easiest path. Download the latest **app** package and a
**[language pack](https://github.com/ctsdownloads/easyspeak/releases?q=lang)**
from the [Releases page](https://github.com/ctsdownloads/easyspeak/releases)
and install them together:

=== "Debian / Ubuntu"

    ```bash
    sudo apt install ./easyspeak_*_amd64.deb ./easyspeak-lang-en_*_all.deb
    ```

=== "Fedora / RHEL"

    ```bash
    sudo dnf install ./easyspeak-*.x86_64.rpm ./easyspeak-lang-en-*.noarch.rpm
    ```

This bundles the Python runtime, Piper, the GNOME Shell extension, and the speech
models — no `pip`/`uv` step and no compiler. **Log out and back in once** after
the first launch so GNOME loads the bundled extension. See the
[Packaging guide](packaging.md#install) for offline notes, more languages, and
hold-to-dictate setup.

## Install from source

For development, or to run the latest unreleased code, install from the repository.
This path needs system build dependencies and a supported Python.

### Python

EasySpeak is tested against Python 3.10, 3.11, 3.12, 3.13, and 3.14. Fedora 43's
default `python3` (3.14) works out of the box.

### 1. System packages

```bash
sudo dnf install \
  pipewire-utils \
  wireplumber \
  at-spi2-core \
  python3-gobject \
  libadwaita \
  qutebrowser \
  glib2 \
  ffmpeg-free \
  pulseaudio-utils \
  sound-theme-freedesktop \
  portaudio-devel \
  python3-devel \
  gcc
```

`python3-gobject` and `libadwaita` power the tray menu's **About EasySpeak**
window. They ship with any GNOME desktop, so they're usually already present;
they're listed here for the sake of minimal or non-GNOME installs.

### 2. Python packages

The simplest path is [uv](https://docs.astral.sh/uv/), which transparently
creates and updates a virtual environment and runs EasySpeak from in there:

```bash
uv run easyspeak
```

Prefer plain `pip`? Create a virtual environment first — most distributions ship
their system Python as [externally managed](https://peps.python.org/pep-0668/),
so installing into it directly fails:

```bash
python3 -m venv ~/easyspeak-venv
source ~/easyspeak-venv/bin/activate
pip install faster-whisper pyopen-wakeword numpy pyaudio
cd ~/easyspeak
pip install -e .
```

A Python-only installation has no bundled speech-recognition model, and EasySpeak
stays offline by default ([`EASYSPEAK_OFFLINE=strict`](usage.md#configuration)),
so on first run it reports the model as missing. Set `EASYSPEAK_OFFLINE=relaxed`
to have it fetch `base.en` (about 140 MB) from Hugging Face for you, or install a
language pack.

### 3. Piper TTS

```bash
mkdir -p ~/.local/bin
cd ~/.local/bin
wget https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_x86_64.tar.gz
tar xzf piper_linux_x86_64.tar.gz
rm piper_linux_x86_64.tar.gz

echo 'export PATH="$HOME/.local/bin/piper:$PATH"' >> ~/.bashrc
source ~/.bashrc

mkdir -p ~/.local/share/piper
cd ~/.local/share/piper
wget -O en_US-amy-medium.onnx \
  "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/amy/medium/en_US-amy-medium.onnx"
wget -O en_US-amy-medium.onnx.json \
  "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/amy/medium/en_US-amy-medium.onnx.json"
```

### 4. Clone the repository

```bash
git clone https://github.com/ctsdownloads/easyspeak.git ~/easyspeak
cd ~/easyspeak
```

### Head tracking (optional)

Head tracking requires a webcam and additional dependencies:

```bash
pip install '.[head-tracking]'
# or, with uv
uv run --extra head-tracking easyspeak
```

The `head-tracking` extra pulls in `sixdrepnet` and `opencv-python`.
