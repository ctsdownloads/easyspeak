"""Kokoro TTS worker: stdin reply lines in, raw s16le mono PCM out.

Spawned by the speech pipeline as `python -m easyspeak.core.kokoro_worker`
with `--ready-fd <n>` — the write end of a pipe, handed over at its real
descriptor number via `pass_fds`. The protocol has two channels:

- stdout carries raw s16le mono PCM at 24 kHz and nothing else: one reply per
  stdin line, so the player downstream never sees log noise in its stream.
- After the warmup synthesis the worker writes one `ready provider=<ep>` line
  to the ready fd and never touches that fd again, so the parent learns that
  the engine came up AND which execution provider engaged (the provisioner's
  verify reads it back). Logs go to stderr, which the parent points at
  DEVNULL in normal runs.

`onnxruntime` and `kokoro_onnx` are imported lazily, inside functions: this
module must import cleanly on venvs where those wheels are absent (the dev
suite runs on Python 3.14, where kokoro-onnx cannot install). All engine
policy arrives via argv and env; see the Kokoro design spec §3.2.
"""

import argparse
import ctypes
import io
import logging
import os
import sys
import sysconfig
from pathlib import Path

import numpy as np

from . import log

logger = logging.getLogger(__name__)

SPEAK_SAMPLE_RATE = 24000
SILENCE_PEAK = 1e-4
WARMUP_TEXT = "Hello."


def to_s16le(samples):
    """Float samples in [-1, 1] → little-endian s16 mono PCM bytes."""
    # Scale by 32767, never 32768: +1.0 would wrap to -32768 in int16 and click.
    # The clip guarantees the cast stays in range; truncation vs rounding differs
    # by at most one least-significant bit (inaudible), and this is byte-exact
    # with the spike's proven output path.
    return (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()


def is_silent(samples):
    """Detect the spike's silent-output class (fp16 on CUDA, q8f16 for it/es).

    Peak amplitude over the whole buffer, with an empty buffer as silence:
    feeding the player a zero-length stream would surface as missing audio
    instead of a worker failure, so it must be named as one.
    """
    return len(samples) == 0 or float(np.max(np.abs(samples))) < SILENCE_PEAK


def preload_nvidia_libraries(purelib=None):
    """CDLL the pip-wheel CUDA libraries so onnxruntime's dlopen can find them.

    ORT 1.31 does not discover site-packages/nvidia on its own, and pinning
    CUDA without cuDNN raises NOT_IMPLEMENTED instead of falling back, so the
    load outcome decides the provider policy. Returns whether libcudnn AND
    libcublas loaded — the probe result `resolve_providers` consumes.

    The libraries interdepend (cublas needs cublasLt, cuDNN needs its sub-libs)
    and dlopen only resolves a dependency that is already loaded, so loading
    runs in fixed-point passes: repeat until a pass loads nothing new. A
    library that cannot load is logged and skipped — never a hard failure,
    because the machine is simply on CPU then.
    """
    if purelib is None:
        # Resolve via sysconfig, never by walking __file__ parents: in a
        # src-layout checkout __file__ points into the repo, not site-packages.
        purelib = sysconfig.get_paths()["purelib"]
    pending = {str(path) for path in Path(purelib).glob("nvidia/*/lib/lib*.so*")}
    loaded = set()
    while pending:
        progressed = False
        for path in sorted(pending):
            try:
                ctypes.CDLL(path)
            except OSError as error:
                logger.debug("preload skipped %s: %s", path, error)
            else:
                loaded.add(path)
                pending.discard(path)
                progressed = True
        if not progressed:
            break
    names = {path.rsplit("/", 1)[-1] for path in loaded}
    return any(n.startswith("libcudnn") for n in names) and any(
        n.startswith("libcublas") for n in names
    )


def available_providers():
    """The providers this onnxruntime build was compiled with (metadata only)."""
    import onnxruntime

    return onnxruntime.get_available_providers()


def build_session(model_path, providers):
    """Create the inference session — the constructor the provider policy gates."""
    import onnxruntime

    return onnxruntime.InferenceSession(model_path, providers=providers)


def resolve_providers(cuda_libs_loaded):
    """Probe before pin: CUDA only when the build lists it AND its libraries loaded.

    `ONNX_PROVIDER` wins verbatim at selection — an explicit pin is never
    second-guessed here. It does not outlive a failing session, though: a
    pinned CUDA whose session still fails to init falls back to CPU in
    `start_session`, and the ready line reports what actually engaged.
    The available-providers list alone lies: it is build-time metadata that
    names CUDA even on machines whose CUDA libraries cannot load.
    """
    override = os.environ.get("ONNX_PROVIDER")
    if override:
        return [override]
    available = available_providers()
    if cuda_libs_loaded and "CUDAExecutionProvider" in available:
        return ["CUDAExecutionProvider"]
    logger.info(
        "onnxruntime CUDA unavailable (listed: %s, cudnn+cublas loaded: %s); "
        "running on CPU",
        "CUDAExecutionProvider" in available,
        cuda_libs_loaded,
    )
    return ["CPUExecutionProvider"]


def start_session(model_path, cuda_libs_loaded):
    """Create the session; a failed CUDA init falls back to CPU instead of dying.

    The probe is still no guarantee: the libraries can load while CUDA *session*
    init fails (driver mismatch and friends) — and that holds for an explicit
    `ONNX_PROVIDER=CUDAExecutionProvider` pin too. One CPU rebuild keeps a
    broken-driver machine talking; a CPU-provider failure is real and raises.
    Returns (session, providers) — `providers` is what the ready line reports.
    """
    pinned = resolve_providers(cuda_libs_loaded)
    try:
        return build_session(model_path, pinned), pinned
    except Exception as error:  # broad on purpose — the daemon stays alive
        if "CUDAExecutionProvider" not in pinned:
            raise
        logger.warning("CUDA session init failed; running on CPU: %s", error)
        fallback = ["CPUExecutionProvider"]
        return build_session(model_path, fallback), fallback


def announce_ready(write, provider):
    """Report the engine up and its engaged provider — the fd's only traffic."""
    write(f"ready provider={provider}\n".encode())


def synthesize(engine, text, *, voice, speed, lang, out):
    """Synthesize one phrase and stream its s16le PCM to `out`.

    Returns False — having written nothing — when the result would poison the
    stream: silence (the spike's fp16-on-CUDA / q8f16 class) or a sample rate
    other than the protocol's 24 kHz (the player would play it at the wrong
    pitch). The caller exits nonzero either way; at warmup that is a death
    before `ready`, mid-loop a death after it (the pipeline's strike path,
    spec §3.3).
    """
    samples, rate = engine.create(text, voice=voice, speed=speed, lang=lang)
    if rate != SPEAK_SAMPLE_RATE:
        logger.error(
            "unexpected sample rate %s (protocol is %d Hz)", rate, SPEAK_SAMPLE_RATE
        )
        return False
    if is_silent(samples):
        return False
    out.write(to_s16le(samples))
    out.flush()
    return True


def parse_args(argv=None):
    """Parse the worker's argv (all engine policy arrives via argv and env)."""
    parser = argparse.ArgumentParser(
        prog="easyspeak.core.kokoro_worker",
        description="Kokoro TTS worker: reply lines in, raw s16le mono PCM out.",
    )
    parser.add_argument("--model", required=True, help="path to the ONNX model")
    parser.add_argument("--voices", required=True, help="path to the voices file")
    parser.add_argument("--voice", required=True, help="voice name, e.g. af_heart")
    parser.add_argument(
        "--lang", required=True, help="kokoro language code, e.g. en-us"
    )
    parser.add_argument(
        "--speed", type=float, default=1.0, help="speech rate multiplier"
    )
    parser.add_argument(
        "--ready-fd",
        type=int,
        required=True,
        help="descriptor of the pipe write end that receives `ready provider=<ep>`",
    )
    return parser.parse_args(argv)


def main(argv=None):
    """Warm up, announce ready, then synthesize one reply per stdin line.

    stdin EOF ends the process with exit 0 — the pipeline's `drain()` closes
    our stdin as the deliberate shutdown path. Anything that would poison the
    stream (silence, a foreign sample rate, a synthesis error) exits nonzero
    instead, which the pipeline counts as a not-ready engine (strike, rebuild).
    """
    args = parse_args(argv)
    # The parent passes its level down via EASYSPEAK_LOG_LEVEL, so the worker
    # logs like the daemon whenever stderr is inherited under --verbose.
    log.configure(log.resolve_level())

    ready = os.fdopen(args.ready_fd, "wb", buffering=0)

    # Preload BEFORE any onnxruntime import: the provider policy needs to know
    # whether cuDNN/cuBLAS can load before it picks a provider.
    cuda_libs_loaded = preload_nvidia_libraries()
    session, providers = start_session(args.model, cuda_libs_loaded)

    import kokoro_onnx

    engine = kokoro_onnx.Kokoro.from_session(session, args.voices)

    # Warmup through the real synthesize-and-write path, audio discarded, so
    # the first real reply skips the ~0.6-1.3 s first-CUDA-inference cost.
    if not synthesize(
        engine,
        WARMUP_TEXT,
        voice=args.voice,
        speed=args.speed,
        lang=args.lang,
        out=io.BytesIO(),
    ):
        logger.error("warmup synthesis produced no usable audio; exiting without ready")
        sys.exit(1)

    announce_ready(ready.write, providers[0])
    logger.debug(
        "kokoro worker ready: model=%s provider=%s rate=%d",
        args.model,
        providers[0],
        SPEAK_SAMPLE_RATE,
    )

    # Replies are 1-3 words by construction, so no chunking: a pathologically
    # long line only degrades latency, it cannot corrupt the stream framing.
    for line in sys.stdin:
        text = line.strip()
        if not text:
            continue
        try:
            if not synthesize(
                engine,
                text,
                voice=args.voice,
                speed=args.speed,
                lang=args.lang,
                out=sys.stdout.buffer,
            ):
                logger.error(
                    "synthesis produced no usable audio; refusing to emit: %r", text
                )
                sys.exit(1)
        except Exception:
            # stderr is DEVNULL in normal runs, so under --verbose this is the
            # only record of WHY the engine died (a dead player's broken pipe
            # included). Exit nonzero so the pipeline strikes and rebuilds.
            logger.exception("synthesis failed; exiting: %r", text)
            sys.exit(1)


if __name__ == "__main__":
    main()
