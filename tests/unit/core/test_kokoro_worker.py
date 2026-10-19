"""Tests for the Kokoro worker process (protocol, policy, preload).

The kokoro_onnx wheel cannot install on the dev/CI venv (Python 3.14), so every
test injects a fake module into sys.modules instead of importing the real one —
which is only possible because the worker imports kokoro_onnx/onnxruntime
lazily, inside functions. Importing this test module therefore already proves
the worker's config-time import safety on a venv without the wheels.
"""

import fnmatch
import importlib
import io
import logging
import os
import sys
import types
from types import SimpleNamespace
from unittest.mock import Mock, patch

import easyspeak.core.kokoro_worker as worker
import numpy as np
import pytest

LOUD = np.full(2400, 0.5, dtype=np.float32)


@pytest.fixture
def fake_kokoro(monkeypatch):
    """Inject a kokoro_onnx stand-in; tests set `state.audio`/`state.rate`."""
    state = SimpleNamespace(
        calls=[],
        audio=lambda _text: np.zeros(2400, dtype=np.float32),
        rate=24000,
    )

    class FakeKokoro:
        def __init__(self, session, voices_path):
            self.session = session
            self.voices_path = voices_path
            self.sess = Mock()
            self.sess.get_providers.return_value = ["CPUExecutionProvider"]

        @classmethod
        def from_session(cls, session, voices_path):
            return cls(session, voices_path)

        def create(self, text, voice, speed=1.0, lang="en-us"):
            state.calls.append((text, voice, speed, lang))
            return state.audio(text), state.rate

    module = types.ModuleType("kokoro_onnx")
    module.SAMPLE_RATE = 24000
    module.Kokoro = FakeKokoro
    state.kokoro_class = FakeKokoro
    monkeypatch.setitem(sys.modules, "kokoro_onnx", module)
    return state


class FakeStdout:
    """Stands in for sys.stdout; `buffer` collects exactly what main() emits."""

    def __init__(self):
        self.buffer = io.BytesIO()


@pytest.fixture
def speak_env(monkeypatch, fake_kokoro):
    """Point main()'s engine plumbing at fakes: no real wheel, session, or fd."""
    monkeypatch.setattr(worker, "preload_nvidia_libraries", lambda: False)
    monkeypatch.setattr(worker, "available_providers", lambda: ["CPUExecutionProvider"])
    monkeypatch.setattr(worker, "build_session", lambda model, providers: Mock())
    # configure() mutates the suite's loggers (propagate=False would blind
    # caplog for every later test); the protocol under test doesn't need it.
    monkeypatch.setattr(worker.log, "configure", lambda level: None)
    return SimpleNamespace(state=fake_kokoro)


def worker_argv(ready_fd):
    """The spawn command the pipeline builds (Task 3), minus --speed."""
    return [
        "--model",
        "kokoro-v1.0.onnx",
        "--voices",
        "voices-v1.0.bin",
        "--voice",
        "af_heart",
        "--lang",
        "en-us",
        "--ready-fd",
        str(ready_fd),
    ]


def drive_worker(monkeypatch, stdin_text):
    """Run main() end to end; return (exit_code, ready_line, stdout_bytes).

    The ready fd is a real pipe, so the handshake is exercised the way the
    parent sees it: main() gets the write end's actual descriptor number.
    """
    # sys.stdout/sys.stdin are patched here, in the test body, deliberately:
    # pytest's capture restores both to its own streams at every test-phase
    # boundary, so a patch made in a fixture is silently gone by call time.
    stdout = FakeStdout()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_text))
    # The fd-backed ready writer must not OWN the descriptor: a failure path's
    # traceback (retained by caplog) keeps main's frame — and its os.fdopen
    # FileIO — alive into later tests, and the finalizer would then close an
    # fd number some other test's pipe has reused. closefd=False makes the
    # object harmless; the pipe below is closed exactly once, by this test.
    monkeypatch.setattr(
        worker.os, "fdopen", lambda fd, *a, **k: io.FileIO(fd, "wb", closefd=False)
    )
    read_fd, write_fd = os.pipe()
    code = 0
    try:
        try:
            worker.main(worker_argv(write_fd))
        except SystemExit as exit_exc:
            code = exit_exc.code
    finally:
        # Closed exactly once, here, so the os.read below hits EOF when main
        # died before announcing.
        os.close(write_fd)
    ready = os.read(read_fd, 4096)
    os.close(read_fd)
    return code, ready, stdout.buffer.getvalue()


def test_to_s16le_clips_and_converts():
    pcm = worker.to_s16le(np.array([0.5, 1.5, -2.0], dtype=np.float32))
    assert pcm == np.array([16383, 32767, -32767], dtype="<i2").tobytes()


def test_is_silent_boundaries():
    assert worker.is_silent(np.array([], dtype=np.float32))
    assert worker.is_silent(np.zeros(2400, dtype=np.float32))
    # Peak amplitude, whole buffer, strict less-than. The boundary probes are
    # float64 because in float32 the decimal 1e-4 rounds just *under* itself.
    assert worker.is_silent(np.full(2400, 9e-5, dtype=np.float32))
    assert not worker.is_silent(np.full(4, 1e-4))
    assert worker.is_silent(np.full(4, 9.9e-5))
    assert not worker.is_silent(LOUD)


def test_provider_env_override_wins_verbatim(monkeypatch):
    monkeypatch.setenv("ONNX_PROVIDER", "FooExecutionProvider")
    assert worker.resolve_providers(cuda_libs_loaded=True) == ["FooExecutionProvider"]


def test_cuda_pinned_only_when_listed_and_probed(monkeypatch, caplog):
    monkeypatch.delenv("ONNX_PROVIDER", raising=False)
    cuda_listed = [
        "TensorrtExecutionProvider",
        "CUDAExecutionProvider",
        "CPUExecutionProvider",
    ]
    with (
        patch.object(worker, "available_providers", return_value=cuda_listed),
        caplog.at_level(logging.INFO),
    ):
        # Build metadata alone lies: pinning CUDA without its loaded libraries
        # raises NOT_IMPLEMENTED at session init, hence the probe requirement.
        assert worker.resolve_providers(cuda_libs_loaded=True) == [
            "CUDAExecutionProvider"
        ]
        assert worker.resolve_providers(cuda_libs_loaded=False) == [
            "CPUExecutionProvider"
        ]
        assert "running on CPU" in caplog.text
    cpu_only = ["CPUExecutionProvider"]
    with patch.object(worker, "available_providers", return_value=cpu_only):
        assert worker.resolve_providers(cuda_libs_loaded=True) == cpu_only


def test_cuda_session_failure_falls_back_to_cpu_once(caplog):
    calls = []

    def flaky_cuda(model_path, providers):
        calls.append(providers)
        if providers == ["CUDAExecutionProvider"]:
            raise RuntimeError("NOT_IMPLEMENTED Got InvalidProvider")
        return Mock(name="session")

    with (
        patch.object(worker, "build_session", side_effect=flaky_cuda),
        patch.object(
            worker,
            "available_providers",
            return_value=["CUDAExecutionProvider", "CPUExecutionProvider"],
        ),
        caplog.at_level(logging.INFO),
    ):
        session, providers = worker.start_session("m.onnx", cuda_libs_loaded=True)

    assert providers == ["CPUExecutionProvider"]
    # Exactly one CPU rebuild — the probe cannot foresee a broken driver, but
    # the worker still comes up talking instead of crash-looping.
    assert calls == [["CUDAExecutionProvider"], ["CPUExecutionProvider"]]
    assert "CUDA session init failed; running on CPU" in caplog.text
    assert session is not None


def test_env_pinned_cuda_session_failure_still_falls_back_to_cpu(monkeypatch):
    """An explicit pin decides selection; the ready line reports what engaged.

    `ONNX_PROVIDER=CUDAExecutionProvider` skips the probe entirely (the
    available-providers query must not even run), but if the pinned session
    still fails to init, the ladder rescues the machine onto CPU.
    """
    monkeypatch.setenv("ONNX_PROVIDER", "CUDAExecutionProvider")

    def failing_cuda(model_path, providers):
        if providers == ["CUDAExecutionProvider"]:
            raise RuntimeError("NOT_IMPLEMENTED")
        return Mock(name="session")

    with (
        patch.object(worker, "build_session", side_effect=failing_cuda),
        patch.object(
            worker,
            "available_providers",
            side_effect=AssertionError("env pin must skip the probe"),
        ),
    ):
        _session, providers = worker.start_session("m.onnx", cuda_libs_loaded=False)

    assert providers == ["CPUExecutionProvider"]


def test_cpu_session_failure_raises():
    with (
        patch.object(worker, "build_session", side_effect=OSError("no such model")),
        patch.object(
            worker, "available_providers", return_value=["CPUExecutionProvider"]
        ),
        pytest.raises(OSError, match="no such model"),
    ):
        worker.start_session("m.onnx", cuda_libs_loaded=False)


def wheel_tree(tmp_path, libraries):
    """Fake site-packages nvidia layout; returns (purelib, expected lib paths)."""
    purelib = tmp_path / "site-pkgs"
    for rel in libraries:
        path = purelib / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
    # Only what the worker's glob pattern may pick up is an expectation —
    # stray non-library files (headers, licenses) in the same tree are not.
    return str(purelib), sorted(
        str(purelib / rel)
        for rel in libraries
        if fnmatch.fnmatch(rel.rsplit("/", 1)[-1], "lib*.so*")
    )


def patch_loader(monkeypatch, behavior):
    """Replace ctypes.CDLL with a recorder whose calls run `behavior`."""
    calls = []

    def cdll(path):
        calls.append(path)
        behavior(path)

    monkeypatch.setattr(worker.ctypes, "CDLL", cdll)
    return calls


def test_preload_loads_wheels_and_probes_true(tmp_path, monkeypatch):
    purelib, libs = wheel_tree(
        tmp_path,
        [
            "nvidia/cublas/lib/libcublas.so.12",
            "nvidia/cudnn/lib/libcudnn.so.9",
            "nvidia/cufft/lib/libcufft.so.11",
            "nvidia/cufft/include/interleaved.h",  # not a lib*.so* — never loaded
        ],
    )
    loaded = patch_loader(monkeypatch, lambda _path: None)

    assert worker.preload_nvidia_libraries(purelib) is True
    assert sorted(loaded) == libs


def test_preload_skips_broken_library_and_probe_reflects_it(
    tmp_path, monkeypatch, caplog
):
    purelib, libs = wheel_tree(
        tmp_path,
        ["nvidia/cublas/lib/libcublas.so.12", "nvidia/cudnn/lib/libcudnn.so.9"],
    )

    def broken(_path):
        if "libcudnn" in _path:
            raise OSError("libcudnn.so.9: cannot open shared object file")

    calls = patch_loader(monkeypatch, broken)

    with caplog.at_level(logging.DEBUG):
        assert worker.preload_nvidia_libraries(purelib) is False
    assert "preload skipped" in caplog.text and "libcudnn" in caplog.text
    # One skip is retried on the next pass before the fixed point is reached…
    assert calls.count(libs[1]) == 2


def test_preload_retries_after_dependency_arrives(tmp_path, monkeypatch):
    """The reason for fixed-point passes: cublas needs cublasLt loaded first."""
    purelib, libs = wheel_tree(
        tmp_path,
        [
            "nvidia/cublas/lib/libcublas.so.12",
            "nvidia/cublas/lib/libcublasLt.so.12",
            "nvidia/cudnn/lib/libcudnn.so.9",
        ],
    )
    attempts = []

    def needs_lt(path):
        attempts.append(path)
        if path.endswith("libcublas.so.12") and not any(
            a.endswith("libcublasLt.so.12") for a in attempts[:-1]
        ):
            raise OSError("libcublasLt.so.12: cannot open shared object file")

    patch_loader(monkeypatch, needs_lt)

    assert worker.preload_nvidia_libraries(purelib) is True
    cublas = next(lib for lib in libs if lib.endswith("libcublas.so.12"))
    assert attempts.count(cublas) == 2  # failed once, succeeded on the retry


def test_preload_terminates_when_nothing_loads(tmp_path, monkeypatch):
    purelib, libs = wheel_tree(
        tmp_path,
        ["nvidia/cudnn/lib/libcudnn.so.9", "nvidia/cublas/lib/libcublas.so.12"],
    )

    def unloadable(_path):
        raise OSError("nope")

    calls = patch_loader(monkeypatch, unloadable)

    assert worker.preload_nvidia_libraries(purelib) is False
    # A pass that loads nothing new ends the loop — no infinite retry.
    assert sorted(calls) == libs


def test_preload_purelib_comes_from_sysconfig(monkeypatch, tmp_path):
    """purelib must come from sysconfig, never __file__ parents (src-layout)."""
    purelib, _libs = wheel_tree(
        tmp_path,
        ["nvidia/cudnn/lib/libcudnn.so.9", "nvidia/cublas/lib/libcublas.so.12"],
    )
    monkeypatch.setattr(worker.sysconfig, "get_paths", lambda: {"purelib": purelib})
    loaded = patch_loader(monkeypatch, lambda _path: None)

    assert worker.preload_nvidia_libraries() is True
    assert loaded and loaded[0].startswith(purelib)


def test_ready_line_carries_provider():
    write = Mock()
    worker.announce_ready(write, "CPUExecutionProvider")
    write.assert_called_once_with(b"ready provider=CPUExecutionProvider\n")


def test_import_safety_without_kokoro_onnx(monkeypatch):
    """The module imports cleanly with no kokoro_onnx anywhere (py3.14 venvs)."""
    monkeypatch.delitem(sys.modules, "kokoro_onnx", raising=False)
    reloaded = importlib.reload(worker)
    assert reloaded.SPEAK_SAMPLE_RATE == 24000


def test_lazy_onnxruntime_wrappers_use_the_injected_module(monkeypatch):
    """available_providers/build_session resolve onnxruntime lazily, at call time.

    The fake rides in via sys.modules (the kokoro_onnx trick). Top-level
    laziness itself is pinned by the reload test above: with the real wheel
    also installed in this venv, only that absence-at-import scenario proves
    the import is not module-level.
    """

    def fake_session(model_path, providers=None):
        return (model_path, providers)

    runtime = types.ModuleType("onnxruntime")
    runtime.get_available_providers = lambda: ["FakeExecutionProvider"]
    runtime.InferenceSession = fake_session
    monkeypatch.setitem(sys.modules, "onnxruntime", runtime)

    assert worker.available_providers() == ["FakeExecutionProvider"]
    assert worker.build_session("m.onnx", ["FakeExecutionProvider"]) == (
        "m.onnx",
        ["FakeExecutionProvider"],
    )


def test_main_speaks_each_line_and_exits_cleanly(monkeypatch, speak_env):
    speak_env.state.audio = lambda _text: LOUD
    code, ready, pcm = drive_worker(monkeypatch, "Done.\n")

    assert code == 0
    assert ready == b"ready provider=CPUExecutionProvider\n"
    assert speak_env.state.calls == [
        (worker.WARMUP_TEXT, "af_heart", 1.0, "en-us"),
        ("Done.", "af_heart", 1.0, "en-us"),
    ]
    # stdout carries exactly the phrase's PCM — the warmup audio is discarded.
    assert pcm == worker.to_s16le(LOUD)


def test_main_skips_blank_lines(monkeypatch, speak_env):
    speak_env.state.audio = lambda _text: LOUD
    code, _ready, pcm = drive_worker(monkeypatch, "  \n\nDone.\n")

    assert code == 0
    assert [call[0] for call in speak_env.state.calls] == [worker.WARMUP_TEXT, "Done."]
    assert pcm == worker.to_s16le(LOUD)


def test_main_eof_exits_cleanly_without_output(monkeypatch, speak_env):
    speak_env.state.audio = lambda _text: LOUD
    code, ready, pcm = drive_worker(monkeypatch, "")

    assert code == 0
    assert ready == b"ready provider=CPUExecutionProvider\n"
    assert pcm == b""


def test_main_silent_warmup_exits_before_ready(monkeypatch, speak_env):
    code, ready, pcm = drive_worker(monkeypatch, "Done.\n")

    assert code == 1
    assert ready == b""  # never announced: the parent counts this as not-ready
    assert pcm == b""


def test_main_wrong_sample_rate_exits_nonzero_without_output(monkeypatch, speak_env):
    """A 22050 export must never reach the 24 kHz player as wrong-pitch PCM."""
    speak_env.state.audio = lambda _text: LOUD
    speak_env.state.rate = 22050
    code, ready, pcm = drive_worker(monkeypatch, "Done.\n")

    # The warmup is the first synthesis through the shared path, so a foreign
    # rate dies exactly like a silent warmup: before ready, nothing on stdout.
    assert code == 1
    assert ready == b""
    assert pcm == b""


def test_main_silent_synthesis_exits_nonzero_without_output(monkeypatch, speak_env):
    speak_env.state.audio = lambda text: (
        np.zeros(2400, dtype=np.float32) if text == "Done." else LOUD
    )
    code, ready, pcm = drive_worker(monkeypatch, "Done.\n")

    assert code == 1
    assert ready == b"ready provider=CPUExecutionProvider\n"
    assert pcm == b""  # silence feeds the strike path, never the player


def test_main_engine_failure_mid_loop_exits_nonzero(monkeypatch, speak_env, caplog):
    """An engine error after `ready` exits the loop — it never limps on.

    The pipeline's strike contract depends on the worker dying (not continuing
    to the next line) once the engine is broken mid-session.
    """

    def boom(text):
        if text == "Done.":
            raise RuntimeError("CUDA broke mid-phrase")
        return LOUD

    speak_env.state.audio = boom
    with caplog.at_level(logging.ERROR):
        code, ready, pcm = drive_worker(monkeypatch, "Done.\n")

    assert code == 1
    assert ready == b"ready provider=CPUExecutionProvider\n"  # warmup had succeeded
    assert pcm == b""
    assert "synthesis failed" in caplog.text
    # logger.exception's traceback is the --verbose record of WHY it died.
    assert "CUDA broke mid-phrase" in caplog.text
