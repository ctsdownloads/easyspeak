# Integration tests

Real-execution checks for the boundaries the unit suite can only mock: the
text-to-speech pipeline, the systemd user unit, and the grid's ydotool
backend. The
unit tests prove the right argv is *built* or the right `systemctl` call is
*made*; these run the real `piper`/audio-player binaries, the genuine
`systemctl --user`, and the real overlay + injector pair to prove those
invocations are actually accepted.

## How they run

They drive external commands for real, so this folder is **excluded from
default discovery** (see `pyproject.toml`) and is opt-in:

```sh
just integration       # uv run --extra=integration pytest tests/integration
just integration -q    # extra pytest args pass through
```

Each test **skips gracefully** when the binary or server it needs is absent
(missing voice model, no PulseAudio/PipeWire, no user systemd manager, no
sway/ydotool/gtk4-layer-shell), so on an unprepared machine — including headless
CI — the folder degrades to a no-op rather than a failure.

## Layout

```sh
test_speech_pipeline.py             # piper synthesis + player playback for real
test_gnome_extension_unit.py        # install_refresh_unit enabled by real systemd
test_mousegrid_ydotool_harness.py   # grid ydotool backend: gate, overlay + argv, live click arm
grid_probe_window.py                # fullscreen GTK4 window reporting pointer events as JSON
conftest.py                         # stubs heavy deps; skip fixtures for audio/systemd
```

## The grid's ydotool harness

`test_mousegrid_ydotool_harness.py` runs the grid conversation end to end in a
headless sway session it starts and tears down itself: gate behaviour, overlay
rendering, exact injection argv, and — only when opted in — a click landing in
the aimed cell. Its prerequisites, its environment variables, and why the live
arm is opt-in are in the module docstring; machine setup lives in
docs/troubleshooting.md.
