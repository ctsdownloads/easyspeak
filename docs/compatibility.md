# Compatibility

EasySpeak runs on Wayland desktops. GNOME is where it started, and where a bundled
Shell extension provides everything. On other desktops, key injection runs through
`ydotool` and a StatusNotifier icon takes the tray's place; a few extension
features still have no counterpart there.

| Feature | GNOME | KDE Plasma | COSMIC |
|---------|:-----:|:----------:|:------:|
| Wake word, voice commands, spoken replies | ✅ | ✅ | ✅ |
| Sleep and wake from the tray icon | ✅ | ✅ | ✅ |
| Quick Settings toggle | ✅ | — | — |
| Open and close apps | ✅ | ✅[^apps] | ✅ |
| Folders and file manager | ✅ | ✅ | ✅ |
| Media playback | ✅ | ✅ | ✅ |
| Volume | ✅ | ✅[^volume] | ✅[^volume] |
| Brightness | ✅ | ❌ | ❌ |
| Do not disturb | ✅ | ❌ | ❌ |
| Browser control | ✅ | ✅[^browser] | ✅[^browser] |
| Dictation | ✅ | ✅[^dictation] | ✅[^dictation] |
| Push-to-talk key | ✅ | ✅ | ✅ |
| Mouse grid | ✅ | ✅[^grid] | ✅[^grid] |
| Head tracking | ✅ | ❌ | ❌ |
| About dialog | ✅ | ⚠️[^about] | ⚠️[^about] |
| EasySpeak settings (e.g. start at login) | ✅ | ⚠️[^settings] | ⚠️[^settings] |

✅ works · ⚠️ partly · ❌ not yet · — not applicable

[^apps]: Opens the KDE counterpart where there is one, e.g. KCalc for "calculator"
    or System Settings for "settings".
[^volume]: The level change is real either way. On a desktop that handles media
    keys globally (GNOME, KDE, COSMIC), a 1.0.x ydotool client replays a real
    media key, which the desktop renders like one of your own key presses — its
    on-screen indicator acknowledges the change; on a 0.1.x client (e.g.
    Pop!_OS 24.04's) the media key cannot be spelled, so the level changes
    directly through the fallback command. On any other desktop (sway,
    Hyprland, ...) the fallback IS the replay: the compositor may have no
    global media-key handling, and a "successfully" injected key it drops
    would change nothing at all.
[^browser]: "Press enter" and the other keystrokes go through the injection
    backend (Mutter RemoteDesktop on GNOME, `ydotool` elsewhere) and land like
    real key presses.
[^dictation]: The text is pasted automatically through the injection backend;
    `wl-clipboard` remains needed for the clipboard half.
[^about]: Opens in Plasma's own look on KDE if the optional `kdialog` is
    installed, else as GNOME's dialog if GTK 4 and libadwaita are. Without
    either, EasySpeak says its version and shows the details in a notification.
[^settings]: "Start at Login" is in the tray icon's menu; there are no other
    settings yet. KDE's System Settings → Autostart shows the same entry.
[^grid]: GNOME's grid is the bundled Shell extension. Elsewhere (KDE Plasma,
    COSMIC, wlroots) the mousegrid plugin uses its ydotool backend when that
    stack is installed: a compositor with layer-shell support, `ydotool` with write
    access to `/dev/uinput`, and an interpreter with PyGObject and the
    gtk4-layer-shell typelib. That access is input-injection grade — the same
    class as the `input` group hold-to-dictate needs — and on ydotool 1.0.x
    (Ubuntu 26.04) it also needs a running `ydotoold`: that client refuses to emit
    without a socket. 0.1.8 (Ubuntu 25.10; Pop!_OS 24.04 ships `0.1.8-3build1`
    too) works without one and only warns about latency. Click precision follows
    the desktop's pointer-acceleration
    profile: on COSMIC and KDE Plasma 6 alike, the default (adaptive)
    profile lands clicks roughly twice the aimed distance; the Flat profile
    lands them exactly.

KDE Plasma and COSMIC support are new: this table reflects a first test on
Plasma 6 and on Pop!_OS 24.04's COSMIC 1.x. If you find something that works
differently, please [report it][issues].

[issues]: https://github.com/ctsdownloads/easyspeak/issues
