"""Tests for the Kokoro provisioning engine (`core.provision`)."""

import fcntl
import hashlib
import importlib.resources
import importlib.util
import io
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from easyspeak.core import provision

MODEL_BYTES = b"fake kokoro model bytes"
VOICES_BYTES = b"fake kokoro voices bytes"

# pytest runs the suite as the invoking user in CI and dev, but a stray root
# run (container) would defeat every chmod-based unwritability test below.
needs_non_root = pytest.mark.skipif(
    os.geteuid() == 0, reason="root ignores file modes, so chmod proves nothing"
)


class FakeResponse:
    """A urlopen() response: pre-split chunks, then EOF."""

    def __init__(self, chunks):
        self.chunks = list(chunks)

    def read(self, size=-1):
        if not self.chunks:
            return b""
        return self.chunks.pop(0)[:size]

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class RecordingStdin:
    """A stdin stand-in that stays readable after close (`_reap` closes it)."""

    def __init__(self):
        self.data = bytearray()
        self.closed = False

    def write(self, chunk):
        self.data += chunk

    def flush(self):
        pass

    def close(self):
        self.closed = True


class BrokenStdin:
    """A stdin whose write fails — a worker that died mid-check."""

    def write(self, chunk):
        raise BrokenPipeError("worker is gone")

    def flush(self):
        pass

    def close(self):
        pass


class FakeWorker:
    """A subprocess.Popen stand-in speaking the kokoro_worker fd protocol.

    Writes its ready line to the very descriptor the parent handed over (a
    real child inherits its own copy; the fake just writes the parent's), and
    answers the verify phrase with PCM bytes pre-buffered in a real pipe, so
    the provisioner's select()-based reads run against true fd semantics.
    """

    def __init__(
        self,
        ready_line=b"ready provider=CPUExecutionProvider\n",
        pcm=b"\x01\x00" * 480,
        stdin=None,
        stderr_message=None,
    ):
        self.ready_line = ready_line
        self.pcm = pcm
        self.stdin = stdin
        self.stderr_message = stderr_message
        self.process = None
        self.argv = None

    def __call__(self, argv, **kwargs):
        self.argv = argv
        fd = int(argv[argv.index("--ready-fd") + 1])
        if self.ready_line is not None:
            os.write(fd, self.ready_line)
        if self.stderr_message and "stderr" in kwargs:
            # bytes pass through raw, so tests can write invalid UTF-8
            payload = (
                self.stderr_message
                if isinstance(self.stderr_message, bytes)
                else self.stderr_message.encode()
            )
            os.write(kwargs["stderr"].fileno(), payload)
        read_fd, write_fd = os.pipe()
        os.write(write_fd, self.pcm)
        os.close(write_fd)
        self.process = Mock(
            stdin=self.stdin or RecordingStdin(), stdout=os.fdopen(read_fd, "rb")
        )
        self.process.wait.return_value = 0
        return self.process


@pytest.fixture
def kokoro_dirs(tmp_path, monkeypatch):
    """Point every config path at a fresh tmp tree, created for writes."""
    directory = tmp_path / "models" / "kokoro"
    directory.mkdir(parents=True)
    monkeypatch.setattr(provision.config, "KOKORO_DIR", directory)
    monkeypatch.setattr(
        provision.config, "KOKORO_MODEL", directory / "kokoro-v1.0.onnx"
    )
    monkeypatch.setattr(
        provision.config, "KOKORO_VOICES", directory / "voices-v1.0.bin"
    )
    return directory


@pytest.fixture
def pins():
    """A pins table in the packaged copy's exact shape, digests of the fakes."""
    return {
        "version": "1.0.0",
        "model_repo": "onnx-community/Kokoro-82M-v1.0-ONNX",
        "model_revision": "1939ad2",
        "model_path": "onnx/model.onnx",
        "voices_repo": "thewh1teagle/kokoro-onnx",
        "voices_tag": "model-files-v1.1",
        "voices_asset": "voices-v1.0.bin",
        "files": {
            "kokoro-v1.0.onnx": hashlib.sha256(MODEL_BYTES).hexdigest(),
            "voices-v1.0.bin": hashlib.sha256(VOICES_BYTES).hexdigest(),
        },
    }


@pytest.fixture
def seeded_models(kokoro_dirs):
    """Model files present on disk, so verify() gets past its presence gate."""
    (kokoro_dirs / "kokoro-v1.0.onnx").write_bytes(MODEL_BYTES)
    (kokoro_dirs / "voices-v1.0.bin").write_bytes(VOICES_BYTES)
    return kokoro_dirs


class TestPreflight:
    """Preflight refuses impossible runs before anything downloads."""

    @pytest.fixture(autouse=True)
    def _py313(self, monkeypatch):
        """Pin the interpreter below the 3.14 refusal.

        The version check runs first, so unpatched these tests would all die
        with the version error on the 3.14 matrix leg instead of exercising
        what they test. The refusal test below overrides this with its own
        (3, 14) patch — monkeypatch restores in reverse order, so that one
        wins for its test and this one still cleans up.
        """
        monkeypatch.setattr(sys, "version_info", (3, 13, 0))

    def test_rejects_python_314_and_names_the_limit(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "version_info", (3, 14, 0))
        with pytest.raises(provision.ProvisionError, match=r"3\.14"):
            provision.preflight(tmp_path)

    @needs_non_root
    def test_names_sudo_for_an_unwritable_venv(self, tmp_path):
        readonly = tmp_path / "venv"
        readonly.mkdir()
        readonly.chmod(0o555)
        try:
            with pytest.raises(provision.ProvisionError, match="sudo"):
                provision.preflight(tmp_path / "kokoro", prefix=str(readonly))
        finally:
            readonly.chmod(0o755)  # let tmp_path cleanup work

    @needs_non_root
    def test_names_the_models_dir_escape_hatch(self, tmp_path):
        readonly = tmp_path / "models"
        readonly.mkdir()
        readonly.chmod(0o555)
        try:
            with pytest.raises(provision.ProvisionError, match="EASYSPEAK_MODELS_DIR"):
                provision.preflight(readonly / "kokoro", prefix=str(tmp_path))
        finally:
            readonly.chmod(0o755)

    def test_writable_paths_pass_and_create_the_model_dir(self, tmp_path):
        provision.preflight(tmp_path / "kokoro", prefix=str(tmp_path))
        assert (tmp_path / "kokoro").is_dir()


class TestFlavor:
    @pytest.mark.parametrize(
        ("nvidia_smi", "expected"),
        [("/usr/bin/nvidia-smi", "gpu"), (None, "cpu")],
    )
    def test_nvidia_smi_on_path_decides(self, monkeypatch, nvidia_smi, expected):
        monkeypatch.setattr(
            provision.shutil,
            "which",
            lambda name: nvidia_smi if name == "nvidia-smi" else None,
        )
        assert provision.detect_flavor() == expected


class TestWheelSpecs:
    def test_cpu_specs_exact_and_every_spec_major_bounded(self):
        assert provision.CPU_WHEEL_SPECS == [
            "kokoro-onnx>=0.6.1,<0.7 ; python_version < '3.14'"
        ]
        for spec in provision.CPU_WHEEL_SPECS + provision.GPU_WHEEL_SPECS:
            assert "<" in spec

    def test_gpu_specs_carry_the_full_swap_set(self):
        names = {spec.split(">")[0] for spec in provision.GPU_WHEEL_SPECS}
        assert names == {
            "kokoro-onnx[gpu]",
            "onnxruntime-gpu",
            "nvidia-cudnn-cu12",
            "nvidia-cublas-cu12",
            "nvidia-cuda-runtime-cu12",
            "nvidia-cufft-cu12",
        }


class TestInstall:
    @pytest.fixture
    def run_calls(self, monkeypatch):
        """Record every installer subprocess; always succeed."""
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr(provision.subprocess, "run", fake_run)
        return calls

    def test_uv_door_argv_is_exact(self, monkeypatch, run_calls):
        monkeypatch.setattr(
            provision.shutil,
            "which",
            lambda name: "/usr/bin/uv" if name == "uv" else None,
        )
        provision.install("cpu")
        assert run_calls == [
            [
                "/usr/bin/uv",
                "pip",
                "install",
                "--python",
                sys.executable,
                *provision.CPU_WHEEL_SPECS,
            ]
        ]

    def test_gpu_swap_uninstalls_onnxruntime_first(self, monkeypatch, run_calls):
        monkeypatch.setattr(
            provision.shutil,
            "which",
            lambda name: "/usr/bin/uv" if name == "uv" else None,
        )
        provision.install("gpu")
        assert "onnxruntime" in run_calls[0]
        assert run_calls[1][1:] == [
            "pip",
            "install",
            "--python",
            sys.executable,
            *provision.GPU_WHEEL_SPECS,
        ]

    def test_ensurepip_door_bootstraps_pip_first(self, monkeypatch, run_calls):
        monkeypatch.setattr(provision.shutil, "which", lambda name: None)
        provision.install("cpu")
        assert run_calls == [
            [sys.executable, "-m", "ensurepip", "--upgrade"],
            [sys.executable, "-m", "pip", "install", *provision.CPU_WHEEL_SPECS],
        ]

    def test_gpu_swap_uninstalls_on_the_pip_door_too(self, monkeypatch, run_calls):
        monkeypatch.setattr(provision.shutil, "which", lambda name: None)
        provision.install("gpu")
        assert [cmd[1:3] for cmd in run_calls] == [
            ["-m", "ensurepip"],
            ["-m", "pip"],  # the swap: uninstall before the GPU install lands
            ["-m", "pip"],
        ]
        assert "onnxruntime" in run_calls[1]
        assert run_calls[2][4:] == list(provision.GPU_WHEEL_SPECS)

    def test_no_installer_names_the_exact_manual_command(self, monkeypatch):
        monkeypatch.setattr(provision.shutil, "which", lambda name: None)
        monkeypatch.setattr(
            provision.subprocess,
            "run",
            lambda cmd, **kwargs: SimpleNamespace(
                returncode=1, stderr="ensurepip is unavailable", stdout=""
            ),
        )
        with pytest.raises(provision.ProvisionError, match="uv pip install") as excinfo:
            provision.install("gpu")
        assert sys.executable in str(excinfo.value)
        assert "onnxruntime-gpu" in str(excinfo.value)

    def test_failed_install_surfaces_the_installer_output(self, monkeypatch):
        monkeypatch.setattr(
            provision.shutil,
            "which",
            lambda name: "/usr/bin/uv" if name == "uv" else None,
        )

        def failing_run(cmd, **kwargs):
            raise subprocess.CalledProcessError(1, cmd, stderr="resolver exploded")

        monkeypatch.setattr(provision.subprocess, "run", failing_run)
        with pytest.raises(provision.ProvisionError, match="resolver exploded"):
            provision.install("cpu")

    def test_footprint_disclosed_before_any_install(
        self, monkeypatch, run_calls, caplog
    ):
        monkeypatch.setattr(provision.shutil, "which", lambda name: None)
        with caplog.at_level(logging.INFO, logger="easyspeak.core.provision"):
            provision.install("gpu")
        assert any("~2 GB of wheels" in record.message for record in caplog.records)


class TestImportability:
    def test_still_unimportable_after_the_wheel_step(self, monkeypatch):
        real_find_spec = importlib.util.find_spec

        def fake_find_spec(name, *args):
            return None if name == "kokoro_onnx" else real_find_spec(name, *args)

        monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
        with pytest.raises(provision.ProvisionError, match="importable"):
            provision.require_importable()


class TestPins:
    def test_read_through_importlib_resources(self, monkeypatch):
        body = (
            b'[tts.kokoro]\nversion = "1.0.0"\n\n[tts.kokoro.files]\n'
            b'"kokoro-v1.0.onnx" = "abc"\n'
        )
        requested = []

        class FakeTraversable:
            def joinpath(self, name):
                requested.append(name)
                return self

            def open(self, mode="rb"):
                return io.BytesIO(body)

        def fake_files(package):
            requested.append(package)
            return FakeTraversable()

        monkeypatch.setattr(importlib.resources, "files", fake_files)
        assert provision.load_pins()["files"] == {"kokoro-v1.0.onnx": "abc"}
        assert requested == ["easyspeak.core", "runtime_pins.toml"]

    def test_the_real_packaged_copy_holds_the_contract(self):
        """The shipped TOML: tts-only family, bare lowercase hex digests."""
        if sys.version_info < (3, 11):
            import tomli as tomllib
        else:
            import tomllib

        source = importlib.resources.files("easyspeak.core").joinpath(
            "runtime_pins.toml"
        )
        data = tomllib.loads(source.read_text(encoding="utf-8"))
        assert set(data) == {"tts"}  # the runtime copy carries only the tts family
        kokoro = data["tts"]["kokoro"]
        assert kokoro["model_repo"] == "onnx-community/Kokoro-82M-v1.0-ONNX"
        assert {"kokoro-v1.0.onnx", "voices-v1.0.bin"} <= set(kokoro["files"])
        for digest in kokoro["files"].values():
            assert digest == digest.lower() and len(digest) == 64
            assert not digest.startswith("sha256:")


class TestDownloads:
    def test_happy_path_renames_part_into_shipped_names(
        self, kokoro_dirs, pins, monkeypatch
    ):
        responses = iter(
            [
                FakeResponse([MODEL_BYTES[:5], MODEL_BYTES[5:]]),
                FakeResponse([VOICES_BYTES]),
            ]
        )
        urls = []
        timeouts = []

        def fake_urlopen(url, *args, **kwargs):
            urls.append(url)
            timeouts.append(kwargs.get("timeout"))
            return next(responses)

        monkeypatch.setattr(provision, "urlopen", fake_urlopen)
        provision.download_models(pins)
        assert (kokoro_dirs / "kokoro-v1.0.onnx").read_bytes() == MODEL_BYTES
        assert (kokoro_dirs / "voices-v1.0.bin").read_bytes() == VOICES_BYTES
        assert not list(kokoro_dirs.glob("*.part"))
        assert timeouts == [provision.DOWNLOAD_TIMEOUT] * 2  # a hung fetch gives up
        assert urls == [
            (
                "https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX"
                "/resolve/1939ad2/onnx/model.onnx"
            ),
            (
                "https://github.com/thewh1teagle/kokoro-onnx/releases/download"
                "/model-files-v1.1/voices-v1.0.bin"
            ),
        ]

    def test_checksum_mismatch_removes_the_partial(
        self, kokoro_dirs, pins, monkeypatch
    ):
        pins["files"]["kokoro-v1.0.onnx"] = "0" * 64
        monkeypatch.setattr(
            provision, "urlopen", lambda url, *a, **k: FakeResponse([MODEL_BYTES])
        )
        with pytest.raises(provision.ProvisionError, match="checksum"):
            provision.download_models(pins)
        assert not (kokoro_dirs / "kokoro-v1.0.onnx").exists()
        assert not list(kokoro_dirs.glob("*.part"))

    def test_mid_body_error_removes_the_partial(self, kokoro_dirs, pins, monkeypatch):
        class DyingResponse(FakeResponse):
            def read(self, size=-1):
                if self.chunks:
                    return self.chunks.pop(0)
                raise OSError("connection reset by peer")

        monkeypatch.setattr(
            provision, "urlopen", lambda url, *a, **k: DyingResponse([MODEL_BYTES[:5]])
        )
        with pytest.raises(provision.ProvisionError, match="connection reset"):
            provision.download_models(pins)
        assert not list(kokoro_dirs.glob("*"))

    def test_keyboard_interrupt_removes_the_partial(
        self, kokoro_dirs, pins, monkeypatch
    ):
        class InterruptedResponse(FakeResponse):
            def read(self, size=-1):
                if self.chunks:
                    return self.chunks.pop(0)
                raise KeyboardInterrupt

        monkeypatch.setattr(
            provision,
            "urlopen",
            lambda url, *a, **k: InterruptedResponse([MODEL_BYTES[:5]]),
        )
        with pytest.raises(KeyboardInterrupt):
            provision.download_models(pins)
        assert not list(kokoro_dirs.glob("*"))

    def test_current_files_are_kept_and_not_refetched(
        self, kokoro_dirs, pins, monkeypatch
    ):
        (kokoro_dirs / "kokoro-v1.0.onnx").write_bytes(MODEL_BYTES)
        (kokoro_dirs / "voices-v1.0.bin").write_bytes(VOICES_BYTES)

        def refuse(url, *args, **kwargs):
            msg = f"should not have downloaded {url}"
            raise AssertionError(msg)

        monkeypatch.setattr(provision, "urlopen", refuse)
        provision.download_models(pins)  # nothing raised, nothing fetched
        assert (kokoro_dirs / "kokoro-v1.0.onnx").read_bytes() == MODEL_BYTES


class TestVerify:
    def test_verified_when_audio_and_provider_match_the_flavor(
        self, seeded_models, monkeypatch
    ):
        worker = FakeWorker(ready_line=b"ready provider=CUDAExecutionProvider\n")
        monkeypatch.setattr(provision.subprocess, "Popen", worker)
        assert provision.verify("gpu") == (True, "CUDAExecutionProvider")
        assert worker.process.stdin.data == b"Done.\n"
        assert worker.process.stdin.closed  # closing stdin is the exit sign

    def test_gpu_flavor_landing_on_cpu_warns_loud_and_fails(
        self, seeded_models, monkeypatch, caplog
    ):
        monkeypatch.setattr(provision.subprocess, "Popen", FakeWorker())
        assert provision.verify("gpu") == (False, "CPUExecutionProvider")
        assert any("troubleshooting" in record.message for record in caplog.records)

    def test_silent_synthesis_counts_as_failure(self, seeded_models, monkeypatch):
        monkeypatch.setattr(provision.subprocess, "Popen", FakeWorker(pcm=b""))
        assert provision.verify("cpu") == (False, "CPUExecutionProvider")

    def test_worker_that_never_announces_counts_as_failure(
        self, seeded_models, monkeypatch
    ):
        monkeypatch.setattr(provision.subprocess, "Popen", FakeWorker(ready_line=None))
        assert provision.verify("cpu") == (False, None)

    def test_missing_models_skip_before_any_spawn(self, kokoro_dirs, monkeypatch):
        def refuse(*args, **kwargs):
            raise AssertionError("must not spawn without the model files")

        monkeypatch.setattr(provision.subprocess, "Popen", refuse)
        assert provision.verify("cpu") == (False, None)

    def test_spawn_failure_closes_both_pipe_ends(self, seeded_models, monkeypatch):
        """The exact leak `test_speech`'s spawn-failure test guards against."""
        closed = []
        monkeypatch.setattr(provision.os, "pipe", lambda: (7, 8))
        monkeypatch.setattr(provision.os, "close", closed.append)

        def refuse(argv, **kwargs):
            raise OSError("spawn failed")

        monkeypatch.setattr(provision.subprocess, "Popen", refuse)
        assert provision.verify("cpu") == (False, None)
        assert closed == [7, 8]  # the child never got its copies; we close ours

    def test_a_worker_dying_mid_check_reports_no_audio(
        self, seeded_models, monkeypatch
    ):
        monkeypatch.setattr(
            provision.subprocess, "Popen", FakeWorker(stdin=BrokenStdin())
        )
        assert provision.verify("cpu") == (False, "CPUExecutionProvider")

    def test_worker_stderr_reaches_the_failure_warning(
        self, seeded_models, monkeypatch, caplog
    ):
        worker = FakeWorker(
            ready_line=None, stderr_message="CUDA driver version is insufficient"
        )
        monkeypatch.setattr(provision.subprocess, "Popen", worker)
        with caplog.at_level(logging.WARNING, logger="easyspeak.core.provision"):
            assert provision.verify("cpu") == (False, None)
        assert any(
            "CUDA driver version is insufficient" in record.message
            for record in caplog.records
        )

    def test_reap_kills_a_worker_past_its_shutdown_grace(self):
        proc = Mock()
        proc.wait.side_effect = subprocess.TimeoutExpired(cmd="worker", timeout=1)
        provision._reap(proc)
        proc.kill.assert_called_once_with()


class TestState:
    def test_write_is_an_atomic_replace(self, tmp_path, monkeypatch):
        real_replace = os.replace
        replaces = []

        def recording_replace(src, dst):
            replaces.append((src, dst))
            real_replace(src, dst)

        monkeypatch.setattr(provision.os, "replace", recording_replace)
        provision.write_state(tmp_path, {"flavor": "cpu"})
        assert json.loads((tmp_path / "provisioned.json").read_text()) == {
            "flavor": "cpu"
        }
        assert replaces == [
            (tmp_path / "provisioned.json.tmp", tmp_path / "provisioned.json")
        ]
        assert not list(tmp_path.glob("*.tmp"))

    def test_read_is_tolerant_of_absent_corrupt_and_foreign(self, tmp_path):
        assert provision.read_state(tmp_path) is None  # absent
        (tmp_path / "provisioned.json").write_text("{corrupt")
        assert provision.read_state(tmp_path) is None  # corrupt JSON
        (tmp_path / "provisioned.json").write_text("[1, 2]")
        assert provision.read_state(tmp_path) is None  # JSON, but not an object
        (tmp_path / "provisioned.json").write_text('{"flavor": "cpu"}')
        assert provision.read_state(tmp_path) == {"flavor": "cpu"}

    def test_record_fields_round_trip(self, tmp_path):
        record = {
            "flavor": "gpu",
            "wheels": ["kokoro-onnx[gpu]"],
            "verified_at": "2026-10-18T12:00:00+00:00",
            "provider": "CUDAExecutionProvider",
            "verified": True,
        }
        provision.write_state(tmp_path, record)
        assert provision.read_state(tmp_path) == record

    @needs_non_root
    def test_an_unwritable_dir_is_a_refusal_not_a_traceback(self, tmp_path):
        readonly = tmp_path / "locked"
        readonly.mkdir()
        readonly.chmod(0o555)
        try:
            with pytest.raises(provision.ProvisionError, match="could not write"):
                provision.write_state(readonly, {"flavor": "cpu"})
        finally:
            readonly.chmod(0o755)  # let tmp_path cleanup work


class TestSatisfaction:
    def test_gpu_needs_verified_and_the_cuda_provider(self):
        good = {"flavor": "gpu", "verified": True, "provider": "CUDAExecutionProvider"}
        assert provision.is_satisfied(good, "gpu")
        assert not provision.is_satisfied(
            {**good, "provider": "CPUExecutionProvider"}, "gpu"
        )
        assert not provision.is_satisfied({**good, "verified": False}, "gpu")
        assert not provision.is_satisfied(None, "gpu")

    def test_a_recorded_flavor_change_is_an_upgrade_not_a_skip(self):
        cpu_state = {
            "flavor": "cpu",
            "verified": True,
            "provider": "CPUExecutionProvider",
        }
        assert provision.is_satisfied(cpu_state, "cpu")
        assert not provision.is_satisfied(cpu_state, "gpu")


class TestSummaryLine:
    def test_exact_machine_format(self, capsys):
        provision.summarize("gpu", "CPUExecutionProvider", verified=False)
        provision.summarize("cpu", "CPUExecutionProvider", verified=True)
        provision.summarize("cpu", None, verified=False)  # engine never came up
        assert capsys.readouterr().out == (
            "provision: flavor=gpu provider=CPUExecutionProvider verified=no\n"
            "provision: flavor=cpu provider=CPUExecutionProvider verified=yes\n"
            "provision: flavor=cpu provider=none verified=no\n"
        )


class TestLock:
    def test_lock_file_created_and_flock_taken(self, tmp_path, monkeypatch):
        real_flock = fcntl.flock
        locks = []

        def recording_flock(fd, operation):
            locks.append((fd, operation))
            real_flock(fd, operation)

        monkeypatch.setattr(provision.fcntl, "flock", recording_flock)
        with provision.provision_lock(tmp_path):
            assert (tmp_path / ".provision.lock").is_file()
        assert locks and locks[0][1] == fcntl.LOCK_EX
        # The file stays: it is the anchor the next run flocks.
        assert (tmp_path / ".provision.lock").is_file()


def fake_happy_world(monkeypatch, kokoro_dirs, pins, worker=None):
    """Fake every external door; a CPU flavor that installs, downloads, verifies."""
    world = SimpleNamespace(
        run_calls=[],
        worker=worker or FakeWorker(b"ready provider=CPUExecutionProvider\n"),
    )
    monkeypatch.setattr(sys, "version_info", (3, 13, 0))  # preflight must pass
    monkeypatch.setattr(
        provision.shutil, "which", lambda name: None
    )  # no uv, no nvidia-smi
    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name, *args):
        return object() if name == "kokoro_onnx" else real_find_spec(name, *args)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)

    def fake_run(cmd, **kwargs):
        world.run_calls.append(cmd)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(provision.subprocess, "run", fake_run)
    monkeypatch.setattr(provision.subprocess, "Popen", world.worker)
    monkeypatch.setattr(provision, "load_pins", lambda: pins)
    responses = iter([FakeResponse([MODEL_BYTES]), FakeResponse([VOICES_BYTES])])
    monkeypatch.setattr(provision, "urlopen", lambda url, *a, **k: next(responses))
    return world


class TestProvisionKokoro:
    def test_a_preflight_refusal_prints_no_machine_line(self, monkeypatch, capsys):
        """A refused run never engaged a flavor, so stdout stays empty.

        This is the one deliberate hole in the machine-line guarantee (the
        line names a flavor that was never installed); pinning it keeps the
        CLI's exit contract from accidentally printing a misleading line.
        """

        def refuse(*args, **kwargs):
            msg = "Kokoro needs Python < 3.14"
            raise provision.ProvisionError(msg)

        monkeypatch.setattr(provision, "preflight", refuse)
        assert provision.provision_kokoro() == 1
        assert capsys.readouterr().out == ""

    def test_a_full_verified_run_leaves_state_and_the_machine_line(
        self, kokoro_dirs, pins, monkeypatch, capsys, caplog
    ):
        world = fake_happy_world(monkeypatch, kokoro_dirs, pins)
        with caplog.at_level(logging.INFO, logger="easyspeak.core.provision"):
            assert provision.provision_kokoro() == 0
        record = json.loads((kokoro_dirs / "provisioned.json").read_text())
        assert record["flavor"] == "cpu"
        assert record["verified"] is True
        assert record["provider"] == "CPUExecutionProvider"
        assert record["wheels"] == provision.CPU_WHEEL_SPECS
        datetime.fromisoformat(record["verified_at"])  # an ISO date
        assert capsys.readouterr().out == (
            "provision: flavor=cpu provider=CPUExecutionProvider verified=yes\n"
        )
        assert any("few MB" in record.message for record in caplog.records)
        # No uv on PATH, so this run went through the pip door: bootstrap first.
        assert world.run_calls[0] == [sys.executable, "-m", "ensurepip", "--upgrade"]

    def test_a_satisfied_run_skips_every_door(self, kokoro_dirs, monkeypatch, capsys):
        monkeypatch.setattr(sys, "version_info", (3, 13, 0))
        monkeypatch.setattr(provision.shutil, "which", lambda name: None)
        provision.write_state(
            kokoro_dirs,
            {
                "flavor": "cpu",
                "verified": True,
                "provider": "CPUExecutionProvider",
                "wheels": [],
                "verified_at": "2026-10-18T00:00:00+00:00",
            },
        )

        def refuse(*args, **kwargs):
            raise AssertionError("a satisfied run must touch nothing")

        monkeypatch.setattr(provision.subprocess, "run", refuse)
        monkeypatch.setattr(provision.subprocess, "Popen", refuse)
        monkeypatch.setattr(provision, "urlopen", refuse)
        assert provision.provision_kokoro() == 0
        assert capsys.readouterr().out == (
            "provision: flavor=cpu provider=CPUExecutionProvider verified=yes\n"
        )

    def test_an_install_failure_reports_verified_no(
        self, kokoro_dirs, pins, monkeypatch, capsys, caplog
    ):
        monkeypatch.setattr(sys, "version_info", (3, 13, 0))
        monkeypatch.setattr(provision.shutil, "which", lambda name: None)
        monkeypatch.setattr(
            provision.subprocess,
            "run",
            lambda cmd, **kwargs: SimpleNamespace(
                returncode=1, stderr="ensurepip is unavailable", stdout=""
            ),
        )
        monkeypatch.setattr(provision, "load_pins", lambda: pins)
        with caplog.at_level(logging.WARNING, logger="easyspeak.core.provision"):
            assert provision.provision_kokoro() == 1
        # The ensurepip fall-through is never silent: its captured output is
        # logged before the run reports verified=no.
        assert any(
            "ensurepip is unavailable" in record.message for record in caplog.records
        )
        record = json.loads((kokoro_dirs / "provisioned.json").read_text())
        assert record["verified"] is False
        assert capsys.readouterr().out.endswith(
            "provision: flavor=cpu provider=none verified=no\n"
        )

    def test_non_utf8_worker_stderr_still_reaches_the_machine_line(
        self, kokoro_dirs, pins, monkeypatch, capsys, caplog
    ):
        """A raw non-UTF-8 byte on the worker's stderr must not escape.

        The child writes raw bytes to the fd and the failure handler reads
        them back as text, so strict decoding would raise inside the very
        code paths meant to report the failure — past provision_kokoro's
        ProvisionError net, costing the machine line.
        """
        worker = FakeWorker(
            ready_line=None, stderr_message=b"driver says: \xff\xfe broken"
        )
        fake_happy_world(monkeypatch, kokoro_dirs, pins, worker=worker)
        with caplog.at_level(logging.WARNING, logger="easyspeak.core.provision"):
            assert provision.provision_kokoro() == 1
        assert any("�" in record.message for record in caplog.records)
        assert capsys.readouterr().out.endswith(
            "provision: flavor=cpu provider=none verified=no\n"
        )

    def test_a_state_write_failure_still_prints_the_machine_line(
        self, kokoro_dirs, pins, monkeypatch, capsys, caplog
    ):
        world = fake_happy_world(monkeypatch, kokoro_dirs, pins)

        def refuse(*args, **kwargs):
            msg = "could not write the record"
            raise provision.ProvisionError(msg)

        monkeypatch.setattr(provision, "write_state", refuse)
        with caplog.at_level(logging.WARNING, logger="easyspeak.core.provision"):
            # The engine verified in place, so the exit code stays truthful
            # about the engine; the unpersisted record is the logged refusal.
            assert provision.provision_kokoro() == 0
        assert any(
            "could not write the record" in record.message for record in caplog.records
        )
        assert capsys.readouterr().out.endswith(
            "provision: flavor=cpu provider=CPUExecutionProvider verified=yes\n"
        )
        assert world.run_calls  # the doors ran; only the record was lost
