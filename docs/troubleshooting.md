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

## Mouse grid: the grid never appears on a non-GNOME desktop

The grid needs either the Shell extension (GNOME 47+) or the mousegrid
plugin's ydotool backend, which needs `ydotool` installed (its own tool list must offer
`mousemove`, `click` and `type`), a compositor with layer-shell support (COSMIC,
wlroots, KDE) and an interpreter with PyGObject, the cairo bindings
(`python3-gi-cairo` — the click-through input region is built from a
`cairo.Region`) and the gtk4-layer-shell typelib. `ydotool` also needs write
access to `/dev/uinput`.

On COSMIC specifically, the compositor must be one that exposes
`zwlr_layer_shell_v1` to ordinary clients: cosmic-comp builds from before the
2025-10-30 security rework gated layer-shell to a privileged client class and
the grid's gate fails closed there, while Pop!_OS's current repos (cosmic-comp
`0.1~1791491785` and later) admit any non-sandboxed client — measured on a
Pop!_OS 24.04 VM where `apt install cosmic-comp` moved the session from
refusing the probe to drawing the grid live.

On Debian/Ubuntu the runtime pieces are:

```bash
sudo apt install ydotool libgtk4-layer-shell0 gir1.2-gtk4layershell-1.0 python3-gi python3-gi-cairo python3-cairo
```

`libgtk4-layer-shell0` with `gir1.2-gtk4layershell-1.0` is the library and its
typelib (they first appear in 25.10 and 26.04; 24.04 has neither). Where the
distro packages them, that is all the overlay needs: the helper resolves the
library **by its soname** (`libgtk4-layer-shell.so.0`), so the `-dev` package
and its unversioned `.so` symlink are not needed and `EASYSPEAK_GRID_TYPELIB` is
unnecessary. Where no package exists, build gtk4-layer-shell and point
`EASYSPEAK_GRID_TYPELIB` at the build tree's `src` directory: EasySpeak
prepends it to `GI_TYPELIB_PATH` and `LD_LIBRARY_PATH` in the helper's
environment, and probes interpreter candidates with those same paths, so both
the check that enables the grid and the grid itself find the build tree.

Granting `/dev/uinput` access is a deployment step, not a session tweak: a
`setfacl` grant does not survive a reboot, a udev rule does. Add

```udev
# /etc/udev/rules.d/60-uinput.rules
KERNEL=="uinput", MODE="0660", GROUP="input"
```

then `sudo udevadm control --reload-rules`, `sudo udevadm trigger`, add yourself
to the group (`sudo usermod -aG input $USER`) and log out and back in. This is
input-injection grade access — the same class as the `input` group hold-to-dictate
needs — so grant it to the account that should be able to click. A daemon
(`ydotoold`) opens `/dev/uinput` once at startup and keeps that fd: permission
changes only bite a daemon (re)started after them — the same restart the grid's
fail-closed probe needs before it reports the injector unusable.

`ydotool` ships in two command dialects, and the backend reads which one is
installed from the client itself:

- **ydotool 0.1.8 and older** (Ubuntu 25.10): a running `ydotoold` is optional.
  With no daemon the client builds a uinput device per invocation and says so
  ("ydotoold backend unavailable (may have latency+delay issues)") — the
  latency caveat its own notice names, which the plugin's log calls the
  per-invocation mode.
- **ydotool 1.0.x** (Ubuntu 26.04): the per-invocation fallback is gone. With no
  daemon the client exits 2 ("failed to connect socket") and emits nothing, so a
  running `ydotoold` is required and the backend's capability probe fails closed
  without one — the log says why, and `mousegrid` keeps the words rather than
  promising a grid that cannot click.

Not every distro ships a `ydotoold` binary with the client (Ubuntu 24.04 and
25.10's `ydotool` package is CLI-only and the daemon is a separate `ydotoold`
package; 26.04 ships the daemon in the same package). If your distro has the
daemon but no user unit,
`systemctl --user enable --now ydotoold` answering "Unit ydotoold.service not
found" means installing this as `~/.config/systemd/user/ydotoold.service`:

```ini
[Unit]
Description=ydotoold - persistent uinput device for ydotool

[Service]
ExecStart=/usr/bin/ydotoold --socket-path=/tmp/.ydotool_socket --socket-perm=0600
Restart=on-failure

[Install]
WantedBy=default.target
```

Then `systemctl --user daemon-reload` once, and `systemctl --user enable --now
ydotoold`. The socket path and its 0600 mode are what 0.1.8's client hardcodes,
which is also why the daemon has to run as your user rather than as root: a root
daemon's socket is unreachable by your client. On 1.0.x the client defaults to
`$XDG_RUNTIME_DIR/.ydotool_socket` and honours `YDOTOOL_SOCKET`; the backend
probes that path, the login session's own `/run/user/<uid>/` path and 0.1.8's
`/tmp/.ydotool_socket`, so a daemon on either default is found.

If `ydotool` or the layer-shell stack is missing, or (on ydotool 1.0.x) no
daemon answers, the daemon logs `grid backend inert` at startup with the reason,
says nothing out loud, and `mousegrid` keeps the words. On 0.1.8 a missing
`ydotoold` alone does not: the log names the per-invocation mode and the grid
still answers.

## Mouse grid: clicks land in the wrong place

Injected motion passes through the desktop's pointer-acceleration curve, so a
click lands where the grid says only when that curve is flat. With the default
profile (adaptive), the cursor travels roughly twice the aimed distance —
measured on Pop!_OS 24.04's COSMIC for both ydotool dialects, with and without
`ydotoold`, at the output's default scale, and confirmed on KDE Plasma 6
(KWin), where adaptive scales a grid click exactly 2x. Set the pointer acceleration
profile to **Flat** in your desktop's settings and the clicks land inside the
aimed cell. Switching the profile does not always apply on current cosmic-comp
builds ([pop-os/cosmic-comp#2289](https://github.com/pop-os/cosmic-comp/issues/2289),
[#2738](https://github.com/pop-os/cosmic-comp/issues/2738)); re-check after a
session restart.

From the CLI — headless machines, or any setup where the settings GUI is out
of reach — write the profile cosmic-comp actually reads, then restart the
session:

```text
~/.config/cosmic/com.system76.CosmicComp/v1/input_default
(
    state: Enabled,
    acceleration: Some((profile: Some(Flat), speed: 0.0)),
)
```

On KDE Plasma 6 the same fix lives in System Settings → Mouse & Touchpad →
Mouse, and it is per device: open the **Device** dropdown, pick
`ydotoold virtual device`, then set the acceleration profile to **Flat**.
There is no working command-line equivalent on Plasma — profile entries
written to `kcminputrc` with `kwriteconfig6` are ignored by KWin.

Two traps, both verified on Pop!_OS 24.04: the struct field is `acceleration` —
naming it after the type (`AccelConfig: (…)`) parses without error and silently
applies nothing, because unknown fields are dropped, not rejected; and even a
correct file only takes effect after a session restart. Cosmic config values
that are options are written as explicit `Some(...)`, matching the other files
in that directory.

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

If you hear **"I can't type on this desktop yet. The text is on the clipboard,
paste it with Control V."**, the paste keystroke couldn't be injected — see the
next section.

## Key injection backend

Every injected keystroke — dictation's paste, the browser's "press enter", the
media keys — goes through one backend, chosen at the first injection and sticky
for the rest of the process: Mutter RemoteDesktop where the session is GNOME
and Mutter owns its RemoteDesktop name — or where the ownership probe itself
fails — the ydotool/uinput stack (the same one the mouse grid uses) everywhere
else. `EASYSPEAK_KEY_BACKEND` forces the choice: `remote-desktop`, `uinput`,
or `auto` (the default, which probes as above; an unknown value warns and
falls back to it). The choice is read once, so a change takes effect when the
EasySpeak daemon restarts, not mid-session.

Dictation and the browser speak a refusal when their keystrokes can't be
injected, and the log names the remedy:

- **`ydotool` missing** — the prebuilt packages ship it as a dependency; on a
  source install, install it yourself (`sudo dnf install ydotool`).
- **No write access to `/dev/uinput`** — a udev rule or membership in the
  `input` group, exactly the grant [the mouse grid's ydotool backend](#mouse-grid-the-grid-never-appears-on-a-non-gnome-desktop)
  needs. Permission changes reach only processes started after them, and the
  backend is picked at the first injection, so log out and back in first.
- **No running `ydotoold` on ydotool 1.0.x** — the daemon the grid needs; the
  grid section above has the package names and the user-unit recipe.
- **A 0.1.x ydotool client and the media keys** — those clients (e.g.
  Pop!_OS 24.04's `0.1.8-3build1`) take key NAMES, and their table cannot
  spell a media key, so the volume/brightness replay is refused loudly and the
  setting still changes through its direct fallback — without the desktop's
  own on-screen display. Only a 1.0.x client (raw keycodes) renders it.

If the backend resolved wrong for the session at hand — say the daemon started
under one desktop and now runs under GNOME — restart the daemon to let the
gate probe again; set `EASYSPEAK_KEY_BACKEND=remote-desktop` first to pin a
GNOME session to its native backend, then restart.

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

## pip install fails with PyAV/Cython errors

You're on an unsupported Python version. EasySpeak is tested against Python 3.10,
3.11, 3.12, 3.13, and 3.14 — use one of those. The simplest fix is `uv run
easyspeak`, which picks a compatible interpreter for you.
