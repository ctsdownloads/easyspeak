"""
Whisper transcription benchmarks.

Each variant times EasySpeak.transcribe() so the benchmark covers the WAV
temp-file round-trip and prompt/VAD defaults, not just the bare faster-whisper
call. Results upload to bencher.dev via:

    bencher run --adapter python_pytest --file results.json \\
        "pytest --benchmark-json=results.json tests/benchmarks/"
"""

from __future__ import annotations

import pytest
from easyspeak.core.main import EasySpeak, load_whisper_model

VARIANTS = [
    # (model_name, cpu_threads)
    pytest.param("base.en", 0, id="base.en-auto"),
    pytest.param("base.en", 2, id="base.en-2threads"),
    pytest.param("base.en", 10, id="base.en-10threads"),
    pytest.param("tiny.en", 2, id="tiny.en-2threads"),
    pytest.param("tiny.en", 10, id="tiny.en-10threads"),
]


@pytest.mark.parametrize("model_name,cpu_threads", VARIANTS)
def test_transcribe(
    benchmark, sample_pcm: bytes, model_name: str, cpu_threads: int
) -> None:
    app = EasySpeak()
    app.whisper = load_whisper_model(
        model_name=model_name, cpu_threads=cpu_threads, compute_type="int8"
    )

    benchmark.pedantic(
        lambda: app.transcribe(sample_pcm),
        rounds=5,
        iterations=1,
        warmup_rounds=1,
    )
