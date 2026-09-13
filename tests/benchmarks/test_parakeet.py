"""
Parakeet transcription benchmark, on the same sample and path as the Whisper ones.

The first run fetches the int8 ONNX model (about 640 MB) into the models
directory, which is why CI runs `just benchmark` with `EASYSPEAK_OFFLINE=relaxed`
and caches that directory.
"""

from __future__ import annotations

from easyspeak.core.main import EasySpeak, load_parakeet_model


def test_transcribe_parakeet_v3_int8(benchmark, sample_pcm: bytes) -> None:
    app = EasySpeak()
    app.parakeet = load_parakeet_model()

    benchmark.pedantic(
        lambda: app.transcribe(sample_pcm),
        rounds=5,
        iterations=1,
        warmup_rounds=1,
    )
