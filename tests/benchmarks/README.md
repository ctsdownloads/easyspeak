# Benchmark tests

Timing benchmarks for `EasySpeak.transcribe()` across Whisper model and
CPU-thread variants, and for Parakeet. Each case times the full transcribe path — the WAV
temp-file round-trip and prompt/VAD defaults — not just the bare
faster-whisper call.

## How they run

The first run downloads the canonical JFK FLAC sample (~11s) and the
requested speech models, so this folder is **excluded from default
discovery** (see `pyproject.toml`) and is opt-in. Allow the model downloads
with `EASYSPEAK_OFFLINE=relaxed`:

```sh
EASYSPEAK_OFFLINE=relaxed just benchmark      # prints a timing table per model
EASYSPEAK_OFFLINE=relaxed just benchmark -v   # extra pytest args pass through
```

## Layout

```sh
test_whisper.py    # parametrized transcribe() benchmark over model/thread variants
test_parakeet.py   # the same transcribe() benchmark for Parakeet
conftest.py        # session fixtures: downloads the sample, decodes it to 16 kHz PCM
```
