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

| Flag                     | Default             | Effect                                           |
| ------------------------ | ------------------- | ------------------------------------------------ |
| `-v`, `--verbose`        |                     | Show debug output                                |
| `-q`, `--quiet`          |                     | Show only warnings and errors                    |
| `--configure [ITEM ...]` | `extension service` | Set up the listed integrations and exit          |
| `--show [ITEM ...]`      | all                 | Print the listed items' files to stdout and exit |

For `--configure`/`--show`, each `ITEM` is one of `extension`, `service`,
`autostart`, or `desktop`. Verbosity can also be set with the
`EASYSPEAK_LOG_LEVEL` environment variable (e.g. `DEBUG`, `INFO`, `WARNING`),
but the command-line flags take precedence.

See [`core.cli`][core.cli] and [`core.log`][core.log] for
the underlying argument parsing and logging setup.

## Configuration

Behavior is tuned through `EASYSPEAK_*` environment variables, grouped below by
the module that reads each (linked to its API reference).

### [`core.config`][core.config]

| Variable                         | Default                                | Effect                                               |
| -------------------------------- | -------------------------------------- | ---------------------------------------------------- |
| `EASYSPEAK_HOTKEY`               | `1`                                    | Set `0` to disable hold-to-dictate silent activation |
| `EASYSPEAK_HOTKEY_COMBO`         | `ctrl+shift`                           | Keys held to dictate without the wake word           |
| `EASYSPEAK_PIPER_BIN`            | `piper`                                | Piper TTS binary                                     |
| `EASYSPEAK_PIPER_MODEL`          | bundled Amy voice                      | Piper voice `.onnx` for speech output                |
| `EASYSPEAK_SOUNDS_DIR`           | `/usr/share/sounds/freedesktop/stereo` | Directory of the wake chime and error bell           |
| `EASYSPEAK_WHISPER_COMPUTE_TYPE` | `int8`                                 | CTranslate2 compute type                             |
| `EASYSPEAK_WHISPER_CPU_THREADS`  | `0`                                    | CPU threads for transcription (`0` = auto)           |
| `EASYSPEAK_WHISPER_MODEL`        | `base.en`                              | faster-whisper model for transcription               |

`EASYSPEAK_HOTKEY_COMBO` takes the `ctrl`/`shift`/`alt`/`super` aliases or raw
evdev key names joined with `+`, and needs read access to `/dev/input` (be in
the `input` group).

### [`core.log`][core.log]

| Variable              | Default | Effect                                        |
| --------------------- | ------- | --------------------------------------------- |
| `EASYSPEAK_LOG_LEVEL` | `INFO`  | Logging level when no `-v`/`-q` flag is given |

### [`plugins.dictation`][plugins.dictation]

| Variable                 | Default   | Effect                                          |
| ------------------------ | --------- | ----------------------------------------------- |
| `EASYSPEAK_ATSPI_PYTHON` | `python3` | Interpreter running the dictation AT-SPI helper |
