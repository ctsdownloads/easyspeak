# EasySpeak

Voice control for Linux desktops. Fully local, no cloud, Wayland-native.

Say "Hey Jarvis" and control your desktop with your voice.

![License](https://img.shields.io/badge/license-GPL--3.0-blue.svg)
![Platform](https://img.shields.io/badge/platform-Linux-lightgrey.svg)
![Desktop](https://img.shields.io/badge/desktop-GNOME%20%7C%20Wayland-green.svg)
![Status](https://img.shields.io/badge/status-Alpha-orange.svg)

> ⚠️ **Early development.** This project works but is not polished. Expect bugs, incomplete docs, and changes without notice.

## Why EasySpeak?

Linux desktop voice control is a gap. Talon exists but has a steep learning curve and costs money for the full version. Most other tools are X11-only, abandoned, or cloud-dependent.

EasySpeak is:
- **Free and open source** - GPL-3.0 licensed, no paywalls
- **Fully local** - No cloud, no accounts, no data leaving your machine
- **Wayland-native** - Works on modern GNOME desktops where X11 tools fail
- **Simple** - Say "Hey Jarvis, open downloads" and it works
- **Extensible** - Drop a Python file in plugins/ to add commands

Built for people with RSI, accessibility needs, hands-busy workflows, or anyone who wants to talk to their computer.

## Features

Current and in active development:

- **Wake word activation** - Hands-free with "Hey Jarvis"
- **Mouse grid** - Navigate anywhere on screen with voice ("grid", "3 7 5", "click")
- **Head tracking** - Control cursor with head movement (experimental)
- **Browser control** - Qutebrowser integration with link hints, tabs, scrolling
- **Dictation** - Voice-to-text in any text field with punctuation commands
- **App launcher** - Open and close applications by name
- **Media control** - Play, pause, skip via MPRIS
- **System controls** - Volume, brightness, do not disturb
- **Fully local** - OpenWakeWord + Whisper + Piper, no cloud services
- **Wayland-native** - Works properly on modern Linux desktops
- **Plugin architecture** - Easy to extend

## Demo

**Terminal output:**

![Terminal](images/1.png)

**Mouse grid (full screen):**

![Grid full](images/2.png)

**Mouse grid (zoomed):**

![Grid zoomed](images/3.png)

**Browser mode:**

![Browser](images/4.png)

## Requirements

- Linux with GNOME Shell 47+ on Wayland
- Python 3.9+
- Working microphone
- ~2GB disk space for models

Tested on Fedora (via distrobox) and Bluefin.

## Installation

**Terminology:**
- **HOST** = Your main system (run commands in a normal terminal)
- **DISTROBOX** = A container that shares your home folder but has its own packages. Required because Python 3.14 (Fedora 43+) breaks a key dependency.

All commands run on **host** unless marked otherwise.

### 1. System Packages (Fedora) - HOST

```bash
sudo dnf install \
  pipewire-utils \
  wireplumber \
  at-spi2-core \
  python3-gobject \
  qutebrowser \
  glib2
```

Most are pre-installed on Fedora/Bluefin GNOME. The command skips existing packages.

### 2. Piper TTS - HOST

Piper development moved to [OHF-Voice/piper1-gpl](https://github.com/OHF-Voice/piper1-gpl) but the new version is Python-only (no standalone binary). We use the last standalone binary from the original repo - it works fine and voice models are compatible.

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

### 3. Distrobox Setup - HOST then DISTROBOX

**Why distrobox?** Python 3.14 (Fedora 43+) breaks PyAV, a faster-whisper dependency. The fix isn't released yet. Distrobox with Fedora 41 gives Python 3.12 where everything works. Even on older Fedora, distrobox keeps your system clean.

```bash
# HOST: Install distrobox
sudo dnf install distrobox

# HOST: Create container with Fedora 41 (Python 3.12)
distrobox create --name easyspeak --image fedora:41
distrobox enter easyspeak

# DISTROBOX: Install build dependencies and audio
sudo dnf install portaudio-devel python3-devel gcc pulseaudio-utils cairo-devel gobject-introspection-devel

# DISTROBOX: Install Python packages
pip install faster-whisper openwakeword numpy pyaudio PyGObject --break-system-packages

# DISTROBOX: Exit back to host
exit
```

### 4. Clone Repository - HOST

```bash
git clone https://github.com/ctsdownloads/easyspeak.git
cd easyspeak
```

### 5. GNOME Shell Extension - HOST

```bash
mkdir -p ~/.local/share/gnome-shell/extensions/easyspeak-grid@local
cp extension.js metadata.json ~/.local/share/gnome-shell/extensions/easyspeak-grid@local/
gnome-extensions enable easyspeak-grid@local
```

Log out and back in for the extension to load.

### 6. Enable Accessibility - HOST

```bash
gsettings set org.gnome.desktop.interface toolkit-accessibility true
```

## Usage

```bash
distrobox enter easyspeak
cd ~/easyspeak
python core.py
```

Say "Hey Jarvis" followed by a command.

## Commands

### Mouse Grid

Screen splits into a 3x3 layout (like a phone keypad):

```
1 2 3
4 5 6
7 8 9
```

Say **"grid"** to show it. Say a number to zoom into that zone. Keep zooming until you're over your target, then **"click"**.

Chain numbers to go faster: **"3 6 3"** zooms three times at once.

**Drag and drop:**
1. Navigate to the thing you want to drag
2. Say **"mark"** - grabs it (mousedown)
3. Grid resets to full screen
4. Navigate to where you want to drop it
5. Say **"drag"** - releases it (mouseup)

| Command | Action |
|---------|--------|
| grid | Show grid |
| 1-9 | Zoom to zone |
| 3 7 5 | Chain zones |
| click | Left click |
| double click | Double click |
| right click | Right click |
| middle click | Middle click |
| up/down/left/right | Nudge position |
| left 5, down 3, etc. | Nudge with repeat |
| scroll up/down/left/right | Scroll at cursor |
| scroll down 3, etc. | Scroll with repeat |
| mark | Grab (start drag) |
| drag | Drop (end drag) |
| again | Reopen at last spot |
| close | Hide grid |

### Head Tracking (Experimental)

Requires webcam and additional dependencies (`pip install sixdrepnet opencv-python`).

| Command | Action |
|---------|--------|
| start tracking | Begin head tracking |
| stop tracking | End tracking |
| freeze | Lock cursor position |
| go | Resume tracking |
| recalibrate | Reset center position |
| nudge up/down/left/right | Fine tune when frozen |
| click | Left click |
| double click | Double click |
| right click | Right click |

### Browser (Qutebrowser)

| Command | Action |
|---------|--------|
| browser | Enter browser mode |
| numbers / hints | Show link hints |
| zero two | Click hint 02 |
| new tab | Open new tab |
| close tab | Close current tab |
| tab left/right | Switch tabs |
| tab [number] | Jump to specific tab |
| undo tab | Restore closed tab |
| back / forward | Navigate history |
| reload | Refresh page |
| scroll up/down | Scroll page |
| page up/down | Scroll by page |
| top / bottom | Go to top/bottom |
| find [text] | Search in page |
| find next/previous | Navigate matches |
| search [query] | Web search (DuckDuckGo) |
| go to [url] | Navigate to URL |
| open youtube | Open bookmark |
| exit browser | Leave browser mode |

Built-in bookmarks: youtube, google, gmail, github, reddit, twitter, facebook, amazon, netflix, duckduckgo

### Dictation

| Command | Action |
|---------|--------|
| notes | Start dictation mode |
| stop notes | End dictation mode |
| comma | Insert , |
| period | Insert . |
| question mark | Insert ? |
| exclamation mark | Insert ! |
| colon | Insert : |
| semicolon | Insert ; |
| apostrophe | Insert ' |
| quote | Insert " |
| dash | Insert - |
| new line | Insert newline |
| new paragraph | Insert double newline |
| new sentence | Insert . and capitalize next |
| backspace | Delete character |
| space | Insert space |
| tab | Insert tab |
| at sign | Insert @ |
| hashtag | Insert # |
| percent | Insert % |
| asterisk | Insert * |

### Apps

| Command | Action |
|---------|--------|
| open [app] | Launch application |
| close [app] | Close application |

Default apps in `plugins/apps.py` (edit to match your system):
- firefox, steam, spotify, calculator, settings, files, terminal, browser

These are just examples. Edit `apps.py` to add your own apps.

### Files

| Command | Action |
|---------|--------|
| open documents | Open Documents folder |
| open downloads | Open Downloads folder |
| open pictures | Open Pictures folder |
| open music | Open Music folder |
| open videos | Open Videos folder |
| open home | Open home folder |
| open desktop | Open Desktop folder |

### Media

| Command | Action |
|---------|--------|
| play | Resume playback |
| pause | Pause playback |
| next / skip | Next track |
| previous / back | Previous track |

### System

| Command | Action |
|---------|--------|
| volume up/down | Adjust volume |
| mute | Toggle mute |
| brightness up/down | Adjust brightness |
| do not disturb on/off | Toggle notifications |

### General

| Command | Action |
|---------|--------|
| help | List all commands |
| stop / exit / quit | Exit EasySpeak |

## File Structure

```
easyspeak/
├── core.py                 # Main application
├── extension.js            # GNOME Shell extension
├── metadata.json           # Extension metadata
└── plugins/
    ├── __init__.py
    ├── 00_eyetrack.py      # Head tracking (experimental)
    ├── 00_mousegrid.py     # Grid overlay mouse control
    ├── apps.py             # Application launcher
    ├── browser.py          # Qutebrowser control
    ├── dictation.py        # Voice-to-text
    ├── files.py            # Folder navigation
    ├── media.py            # Playback controls
    ├── system.py           # Volume, brightness, DND
    └── zz_base.py          # Help and exit
```

After installation, the extension is copied to:
```
~/.local/share/gnome-shell/extensions/easyspeak-grid@local/
├── extension.js
└── metadata.json
```

## How It Works

- **Wake word**: OpenWakeWord detects "Hey Jarvis" instantly
- **Speech-to-text**: faster-whisper transcribes commands locally
- **Text-to-speech**: Piper provides voice feedback
- **Mouse control**: GNOME Shell extension with Clutter virtual input
- **Browser scroll**: JavaScript injection via qutebrowser IPC
- **Dictation**: AT-SPI accessibility framework

All processing happens locally. No data leaves your machine.

## Writing Plugins

Drop a Python file in `plugins/` and it gets loaded automatically.

```python
NAME = "myplugin"
DESCRIPTION = "What it does"

COMMANDS = [
    "say hello - speaks a greeting",
]

def setup(core):
    """Called once at startup. Store core reference if needed."""
    pass

def handle(cmd, core):
    """Called for every voice command. Return True if handled, None to pass to next plugin."""
    if "say hello" in cmd:
        core.speak("Hello there!")
        return True
    return None
```

**Core methods you can use:**
- `core.speak("text")` - text-to-speech response
- `core.host_run(["cmd", "arg"])` - run shell command on host (works from distrobox)
- `core.transcribe(audio)` - transcribe audio to text
- `core.wait_for_speech()` - wait for user to start speaking
- `core.record_until_silence()` - record until user stops
- `core.in_distrobox()` - returns True if running in distrobox

**Loading order:** Plugins load alphabetically. Use number prefixes to control order (`00_mousegrid.py` loads before `apps.py`).

## Troubleshooting

All troubleshooting commands run on **host**.

**"Failed to show grid - is extension enabled?"**
```bash
gnome-extensions enable easyspeak-grid@local
# Then log out and back in
```

**Dictation not working**
```bash
gsettings set org.gnome.desktop.interface toolkit-accessibility true
# Log out and back in
```

**Wake word not detecting**
- Check microphone: `arecord -d 3 test.wav && aplay test.wav`
- Adjust `WAKE_THRESHOLD` in core.py (lower = more sensitive)

**Commands misheard**
- Adjust `SILENCE_THRESHOLD` in core.py
- Speak clearly after the beep

**Piper permission denied**
```bash
chmod +x ~/.local/bin/piper/piper
chmod +x ~/.local/bin/piper/espeak-ng
```

**pip install fails with PyAV/Cython errors**

You're probably running on host instead of inside distrobox, or using wrong Fedora image:
```bash
# Make sure you're using Fedora 41 image
distrobox create --name easyspeak --image fedora:41
distrobox enter easyspeak
# Then install dependencies inside distrobox
```

## Contributing

Contributions welcome. Please open an issue first to discuss changes.

Areas that need work:
- More application integrations

## Planned Enhancements

- Further GNOME integration for desktop control
- Verbal help per section (say "help browser" for spoken commands)
- Auto-discover installed apps for launcher
- Clipboard commands (copy, paste)

## License

GPL-3.0 License. See [LICENSE](LICENSE) for details.

## Acknowledgments

- [OpenWakeWord](https://github.com/dscripka/openWakeWord) - Wake word detection
- [faster-whisper](https://github.com/guillaumekln/faster-whisper) - Speech recognition
- [Piper](https://github.com/OHF-Voice/piper1-gpl) - Text-to-speech (we use the last standalone binary from the original [rhasspy/piper](https://github.com/rhasspy/piper) repo)
- [Talon](https://talonvoice.com/) - Inspiration for voice control concepts
