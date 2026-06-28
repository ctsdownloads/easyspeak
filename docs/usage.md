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

| Flag | Effect |
|------|--------|
| `-v`, `--verbose` | Show debug output |
| `-q`, `--quiet` | Show only warnings and errors |

Verbosity can also be set with the `EASYSPEAK_LOG_LEVEL` environment variable
(e.g. `DEBUG`, `INFO`, `WARNING`); the command-line flags take precedence.

See [`core.cli`][core.cli] and [`core.log`][core.log] for
the underlying argument parsing and logging setup.

## Configuration

Behaviour is tuned through `EASYSPEAK_*` environment variables (wake threshold,
Whisper model, Piper model path, and more). The full list lives in
[`core.config`][core.config].
