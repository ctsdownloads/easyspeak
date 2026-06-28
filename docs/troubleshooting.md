# Troubleshooting

## Mouse grid: "Failed to show grid — is extension enabled?"

You don't install the extension yourself — EasySpeak does it automatically on
startup, copying it to
`~/.local/share/gnome-shell/extensions/easyspeak@local/` and keeping it up
to date (look for an `easyspeak: installed ...` or `easyspeak: updated ...`
message). On Wayland, GNOME Shell only scans for new extensions at login, so you
typically have to **log out and back in** before it becomes loadable.

After re-login, enable it from the command line:

```bash
gnome-extensions enable easyspeak@local
```

…or open the **Extensions** GNOME app and toggle *EasySpeak* on.

To remove it later:

```bash
gnome-extensions disable easyspeak@local
rm -rf ~/.local/share/gnome-shell/extensions/easyspeak@local
```

…or click the trash icon next to *EasySpeak* in the Extensions app.

## Dictation not working

EasySpeak enables the GNOME accessibility bridge on first run; log out and back
in after seeing the `dictation: enabled GNOME toolkit-accessibility` message. If
the auto-config printed a `WARNING` instead (e.g. on a non-GNOME or locked-down
desktop), run it manually:

```bash
gsettings set org.gnome.desktop.interface toolkit-accessibility true
# Log out and back in
```

## Browser plugin: link numbers don't work

EasySpeak appends two required lines to `~/.config/qutebrowser/config.py` on
first run (you'll see a `browser: wrote ...` or `browser: updated ...` message).
If you see a `browser: note: ... is read-only` or a similar error instead, add
these lines to the config module yourself:

```python
config.load_autoconfig(False)
c.hints.chars = '0123456789'
```

## Wake word not detecting

- Check the microphone: `arecord -d 3 test.wav && aplay test.wav`
- Adjust `WAKE_THRESHOLD` (lower = more sensitive) — see [`core.config`][core.config]

## Wake word triggers multiple times

Mic gain too high. Lower the capture level:

```bash
alsamixer
# Press F6 to select your mic device
# Press Tab to switch to Capture
# Lower to ~70
```

## Commands misheard

- Adjust `SILENCE_THRESHOLD` — see [`core.config`][core.config]
- Speak clearly after the beep

## Piper permission denied

```bash
chmod +x ~/.local/bin/piper/piper
chmod +x ~/.local/bin/piper/espeak-ng
```

## pip install fails with PyAV/Cython errors

You're on an unsupported Python version. EasySpeak is tested against Python 3.10,
3.11, 3.12, 3.13, and 3.14 — use one of those. The simplest fix is `uv run
easyspeak`, which picks a compatible interpreter for you.
