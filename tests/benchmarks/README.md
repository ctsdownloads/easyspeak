# Benchmark tests

Timing benchmarks for `EasySpeak.transcribe()` across Whisper model and
CPU-thread variants. Each case times the full transcribe path — the WAV
temp-file round-trip and prompt/VAD defaults — not just the bare
faster-whisper call.

## How they run

The first run downloads the canonical JFK FLAC sample (~11s) and the
requested Whisper models, so this folder is **excluded from default
discovery** (see `pyproject.toml`) and is opt-in:

```sh
just benchmark        # uv run --extra=benchmark pytest ... --benchmark-json=results.json
just benchmark -v     # extra pytest args pass through
```

Results land in `results.json` for upload to [bencher.dev](https://bencher.dev):

```sh
bencher run --adapter python_pytest --file results.json \
    "pytest --benchmark-json=results.json tests/benchmarks/"
```

## Layout

```sh
test_whisper.py    # parametrized transcribe() benchmark over model/thread variants
conftest.py        # session fixtures: downloads the sample, decodes it to 16 kHz PCM
```
