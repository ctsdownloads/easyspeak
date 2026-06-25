# Unit tests

Fast, isolated checks of every `easyspeak` module with the heavy
native/model dependencies mocked out. Unlike the other folders, this is the
**default discovery** target — `just pytest` runs it with no extra needed
(and `just test` runs it alongside every other suite).

They cover the core runtime and each plugin in isolation: that the right
argv is *built*, the right plugin is *routed* to, config parses, and so on —
not whether external binaries actually accept those calls (that's
`tests/integration`).

## How they run

Always-on, no models or hardware required: `core/conftest.py` stubs
`pyaudio`, `pyopen_wakeword` and `faster_whisper` before any module imports, so
the suite loads on a bare machine — including headless CI.

```sh
just pytest        # uv run --extra=unittest coverage run -m pytest
just coverage      # show the coverage report from the last run
just test          # full chain: test-js, pytest, coverage, integration, acceptance
just pytest -x     # extra pytest args pass through
```

## Layout

```sh
core/test_*.py       # one module per core file (cli, config, speech, tray, ...)
plugins/test_*.py    # one module per plugin (apps, browser, dictation, ...)
core/conftest.py     # stubs native/model deps; mock-plugin fixtures
plugins/conftest.py  # mock-core fixtures (audio, host_run, file managers)
conftest.py          # readlog: capsys-style view over captured logging
```
