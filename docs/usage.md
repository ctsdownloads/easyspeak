# Usage

```bash
uv run easyspeak
```

uv manages the environment for you. If you installed into a plain virtual
environment instead, activate it each time you open a new terminal and run the
script directly:

```bash
source ~/easyspeak-venv/bin/activate
easyspeak
```

Say "Hey Jarvis" followed by a command. After a command that gives no spoken
reply (such as volume changes), EasySpeak keeps listening for a few seconds so
you can chain commands — say "louder", "louder", "louder" without repeating the
wake word each time.

## Command-line options

| Flag                     | Default             | Effect                                                          |
| ------------------------ | ------------------- | --------------------------------------------------------------- |
| `-v`, `--verbose`        |                     | Show debug output                                               |
| `-q`, `--quiet`          |                     | Show only warnings and errors                                   |
| `--configure [ITEM ...]` | `extension service` | Set up the listed integrations and exit                         |
| `--preview ITEM`         |                     | Print the file content that would be configured and exit        |
| `--language CODE`        |                     | Language to dictate and be answered in; or `EASYSPEAK_LANGUAGE` |

`--language` is the command-line form of `EASYSPEAK_LANGUAGE` (see below) and
overrides it. For `--configure`/`--preview`, each `ITEM` is one of `extension`, `service`,
`autostart`, or `desktop`. Verbosity can also be set with the
`EASYSPEAK_LOG_LEVEL` environment variable (e.g. `DEBUG`, `INFO`, `WARNING`),
but the command-line flags take precedence.

See [`core.cli`][core.cli] and [`core.log`][core.log] for
the underlying argument parsing and logging setup.

## Configuration

Behavior is tuned through `EASYSPEAK_*` environment variables, grouped below by
the module that reads each (linked to its API reference).

### [`core.config`][core.config]

| Variable                         | Default                                | Effect                                      |
| -------------------------------- | -------------------------------------- | ------------------------------------------- |
| `EASYSPEAK_HOTKEY`               | `ctrl+shift`                           | Keys held to dictate without the wake word  |
| `EASYSPEAK_LANGUAGE`             | `en`                                   | Language you dictate in and are answered in |
| `EASYSPEAK_MODELS_DIR`           | `models/` beside the venv              | Where language packs are installed          |
| `EASYSPEAK_OFFLINE`              | `strict`                               | Stay offline; `relaxed` downloads models    |
| `EASYSPEAK_PIPER_BIN`            | `piper`                                | Piper TTS binary                            |
| `EASYSPEAK_REQUIRE_WAKE_WORD`    | unset                                  | Modes wait for the wake word each command   |
| `EASYSPEAK_PIPER_MODEL`          | an installed language pack's voice     | Piper voice `.onnx` for speech output       |
| `EASYSPEAK_SOUNDS_DIR`           | `/usr/share/sounds/freedesktop/stereo` | Directory of the wake chime and error bell  |
| `EASYSPEAK_WHISPER_COMPUTE_TYPE` | `int8`                                 | CTranslate2 compute type                    |
| `EASYSPEAK_WHISPER_CPU_THREADS`  | `0`                                    | CPU threads for transcription (`0` = auto)  |
| `EASYSPEAK_WHISPER_MODEL`        | an installed language pack's model     | faster-whisper model for transcription      |
| `EASYSPEAK_SILENCE_THRESHOLD`    | measured at startup                    | Amplitude below which audio counts as quiet |

`EASYSPEAK_LANGUAGE` is the language you dictate in, and the language of the
spoken replies where they are translated (German, Italian, French and Spanish
are) and that language's pack is installed; commands stay English. Where the
replies fall back to English, or the code is not one Whisper knows, a warning at
startup says so. It picks which installed
[language pack](packaging.md#language)
`EASYSPEAK_WHISPER_MODEL` defaults to; without one it falls back to `base.en`
for English and to the multilingual `small` for any other language (a download,
see `EASYSPEAK_OFFLINE`). `EASYSPEAK_PIPER_MODEL` defaults to the voice of the
pack the replies are spoken in, else `~/.local/share/piper/en_US-amy-medium.onnx`.

`EASYSPEAK_SILENCE_THRESHOLD` is normally left alone. On startup EasySpeak
listens to the room for a second and sets the threshold above whatever it
measures — a fixed value assumes a quiet room, and where the ambient level sits
above it (a desk fan, a desktop machine) silence is never detected, so every
recording runs to its full time cap and every command feels slow. The measured
floor is printed at startup:

```
Room noise floor 412; silence threshold 1030
```

Set the variable to skip the measurement, e.g. if you happen to be talking during
the first second after launch.

`EASYSPEAK_HOTKEY` takes the `ctrl`/`shift`/`alt`/`super` aliases or raw evdev
key names joined with `+` (e.g. `ctrl+space`); set it to empty, `off`, or `none`
to turn it off, and an unrecognized key disables it too. See
[Packaging](packaging.md) for the device access it needs.

### [`core.log`][core.log]

| Variable              | Default | Effect                                        |
| --------------------- | ------- | --------------------------------------------- |
| `EASYSPEAK_LOG_LEVEL` | `INFO`  | Logging level when no `-v`/`-q` flag is given |

### [`plugins.dictation`][plugins.dictation]

| Variable                 | Default   | Effect                                             |
| ------------------------ | --------- | -------------------------------------------------- |
| `EASYSPEAK_ATSPI_PYTHON` | probed    | Interpreter running the dictation AT-SPI helper    |
| `EASYSPEAK_PASTE_KEYS`   | per app   | Keystroke that pastes dictated text                |

Dictation types by putting the text on the clipboard and sending a paste
keystroke — every toolkit implements paste, whereas accessibility-level
insertion is widely stubbed out. `EASYSPEAK_PASTE_KEYS` overrides the chord, e.g.
`shift+insert`; by default it is Ctrl+V, or Ctrl+Shift+V when a terminal has
focus. It accepts `ctrl`, `shift`, `alt`, `super`, `insert` and `v` joined with
`+`.

`EASYSPEAK_ATSPI_PYTHON` is normally left alone. The AT-SPI helper needs
PyGObject and the AT-SPI typelib, which the application's own virtual environment
usually lacks, so candidate interpreters are probed with the helper's real import
chain and the first that works is kept. Set the variable to point straight at one
(the Nix flake does).
