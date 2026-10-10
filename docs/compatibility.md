# Compatibility

EasySpeak runs on Wayland desktops. GNOME is where it started, and where a bundled
Shell extension provides everything. On other desktops, some features need a
replacement for that extension that doesn't exist yet.

| Feature | GNOME | KDE Plasma |
|---------|:-----:|:----------:|
| Wake word, voice commands, spoken replies | ✅ | ✅ |
| Sleep and wake from the tray icon | ✅ | ✅ |
| Quick Settings toggle | ✅ | — |
| Open and close apps | ✅ | ✅[^apps] |
| Folders and file manager | ✅ | ✅ |
| Media playback | ✅ | ✅ |
| Volume | ✅ | ⚠️[^volume] |
| Brightness | ✅ | ❌ |
| Do not disturb | ✅ | ❌ |
| Browser control | ✅ | ⚠️[^browser] |
| Dictation | ✅ | ⚠️[^dictation] |
| Push-to-talk key | ✅ | ✅ |
| Mouse grid | ✅ | ❌ |
| Head tracking | ✅ | ❌ |
| About dialog | ✅ | ⚠️[^about] |
| EasySpeak settings (e.g. start at login) | ✅ | ⚠️[^settings] |

✅ works · ⚠️ partly · ❌ not yet · — not applicable

[^apps]: Opens the KDE counterpart where there is one, e.g. KCalc for "calculator"
    or System Settings for "settings".
[^volume]: Changes the volume, but without the on-screen indicator.
[^browser]: Pressing keys in browser mode ("press enter") needs GNOME.
[^dictation]: The text can't be typed yet. It lands on the clipboard, ready to
    paste with Ctrl+V.
[^about]: Opens in Plasma's own look if the optional `kdialog` is installed,
    else as GNOME's dialog if GTK 4 and libadwaita are. Without either, EasySpeak
    says its version and shows the details in a notification.
[^settings]: "Start at Login" is in the tray icon's menu; there are no other
    settings yet. System Settings → Autostart shows the same entry.

KDE Plasma support is new, so this table reflects a first test on Plasma 6. If you
find something that works differently, please [report it][issues].

[issues]: https://github.com/ctsdownloads/easyspeak/issues
