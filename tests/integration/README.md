# Integration tests

Real-execution checks for the boundaries the unit suite can only mock: the
text-to-speech pipeline and the systemd user unit. The unit tests prove the
right argv is *built* or the right `systemctl` call is *made*; these run the
real `piper`/audio-player binaries and the genuine `systemctl --user` to
prove those invocations are actually accepted.

## How they run

They drive external commands for real, so this folder is **excluded from
default discovery** (see `pyproject.toml`) and is opt-in:

```sh
just integration       # uv run --extra=integration pytest tests/integration
just integration -q    # extra pytest args pass through
```

Each test **skips gracefully** when the binary or server it needs is absent
(missing voice model, no PulseAudio/PipeWire, no user systemd manager), so on
an unprepared machine — including headless CI — the folder degrades to a
no-op rather than a failure.

## Layout

```sh
test_speech_pipeline.py        # piper synthesis + player playback for real
test_gnome_extension_unit.py   # install_refresh_unit enabled by real systemd
conftest.py                    # stubs heavy deps; skip fixtures for audio/systemd
```
