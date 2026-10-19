# Troubleshooting

## Mouse grid: "Failed to show grid — is extension enabled?"

You don't install the extension yourself — EasySpeak does it automatically on
startup, copying it to
`~/.local/share/gnome-shell/extensions/gnome@easyspeak.dev/` and keeping it up
to date (look for an `easyspeak: installed ...` or `easyspeak: updated ...`
message). On Wayland, GNOME Shell only scans for new extensions at login, so you
typically have to **log out and back in** before it becomes loadable.

After re-login, enable it from the command line:

```bash
gnome-extensions enable gnome@easyspeak.dev
```

…or open the **Extensions** GNOME app and toggle *EasySpeak* on.

To remove it later:

```bash
gnome-extensions disable gnome@easyspeak.dev
rm -rf ~/.local/share/gnome-shell/extensions/gnome@easyspeak.dev
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

## Dictation types nothing

Dictation places text by putting it on the clipboard and sending a paste
keystroke. Install `wl-clipboard`:

```bash
sudo dnf install wl-clipboard
```

Without it, insertion falls back to the accessibility bridge, which
Chromium-based applications (qutebrowser, Electron apps) accept and silently
discard — the log says so:

```
wl-clipboard is not installed, so dictation is falling back to AT-SPI, ...
```

If you hear **"No text field focused"**, click into a text field first, or use
the browser's `numbers` command and pick the hint on the field you want.

## Browser plugin: link numbers don't work

EasySpeak appends the lines below to `~/.config/qutebrowser/config.py` on first
run (you'll see a `browser: wrote ...` or `browser: updated ...` message). If you
see a `browser: note: ... is read-only` or a similar error instead, add them to
the config module yourself:

```python
config.load_autoconfig(False)
c.hints.chars = "0123456789"
c.content.tls.certificate_errors = "ask-block-thirdparty"
c.content.notifications.enabled = False
c.content.geolocation = False
c.content.autoplay = False
c.content.blocking.method = "hosts"
```

The last four answer prompts and block distractions that voice cannot dismiss: a
modal "allow notifications?" or expired-certificate dialog stops hands-free
browsing dead, and ad overlays are numbered like any other element, so they take
hints away from the page underneath.

Set `c.content.blocking.method = 'both'` for Brave's element-level blocking,
which is what removes overlays rather than just ad domains. It needs
`python3-adblock` installed — EasySpeak checks for it and writes whichever value
works, so installing the package is enough. **Restart qutebrowser** after any
config change.

## Browser: hints or scrolling stop working after going back

Fixed automatically, but worth knowing why the page reloads. qutebrowser runs
JavaScript in the page to find hintable elements and to scroll the container
under the cursor. Going back restores the page from cache without a load, so that
JavaScript is never re-established — hinting fails with "Unknown error while
getting elements" and scrolling silently does nothing.

EasySpeak reloads the page before the next hint or scroll after a history
navigation, which costs your scroll position. You'll hear "Reloading" and see:

```
↻ Reloading: page scripts don't survive a history navigation
```

## Browser renders badly

On some graphics drivers qutebrowser renders video sites wrong: text smears over
itself, icons stutter, the player flickers or disappears. YouTube is the usual
place to notice it.

Say **"fix rendering"** in browser mode. That writes the line below to your
qutebrowser config and restarts the browser:

```python
c.qt.args = ["disable-gpu-compositing"]
```

Say **"restore rendering"** to put it back, or delete the line by hand.

This turns off GPU compositing for qutebrowser only, so video decoding is a
little more expensive. Leave it off unless you see the problem.

## A site breaks with ad blocking on

EasySpeak turns on element-level ad blocking when `python3-adblock` is installed,
because ad overlays are numbered like anything else and steal hint numbers from
the page underneath. Some sites detect it and break on purpose.

Say **"allow ads"** in browser mode to turn blocking off and restart the browser,
and **"block ads"** to turn it back on.

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

- Speak clearly after the beep
- Check the noise floor printed at startup: `Room noise floor 412; silence
  threshold 1030`. The threshold is measured from the room each time, so stay
  quiet for the first second after launch. Override it with
  `EASYSPEAK_SILENCE_THRESHOLD` — see [Configuration](usage.md#configuration)

## Everything takes several seconds

Run with `-v` and compare the two numbers on this line:

```
transcribed 4.2s of audio in 0.45s
```

The second number is the transcription. If it's small and the first is large,
recording isn't stopping when you do: silence isn't being detected, so every
utterance runs to its time cap. Check the noise floor above — if the room is
loud enough that speech and silence look alike, move the microphone closer or set
`EASYSPEAK_SILENCE_THRESHOLD` by hand.

## Piper permission denied

```bash
chmod +x ~/.local/bin/piper/piper
chmod +x ~/.local/bin/piper/espeak-ng
```

## Kokoro doesn't speak — Piper answers instead

EasySpeak never goes quiet: when the Kokoro engine can't start or keeps dying,
it fences itself off, answers with Piper, and says why in the log. Run with
`-v` and check for the engine warnings:

- ``Kokoro is not installed; run `easyspeak --provision-kokoro`, using Piper``
  — the wheels or model files are missing. Mind the version limit on the
  prebuilt packages: they bundle Python 3.14, kokoro-onnx publishes no wheels
  for 3.14 yet, so provisioning refuses there until it does, and Piper stays
  the voice.
- `Kokoro unavailable (...) after 3 strike(s); using Piper until restart` — the
  engine kept crashing, most often a GPU driver problem. Restart EasySpeak to
  try again; `--provision-kokoro` re-checks the install.
- `Kokoro does not cover 'de', using Piper` — German has no Kokoro voice and
  always stays with Piper.

## Kokoro doesn't use the GPU

Provisioning picks the CUDA wheels only when `nvidia-smi` is present, and ends
by reporting which provider actually engaged — a mismatch prints a loud warning
there. If the engine still comes up on the CPU:

- An explicit `ONNX_PROVIDER` is honored verbatim:
  `ONNX_PROVIDER=CPUExecutionProvider` pins the CPU on purpose. Unset it.
- On an AMD (or otherwise non-NVIDIA) machine there is no GPU engine to find —
  the CPU one is what provisioning installs, and it keeps up with short
  replies.
- The worker loads NVIDIA's pip-wheel libraries itself, so no `LD_LIBRARY_PATH`
  is needed anywhere; if CUDA still won't engage with the GPU wheels installed,
  the usual cause is a driver too old for the bundled CUDA runtime — `nvidia-smi`
  working while CUDA initialization fails is the tell.

## Kokoro's GPU is gone after an update

The prebuilt packages own `onnxruntime`, so updating the app replaces the
provisioned GPU flavor with the bundled CPU one. EasySpeak warns at startup
("Kokoro was provisioned for the gpu flavor of onnxruntime, but the cpu flavor
is installed") and keeps answering on the CPU meanwhile. Nothing is broken; run
`easyspeak --provision-kokoro` once more to restore the GPU engine.

## Provisioned Kokoro models not found

The model lands in the models directory. If you provisioned with
`EASYSPEAK_MODELS_DIR` pointed at a custom location, the daemon must run with
the same variable, or it probes the default location and reports the files as
missing despite a successful provision. Set it the same way for both — in a
systemd user override or your shell profile, as
[Packaging](packaging.md#language) describes for the other model variables.

## pip install fails with PyAV/Cython errors

You're on an unsupported Python version. EasySpeak is tested against Python 3.10,
3.11, 3.12, 3.13, and 3.14 — use one of those. The simplest fix is `uv run
easyspeak`, which picks a compatible interpreter for you.
