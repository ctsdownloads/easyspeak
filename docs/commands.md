# Commands

Say "Hey Jarvis" followed by any of the commands below. Say **"help"** at any
time to print the full list to the terminal.

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
| open youtube | Open bookmark[^bookmarks] |
| exit browser | Leave browser mode |

[^hints]:
    On startup, EasySpeak ensures `~/.config/qutebrowser/config.py` has the setup
    needed for link hints to appear as numbers. See
    [Troubleshooting](troubleshooting.md#browser-plugin-link-numbers-dont-work)
    if numbers don't show.

[^bookmarks]:
    Built-in bookmarks: youtube, google, gmail, github, reddit, twitter,
    facebook, amazon, netflix, duckduckgo.

## Dictation

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

## Apps

| Command | Action |
|---------|--------|
| open [app] | Launch application |
| close [app] | Close application |

Default apps live in [`plugins/apps.py`](https://github.com/ctsdownloads/easyspeak/blob/HEAD/src/plugins/apps.py)
(edit to match your system): firefox, steam, spotify, calculator, settings,
files, terminal, browser, music player, and more. Some accept spoken aliases —
e.g. "open music app" works the same as "open music player".

"Open terminal" and "close terminal" are special: they open and close your
system's default terminal, whichever one that is, rather than a fixed app.

## Files

| Command | Action |
|---------|--------|
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
| play | Resume playback |
| pause / stop the music | Pause playback |
| next / skip | Next track |
| previous / back | Previous track |

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

## General

| Command | Action |
|---------|--------|
| help | List all commands |
| go to sleep / stop listening | Release the mic (reactivate from the tray icon) |
| quit / exit / goodbye | Exit EasySpeak |
