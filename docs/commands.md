# Commands

Say "Hey Jarvis" followed by any of the commands below. Say **"help"** at any
time to print the full list to the terminal, described in the active language.

## Mouse grid

Screen splits into a 3x3 layout (like a phone keypad):

```
1 2 3
4 5 6
7 8 9
```

Say **"grid"** to show it. Say a number to zoom into that zone. Keep zooming
until you're over your target, then **"click"**.

Chain numbers to go faster: **"3 6 3"** zooms three times at once.

**Drag and drop:**

1. Navigate to the thing you want to drag
2. Say **"mark"** — grabs it (mousedown)
3. Grid resets to full screen
4. Navigate to where you want to drop it
5. Say **"drag"** — releases it (mouseup)

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

## Head tracking (experimental)

Requires a webcam and additional dependencies — see [Installation](installation.md#head-tracking-optional).

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

## Browser (Qutebrowser)

| Command | Action |
|---------|--------|
| browser | Enter browser mode |
| numbers / hints | Show link hints[^hints] |
| zero two | Click hint 02 |
| new tab | Open new tab |
| close tab | Close current tab |
| next tab / switch tab | Go to the next tab |
| last tab / previous tab | Go to the previous tab |
| tab [number] | Switch to a tab by number |
| close tab [number] | Close a tab by number |
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
| open youtube | Open bookmark[^bookmarks] |
| fix rendering | Switch the browser to software rendering[^rendering] |
| restore rendering | Switch it back to hardware rendering |
| allow ads | Turn ad blocking off[^adblock] |
| block ads | Turn ad blocking back on |
| enter | Press Enter (submit a form or search) |
| press tab | Press Tab |
| press escape | Press Escape in the page |
| press down five | Press the Down arrow five times |
| exit browser | Leave browser mode |

[^hints]:
    On startup, EasySpeak ensures `~/.config/qutebrowser/config.py` has the setup
    needed for link hints to appear as numbers. See
    [Troubleshooting](troubleshooting.md#browser-plugin-link-numbers-dont-work)
    if numbers don't show.

[^rendering]:
    Some graphics drivers render video sites badly under qutebrowser — smeared
    text, stuttering icons, a player that flickers. This writes
    `c.qt.args = ["disable-gpu-compositing"]` to your qutebrowser config and
    restarts the browser. Say "restore rendering" to undo it.

[^adblock]:
    Some sites detect element-level ad blocking and break on purpose. This writes
    `c.content.blocking.enabled = False` and restarts the browser. Ad overlays
    then take hint numbers away from the page underneath, so turn it back on when
    you are done.

[^bookmarks]:
    Built-in bookmarks: youtube, google, gmail, github, reddit, twitter,
    facebook, amazon, netflix, duckduckgo.

Commands may start with a filler word — "and scroll down", "so back" — which is
stripped before matching, since Whisper adds them.

Keystrokes need `press` in front here, apart from `enter`: `down`, `up`, `tab` and
`escape` already mean something else in this mode.

## Dictation

Dictation places text by pasting it, which needs `wl-clipboard` installed and a
text field focused. In the browser, use `numbers` and pick the hint on the field
first.

The words below are the English ones. When you dictate in another language
(`EASYSPEAK_LANGUAGE`), the control words are that language's: "Komma", "neue
Zeile", "Notizen beenden" in German, and so on. Each language's words are the
table `locale/<language>/vocabulary.toml` in the dictation plugin, mishearings
included, so they can be tuned without touching code.

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
| space | Insert space |
| at sign | Insert @ |
| hashtag | Insert # |
| percent | Insert % |
| asterisk | Insert * |

### Editing and keys

These send real keystrokes rather than inserting text, so they work in browser
fields and forms as well as editors. The arrows need `press` in front, since a
bare "up" or "right" is ordinary dictated speech.

| Command | Action |
|---------|--------|
| backspace | Delete one character |
| backspace five | Delete five characters |
| scratch that | Delete what the last utterance inserted |
| enter | Press Enter |
| tab | Press Tab |
| escape | Press Escape |
| page up | Press Page Up |
| page down | Press Page Down |
| press down | Press the Down arrow |
| press down five | Press the Down arrow five times |

## Apps

| Command | Action |
|---------|--------|
| open [app] | Launch application |
| close [app] | Close application |

Default apps live in [`plugins/apps`](https://github.com/ctsdownloads/easyspeak/blob/HEAD/src/plugins/apps/__init__.py)
(edit to match your system): firefox, steam, spotify, calculator, settings,
terminal, browser, music player, and more. Some accept spoken aliases —
e.g. "open music app" works the same as "open music player".

"Open terminal" and "close terminal" are special: they open and close your
system's default terminal, whichever one that is, rather than a fixed app.

## Files

Folders open in whatever file manager your desktop is configured for (via
`xdg-open`).

| Command | Action |
|---------|--------|
| open files / file manager | Open your default file manager (at `$HOME`) |
| open documents | Open Documents folder |
| open downloads | Open Downloads folder |
| open pictures | Open Pictures folder |
| open music | Open Music folder |
| open videos | Open Videos folder |
| open projects | Open Projects folder |
| open home | Open home folder |
| open desktop | Open Desktop folder |

## Media

| Command | Action |
|---------|--------|
| play / resume | Resume playback |
| pause / stop the music | Pause playback |
| next / skip | Next track |
| previous | Previous track |

## System

| Command | Action |
|---------|--------|
| volume up/down (or louder / quieter) | Adjust volume one step (repeat to keep going) |
| very loud / very silent | Jump straight to near-max (85%) / low (15%, not muted) |
| mute | Toggle mute |
| brightness up/down | Adjust brightness |
| do not disturb on/off | Toggle notifications |

Volume changes are silent — GNOME's own on-screen display and chime acknowledge
them.

## Speakers playing audio

Modes normally take a command on their own, with no wake word. That is faster, but
a video playing through speakers reaches the microphone too, and its speech is
transcribed like anything else.

Say **"require wake word"** and modes wait for the wake word before every
command, exactly like the main loop: say "Hey Jarvis", wait for the chime, then
say the command. Page audio never says the wake word, so it can no longer trigger
anything. Dictation is exempt, so a note still takes continuous speech. Say
**"free listening"** to go back.

Set `EASYSPEAK_REQUIRE_WAKE_WORD=1` to start that way every time. Headphones or
PipeWire echo cancellation solve the same problem at the audio level.

## Knowing which mode is listening

Modes announce themselves, so you don't need a terminal to follow along:
"Browser", "Grid", "Dictation", "Ready" when link hints appear, "Clicked",
"Holding" and "Dropped" while dragging, "Hints closed", "Left the browser".

Modes also end on their own after a spell with no recognised command — 30 seconds
for the grid and head tracking, a minute for dictation, three minutes for the
browser. When one does, you'll hear what changed:

> "Leaving browser. Say Hey Jarvis to continue."

## General

| Command | Action |
|---------|--------|
| help | List all commands |
| go to sleep / stop listening | Release the mic (reactivate from the tray icon or the Quick Settings toggle) |
| quit / exit / goodbye | Exit EasySpeak |
