# Installation

## Requirements

- Linux with GNOME Shell 47+ on Wayland
- Working microphone
- ~2 GB disk space for models
- Python 3.12 — **source install only** (not 3.13/3.14, see notes below); the
  prebuilt packages bundle their own runtime

Tested on Fedora and NixOS.

## Quick install (prebuilt packages)

The easiest path. Download the latest **app** package and a **language pack**
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
This path needs system build dependencies and Python 3.12.

### Python 3.12

Fedora 43's default `python3` is 3.14. Unfortunately, we depend on a few Google
packages that are not available for Python 3.13+ yet.

```bash
sudo dnf install python3.12
python3.12 --version  # Verify it's installed
```

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
  python3.12-devel \
  gcc
```

`python3-gobject` and `libadwaita` power the tray menu's **About EasySpeak**
window. They ship with any GNOME desktop, so they're usually already present;
they're listed here for the sake of minimal or non-GNOME installs.

### 2. Python packages

```bash
python3.12 -m venv ~/easyspeak-venv
source ~/easyspeak-venv/bin/activate
pip install faster-whisper openwakeword numpy pyaudio
cd ~/easyspeak
pip install -e .
```

If you use `uv` you can ignore the steps that create a virtual environment and
simply run:

```bash
uv run easyspeak
```

uv will transparently create and update a virtual environment, and run EasySpeak
from in there.

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
