# Screenshots

A quick tour of EasySpeak in action. Each image shows a different part of the
voice-control workflow, from launching the daemon to driving the mouse and
browser entirely by voice.

## Starting the daemon

![EasySpeak starting in a terminal: OpenWakeWord and Whisper load, each plugin reports "Loaded", and the daemon begins listening for the wake word](media/daemon-startup.png){ width="100%" }

An earlier version of EasySpeak running from a terminal. On start it loads the
wake-word model (OpenWakeWord) and the speech recognizer (Whisper), then brings
up each plugin in turn — head tracking, mouse grid, apps, browser, dictation,
files, media, and system. The banner confirms the wake word ("Hey Jarvis") and
the daemon settles into **Listening for wake word…**.

The `ALSA lib … unable to open slave` lines are harmless audio-device probing
noise (suppressed in newer versions).

## Tray menu and Quick Settings

EasySpeak lives in the GNOME top bar, ready whenever you want to mute it, wake
it, or reach its settings. It shows up either as a panel tray icon or as a
[Quick Settings](https://help.gnome.org/gnome-help/quick-settings.html) toggle —
a single switch in its extension settings decides which.

<div markdown style="display: flex; flex-wrap: wrap; gap: 1rem; align-items: flex-start; justify-content: center;">

![The EasySpeak tray menu open in the GNOME top bar, the panel icon showing a muted microphone; the menu lists "Reactivate EasySpeak" (hovered), "Settings…", "Help", "About EasySpeak", and "Quit EasySpeak"](media/tray-menu.png){ width="124" }

![The GNOME Quick Settings menu with an active-microphone EasySpeak toggle expanded into its sub-menu: an "EasySpeak" heading, a "Help" entry, and "EasySpeak Settings" (hovered)](media/quick-settings.png){ width="206" }

![EasySpeak's extension settings — a "Configure EasySpeak" panel with two toggles, "Start EasySpeak on login" and "Show EasySpeak in Quick Settings Menu", both on, above an "About EasySpeak" row](media/extension-settings.png){ width="344" }

</div>

Say, "stop listening", to make EasySpeak stop responding to your voice. The
panel icon (left) switches to a muted microphone to show it's asleep, and
EasySpeak ignores everything until you wake it again. Click the icon and choose
**Reactivate EasySpeak** to start listening once more; the same menu opens
**Settings…**, **Help**, and the **About EasySpeak** dialog, or shuts the daemon
down with **Quit EasySpeak**.

Prefer to keep the top bar tidy? Turn on **Show EasySpeak in Quick Settings
Menu** in the extension settings (right) and EasySpeak moves into GNOME's Quick
Settings as a toggle (center) instead of the panel icon. Expanding the toggle
reveals the same **Help** and **EasySpeak Settings** actions, so either entry
point reaches the very same extension settings — the panel GNOME's Extensions
app exposes for EasySpeak, which also makes it **start on login** and opens
**About EasySpeak**.

## Mouse grid

![A 3x3 numbered grid overlaying the GNOME Files window, with a red crosshair centered on cell 5](media/mouse-grid-files.png){ width="100%" }

The **mouse grid** (["grid" command](commands.md#mouse-grid)) overlays a
numbered 3×3 grid on the whole screen. Saying a digit zooms the grid into
that cell; repeat until the crosshair sits over your target, then say
**"click"**. Here it is layered over the GNOME Files manager — the grid
works over any window.

![The same numbered grid overlaying the qutebrowser window on the DuckDuckGo start page](media/mouse-grid-browser.png){ width="100%" }

The same grid driving the cursor inside the browser. Because the overlay is
compositor-level, the identical "say a number to zoom, then click" flow reaches
anything on screen, web pages included.

## Browser link hints

![qutebrowser in hint mode on the DuckDuckGo start page, with yellow numbered labels tagging every clickable element](media/browser-link-hints.png){ width="100%" }

**Browser control** via qutebrowser's hint mode
(["numbers" command](commands.md#browser-qutebrowser)). Every clickable
element — the search box, the Search / Duck.ai toggles, the
Customize button — is tagged with a short label. Speak a label to follow
that link or focus that field, no mouse needed.
