"""The `easyspeak --provision-kokoro` engine: wheels, models, verification.

One run takes a machine from "no Kokoro" to "verified talking" in five stages
(spec §4.2-4.4): preflight, wheel install, checksum-verified model downloads,
one real synthesis through the daemon's own worker, and the `provisioned.json`
record plus the machine-parseable summary line.

Nothing here may import `kokoro_onnx` or `onnxruntime` at module scope: on
Python 3.14 the wheels cannot install, and the dev suite runs on 3.14, so an
import-time dependency would break every test module that merely imports this
one (the worker keeps the same rule). The only real engine import happens in
the spawned worker process, never in this one.
"""

import contextlib
import fcntl
import hashlib
import importlib.resources
import importlib.util
import json
import logging
import os
import select
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen

from . import config

logger = logging.getLogger(__name__)

# One wheel list per flavor, every spec major-bounded like every other pin in
# this project (spec §4.2.3). The `python_version` markers keep even a manual
# install honest on 3.14, where kokoro-onnx publishes no wheels; preflight()
# rejects that case before we get here.
CPU_WHEEL_SPECS = ["kokoro-onnx>=0.6.1,<0.7 ; python_version < '3.14'"]
GPU_WHEEL_SPECS = [
    "kokoro-onnx[gpu]>=0.6.1,<0.7 ; python_version < '3.14'",
    "onnxruntime-gpu>=1.20,<2",
    "nvidia-cudnn-cu12>=9,<10",
    "nvidia-cublas-cu12>=12,<13",
    "nvidia-cuda-runtime-cu12>=12,<13",
    "nvidia-cufft-cu12>=11,<13",
]
# Disk cost disclosed before the install step, so it stays a choice (§4.2.4):
# the GPU arm's CUDA wheels are ~2 GB, the CPU arm barely registers.
FOOTPRINT = {"cpu": "a few MB", "gpu": "~2 GB of wheels"}

CUDA_PROVIDER = "CUDAExecutionProvider"

# The same readiness budget the daemon's reader thread grants a cold spawn
# (`core.speech`): the verify spawn performs the identical load, warm-up and
# announce work, so it earns the same patience. The audio budget covers one
# short reply — slower than that is a hung engine, not latency.
READY_BUDGET = 15.0
AUDIO_BUDGET = 30.0
# Closing stdin is the worker's deliberate exit sign; this is how long we let
# it collect itself before killing it.
SHUTDOWN_GRACE = 5.0

# The ready fd carries one short line (speech's shape), a reply is a few tens
# of KB of PCM at 24 kHz — both read in comfortable pipe-sized chunks.
LINE_CHUNK = 1024
PCM_CHUNK = 64 * 1024
DOWNLOAD_CHUNK = 1024 * 1024
# urlopen's timeout bounds each blocking socket operation, not the whole
# transfer: a stalled connection gives up, while a slow-but-moving one can
# still deliver the ~300 MB model.
DOWNLOAD_TIMEOUT = 60

STATE_NAME = "provisioned.json"
LOCK_NAME = ".provision.lock"

# The one verify phrase, in English — the one language every install speaks.
VERIFY_TEXT = "Done."


class ProvisionError(RuntimeError):
    """A provisioning stage failed with a message a user can act on."""


# --- preflight (§4.2.1) ------------------------------------------------------


def preflight(kokoro_dir=None, *, prefix=None):
    """Reject impossible runs before anything is downloaded or installed.

    Three checks, each failing with the exact remedy: the interpreter is one
    kokoro-onnx can serve, the environment (wheels) is writable, and the model
    directory (files) is writable. The unwritable halves name `sudo` — and the
    model half also names the `EASYSPEAK_MODELS_DIR` escape hatch that moves
    it into user space. The kokoro-onnx importability check deliberately lives
    AFTER the wheel step (`require_importable`): before installing, there is
    nothing to import yet.
    """
    version = sys.version_info[:2]
    if version >= (3, 14):
        msg = (
            f"Kokoro needs Python < 3.14; this interpreter is {version[0]}."
            f"{version[1]}, and kokoro-onnx publishes no wheels for 3.14 yet."
        )
        raise ProvisionError(msg)
    prefix = prefix or sys.prefix
    if not os.access(prefix, os.W_OK):
        msg = (
            f"{prefix} (the Python environment) is not writable, so the Kokoro "
            "wheels cannot be installed; re-run with sudo, e.g. "
            "`sudo easyspeak --provision-kokoro`."
        )
        raise ProvisionError(msg)
    models = Path(kokoro_dir) if kokoro_dir is not None else config.KOKORO_DIR
    if not _writable(models):
        msg = (
            f"{models} is not writable, so the Kokoro model files cannot be "
            "downloaded there; re-run with sudo, or point EASYSPEAK_MODELS_DIR "
            "at a directory you own (the daemon must then run with the same "
            "variable, or it will keep looking in the default location)."
        )
        raise ProvisionError(msg)


def _writable(path):
    """Whether `path` can host files — creating it counts as part of the check.

    A missing directory is not a failure (the lock and downloads would create
    it anyway); a directory that cannot be created, or that exists but
    refuses writes, is.
    """
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    return os.access(path, os.W_OK)


# --- flavor and wheels (§4.2.2-§4.2.3) ---------------------------------------


def detect_flavor():
    """`gpu` when an NVIDIA driver's nvidia-smi is on PATH, else `cpu`.

    AMD gets the CPU flavor on purpose: its MIGraphX route accelerates nothing
    usable on current stacks, and an NVIDIA owner wanting CPU can still force
    `ONNX_PROVIDER=CPUExecutionProvider` at runtime.
    """
    return "gpu" if shutil.which("nvidia-smi") else "cpu"


def wheel_specs(flavor):
    """The PEP 508 specs for `flavor`, stated once and consumed verbatim."""
    return list(GPU_WHEEL_SPECS if flavor == "gpu" else CPU_WHEEL_SPECS)


# --- install (§4.2.4-§4.2.6) --------------------------------------------------


def install(flavor):
    """Install `flavor`'s wheels through the best installer door available.

    Doors, in order: `uv pip install` (fast, and the deb venv is uv-built, so
    it ships no pip); then pip bootstrapped via ensurepip; and when neither
    exists, a ProvisionError carrying the exact manual command. The GPU arm
    uninstalls the plain `onnxruntime` on its way in — under the pip door the
    two distributions would otherwise coexist with last-write-wins files
    (§4.2.6) — and the disk footprint is disclosed before anything is touched.
    """
    specs = wheel_specs(flavor)
    logger.info(
        "Installing the %s wheels for Kokoro — about %s will be added.",
        flavor,
        FOOTPRINT[flavor],
    )
    uv = shutil.which("uv")
    if uv is not None:
        if flavor == "gpu":
            _uninstall_onnxruntime(uv)
        _run([uv, "pip", "install", "--python", sys.executable, *specs])
        return
    # uv-built venvs ship no pip, so the pip door bootstraps it first.
    if _run([sys.executable, "-m", "ensurepip", "--upgrade"], check=False):
        if flavor == "gpu":
            _uninstall_onnxruntime(None)
        _run([sys.executable, "-m", "pip", "install", *specs])
        return
    msg = (
        "Neither uv nor pip is available to install the Kokoro wheels. "
        "Install uv (https://docs.astral.sh/uv), then run:\n  "
        f"{manual_command(flavor)}"
    )
    raise ProvisionError(msg)


def _uninstall_onnxruntime(uv=None):
    """Swap hygiene: remove the plain onnxruntime before the GPU arm lands.

    Best effort on purpose: a venv without the package (or a stale index)
    must not block the swap — the install that follows either replaces the
    files or fails loudly on its own.
    """
    if uv is not None:
        _run(
            [uv, "pip", "uninstall", "--python", sys.executable, "onnxruntime"],
            check=False,
        )
        return
    _run([sys.executable, "-m", "pip", "uninstall", "-y", "onnxruntime"], check=False)


def _run(cmd, *, check=True):
    """Run an installer command; True on success, ProvisionError with stderr.

    A nonzero exit can only reach the fall-through on a best-effort run (a
    checked run would have raised above), and it is logged there with the
    captured output — so a fall-through, like ensurepip failing to bootstrap
    pip, never happens silently.
    """
    try:
        proc = subprocess.run(cmd, check=check, capture_output=True, text=True)
    except subprocess.CalledProcessError as error:
        msg = (
            f"{' '.join(str(part) for part in cmd)} failed:\n"
            f"{error.stderr or error.stdout or '(no output)'}"
        )
        raise ProvisionError(msg) from None
    if proc.returncode == 0:
        return True
    logger.warning(
        "%s failed:\n%s",
        " ".join(str(part) for part in cmd),
        (proc.stderr or proc.stdout or "(no output)").strip(),
    )
    return False


def _shell_quoted(spec):
    """One shell-safe word for a PEP 508 spec: markers hold spaces and quotes.

    The marker's `python_version < '3.14'` gives up its single quotes for
    double ones (PEP 508 accepts both), so one shell quoting wraps the spec.
    """
    return "'" + spec.replace("'", '"') + "'"


def manual_command(flavor):
    """The exact command to run by hand when neither installer door exists.

    The interpreter path is resolved, not assumed — a deb install's venv
    python is what must receive the wheels — and quoted, since the path may
    hold spaces.
    """
    specs = " ".join(_shell_quoted(spec) for spec in wheel_specs(flavor))
    return f"uv pip install --python {shlex.quote(sys.executable)} {specs}"


def require_importable():
    """Preflight (c), after the wheel step: the import the daemon needs.

    This is the earliest point `config.kokoro_installed()`'s probe could
    succeed, so a failure here means the wheels landed somewhere else entirely.
    """
    if importlib.util.find_spec("kokoro_onnx") is None:
        msg = (
            "kokoro-onnx is still not importable after the wheel install; the "
            f"wheels may have landed in a different environment than "
            f"{sys.executable}"
        )
        raise ProvisionError(msg)


# --- model downloads (§4.3) ---------------------------------------------------


def load_pins():
    """Parse the packaged `runtime_pins.toml` copy — the TTS family only.

    The copy is generated by `just update-pins` (build output; hand-edits
    belong in `pins.toml`) and ships as `easyspeak.core` package data, so this
    reads the INSTALLED copy through importlib.resources — never a repo path.
    A missing, corrupt, or foreign copy is a ProvisionError, not a raw
    exception: the run must reach its machine line (§4.4).
    """
    source = importlib.resources.files("easyspeak.core").joinpath("runtime_pins.toml")
    if sys.version_info < (3, 11):
        import tomli as tomllib
    else:
        import tomllib
    try:
        with source.open("rb") as stream:
            kokoro = tomllib.load(stream)["tts"]["kokoro"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        msg = f"the packaged runtime pins copy is missing or unreadable: {error}"
        raise ProvisionError(msg) from error
    return kokoro


def download_models(pins):
    """Land both pinned files at their shipped names, checksums verified.

    Files already present with the pinned digest are kept, so re-runs pay no
    download; anything else streams through a `.part` file and is renamed only
    once its sha256 matches — `kokoro_installed()`'s probes and these checks
    can then never disagree about what is on disk (§4.3).
    """
    for dest, url in _download_targets(pins):
        try:
            expected = pins["files"][dest.name]
        except (KeyError, TypeError) as error:
            msg = f"the packaged pins carry no checksum for {dest.name}"
            raise ProvisionError(msg) from error
        if _digest_of(dest) == expected:
            logger.info("%s is already in place with the pinned checksum.", dest.name)
            continue
        logger.info("Downloading %s ...", dest.name)
        _download(url, dest, expected)


def _download_targets(pins):
    """The (destination, source URL) pairs, in download order."""
    return [
        (
            config.KOKORO_MODEL,
            (
                "https://huggingface.co/"
                f"{pins['model_repo']}/resolve/{pins['model_revision']}"
                f"/{pins['model_path']}"
            ),
        ),
        (
            config.KOKORO_VOICES,
            (
                "https://github.com/"
                f"{pins['voices_repo']}/releases/download/{pins['voices_tag']}"
                f"/{pins['voices_asset']}"
            ),
        ),
    ]


def _digest_of(path):
    """The sha256 of `path`'s bytes, or None when it is absent or unreadable."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(DOWNLOAD_CHUNK):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _download(url, dest, expected):
    """Stream `url` into `dest` via a `.part` file, honoring the pinned digest.

    The rename into the shipped name happens only after the streamed sha256
    matches; every other exit — mismatch, a network error mid-body, Ctrl+C —
    removes the partial in the `finally`, so a half-written file can never
    masquerade as an installed model.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    digest = hashlib.sha256()
    try:
        # S310: the URLs come verbatim from the machine-generated pins copy.
        with urlopen(url, timeout=DOWNLOAD_TIMEOUT) as response, part.open("wb") as out:  # noqa: S310
            while chunk := response.read(DOWNLOAD_CHUNK):
                digest.update(chunk)
                out.write(chunk)
        if digest.hexdigest() != expected:
            msg = (
                f"{dest.name} downloaded, but its checksum {digest.hexdigest()} "
                f"does not match the pinned {expected}; refusing to install it"
            )
            raise ProvisionError(msg)
        # os.replace, named exactly as the atomic-rename contract it is (spec
        # §4.4) — Path.replace is the same syscall under a friendlier face.
        os.replace(part, dest)  # noqa: PTH105
    except OSError as error:
        msg = f"downloading {url} failed: {error}"
        raise ProvisionError(msg) from error
    finally:
        part.unlink(missing_ok=True)


# --- verification (§4.4) -------------------------------------------------------


def verify(flavor):
    """Grade one real synthesis on the ladder; (verified, provider).

    - audio produced and the provider matching `flavor` → verified;
    - audio but CPU under the GPU flavor → a loud mismatch warning and not
      verified: the worker self-falls-back when CUDA session init fails, so
      this outcome is reachable by construction (the wheels work, just
      slower) — non-fatal by design;
    - no audio, or a worker that never announced → not verified.

    Missing model files skip the whole ladder: (False, None) with the reason
    logged, before any process is spawned. The phrase and voice are fixed
    English (`Done.` / af_heart): en is the one language every install speaks,
    and this check grades engine health, not language coverage. The worker's
    stderr is captured for the failed outcomes — provisioning exists to
    diagnose, so a silent failure would waste the run.
    """
    if not (config.KOKORO_MODEL.is_file() and config.KOKORO_VOICES.is_file()):
        logger.warning(
            "the model files are missing from %s; skipping verification",
            config.KOKORO_DIR,
        )
        return False, None
    # An unnamed temp file: the worker needs a real fd to write into, and
    # closing it deletes it — no cleanup path to forget. errors="replace"
    # because the child writes raw bytes to the fd; a non-UTF-8 one must
    # never blow up the failure handling that quotes it.
    with tempfile.TemporaryFile(
        mode="w+", encoding="utf-8", errors="replace"
    ) as worker_stderr:
        try:
            provider, audio = _probe(worker_stderr)
        except Exception as error:  # a failed probe is an outcome, not a crash
            logger.warning(
                "the Kokoro engine could not be started: %s%s",
                error,
                _worker_said(worker_stderr),
            )
            return False, None
        if provider is None:
            logger.warning(
                "the Kokoro worker never announced readiness; not verified%s",
                _worker_said(worker_stderr),
            )
            return False, None
        if not audio:
            logger.warning(
                "the Kokoro worker produced no audio; not verified%s",
                _worker_said(worker_stderr),
            )
            return False, provider
        if flavor == "gpu" and provider != CUDA_PROVIDER:
            logger.warning(
                "the GPU wheels are installed but the engine runs on %s; synthesis "
                "works, just slower. Check the driver setup in "
                "docs/troubleshooting.md and re-run `easyspeak --provision-kokoro`.",
                provider,
            )
            return False, provider
        return True, provider


def _worker_said(worker_stderr, limit=400):
    """The tail of the worker's captured stderr, for a failure log line.

    Empty when the worker said nothing — the suffix then simply disappears
    from the message instead of advertising a silence.
    """
    worker_stderr.seek(0)
    said = worker_stderr.read().strip()
    if not said:
        return ""
    return f" Worker stderr tail: ...{said[-limit:]}"


def _probe(worker_stderr):
    """Spawn the worker, read `ready provider=`, and synthesize one phrase.

    Mirrors `core.speech`'s spawn mechanics — os.pipe, the write end handed
    over at its real descriptor number via pass_fds, the parent's copy closed
    so EOF can report a death — minus the reader thread: provisioning is a
    one-shot CLI with nothing else to do, so it blocks synchronously.

    `worker_stderr` collects the worker's logs for the caller to quote on a
    failed outcome; a healthy run writes nothing there.

    Returns (provider, audio bytes); provider None when the ready line never
    arrived, audio empty when the synthesis produced nothing usable.
    """
    ready_read, ready_write = os.pipe()
    argv = [
        sys.executable,
        "-m",
        "easyspeak.core.kokoro_worker",
        "--model",
        str(config.KOKORO_MODEL),
        "--voices",
        str(config.KOKORO_VOICES),
        "--voice",
        config.KOKORO_VOICES_BY_LANGUAGE["en"],
        "--lang",
        config.KOKORO_LANGUAGE_CODES["en"],
        "--ready-fd",
        str(ready_write),
    ]
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=worker_stderr,
            # The write end crosses at its real descriptor number — the same
            # number `argv` already told the child about.
            pass_fds=(ready_write,),
        )
    except Exception:
        # The child never got (or never kept) its copy of the write end, so
        # both ends are still solely ours: close them or leak two fds.
        os.close(ready_read)
        os.close(ready_write)
        raise
    # The child holds its own copy now; keeping ours open would stop the read
    # end from ever seeing the EOF that reports a worker death.
    os.close(ready_write)
    # PIPE guarantees both streams; the Optional in the type is for DEVNULL
    # spawns we never do.
    assert proc.stdin is not None  # noqa: S101
    assert proc.stdout is not None  # noqa: S101
    try:
        line = _read_ready_line(ready_read, time.monotonic() + READY_BUDGET)
        if line is None or not line.startswith(b"ready"):
            return None, b""
        provider = line.decode("utf-8", "replace").split("provider=", 1)[-1].strip()
        try:
            proc.stdin.write(f"{VERIFY_TEXT}\n".encode())
            proc.stdin.flush()
            audio = _read_audio(proc.stdout.fileno(), time.monotonic() + AUDIO_BUDGET)
        except OSError:
            # A worker that died mid-check surfaces here as a broken pipe or a
            # closed stdout; the empty reply is the honest outcome.
            audio = b""
        return provider, audio
    finally:
        os.close(ready_read)
        _reap(proc)


def _read_ready_line(fd, deadline):
    """The worker's single ready line, or None on EOF/deadline (speech's shape).

    select() splits the wait against the deadline so a hung worker cannot hold
    the run past its budget — a plain blocking os.read has no timeout.
    """
    buf = bytearray()
    while b"\n" not in buf:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        readable, _, _ = select.select([fd], [], [], remaining)
        if not readable:
            return None
        chunk = os.read(fd, LINE_CHUNK)
        if not chunk:
            return None  # the worker died before announcing itself
        buf += chunk
        if len(buf) > 4096:
            return None  # the fd carries one short line; more is a breach
    return bytes(buf[: buf.index(b"\n")])


def _read_audio(fd, deadline):
    """Read the reply's PCM until it drains, the budget ends, or EOF.

    One flushed reply, not an endless stream: a short read means the pipe is
    momentarily drained, and that is the whole synthesis to count.
    """
    audio = bytearray()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        readable, _, _ = select.select([fd], [], [], remaining)
        if not readable:
            break  # budget expired with the worker still thinking
        chunk = os.read(fd, PCM_CHUNK)
        if not chunk:
            break  # the worker closed stdout — it is on its way out
        audio += chunk
        if len(chunk) < PCM_CHUNK:
            break  # drained: the whole reply fit in the pipe buffer
    return bytes(audio)


def _reap(proc):
    """Close the pipes and collect the worker; closing stdin is its exit sign.

    The same deliberate stdin-EOF exit the daemon's drain() uses, so a
    verified worker is never left lingering behind the CLI.
    """
    for stream in (proc.stdin, proc.stdout):
        if stream is not None:
            with contextlib.suppress(Exception):
                stream.close()
    try:
        proc.wait(timeout=SHUTDOWN_GRACE)
    except Exception:
        with contextlib.suppress(Exception):
            proc.kill()


# --- state, satisfaction, and the run (§4.2.7, §4.4) --------------------------


def write_state(kokoro_dir, record):
    """Persist the provision record atomically: temp file, then os.replace.

    A reader (the daemon's drift check) sees either the old record or the new
    one, never a half-written JSON. An unwritable directory is a
    ProvisionError rather than a raw OSError, so the run still reaches its
    machine line (§4.4).
    """
    directory = Path(kokoro_dir)
    temp = directory / (STATE_NAME + ".tmp")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        temp.write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temp, directory / STATE_NAME)  # noqa: PTH105 — see _download
    except OSError as error:
        msg = f"could not write {directory / STATE_NAME}: {error}"
        raise ProvisionError(msg) from error


def read_state(kokoro_dir):
    """The last provision record, or None when absent, corrupt, or foreign.

    Tolerant by contract: the daemon's drift check reads this file too, and a
    hand-mangled file must degrade to "no information", never to a crash.
    """
    try:
        record = json.loads((Path(kokoro_dir) / STATE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def is_satisfied(state, flavor):
    """Whether `state` already delivers `flavor` — satisfaction is per flavor.

    CPU counts when its verify passed; GPU only when the verify passed AND the
    CUDA provider actually engaged (§4.2.7) — GPU wheels that land on CPU are
    a mismatch worth re-running for. A recorded flavor differing from the
    detected one is the upgrade path (CPU→GPU or back), never a skip.
    """
    if not isinstance(state, dict) or not state.get("verified"):
        return False
    if state.get("flavor") != flavor:
        return False
    return not (flavor == "gpu" and state.get("provider") != CUDA_PROVIDER)


@contextlib.contextmanager
def provision_lock(kokoro_dir=None):
    """Serialize runs with an flock on `KOKORO_DIR/.provision.lock`.

    Blocking on purpose: provisioning is a rare, human-scale CLI action, so a
    second invocation waiting its turn is correct — and simpler — than a
    non-blocking refusal; the lock only has to keep two runs from interleaving
    downloads and wheel swaps (§4.2.1). Closing the descriptor releases the
    flock, so there is no explicit unlock to forget, and the file itself stays
    as the anchor for the next run.
    """
    directory = Path(kokoro_dir) if kokoro_dir is not None else config.KOKORO_DIR
    directory.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(directory / LOCK_NAME, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def summarize(flavor, provider, *, verified):
    """Print the machine-parseable run summary — stdout's one and only line.

    Scripted installs read this line (never the prose, which goes to logging)
    to tell which arm was delivered; `verified` is keyword-only so the call
    reads as the verdict it is.
    """
    # The one deliberate print in the module: this line's whole job is stdout.
    print(  # noqa: T201
        f"provision: flavor={flavor} "
        f"provider={provider or 'none'} "
        f"verified={'yes' if verified else 'no'}"
    )


def provision_kokoro():
    """Run the whole provision pipeline; returns the process exit code.

    The exit code tells scripted installs the truth: 0 only when a verified
    engine (or an already-satisfied run) is in place, 1 otherwise — the
    machine line on stdout carries the details either way. A preflight refusal
    ends without a machine line, because no flavor was ever engaged.
    """
    try:
        preflight()
    except ProvisionError as error:
        # A refusal is a user-facing message, not a crash: no traceback dump.
        logger.error("%s", error)  # noqa: TRY400
        return 1
    flavor = detect_flavor()
    state = read_state(config.KOKORO_DIR)
    if state is not None and is_satisfied(state, flavor):
        logger.info("Kokoro is already provisioned and verified; nothing to do.")
        summarize(flavor, state.get("provider"), verified=True)
        return 0
    verified = False
    provider = None
    with provision_lock():
        try:
            install(flavor)
            require_importable()
            download_models(load_pins())
            verified, provider = verify(flavor)
        except ProvisionError as error:
            # Same refusal-not-crash policy as the preflight handler above.
            logger.error("%s", error)  # noqa: TRY400
        # The write keeps its own caught region: separate, so a pipeline
        # failure above never skips it (§4.4 — on any outcome the record is
        # written, or a failed run would leave a stale "verified" state for
        # the next one to trust), and caught, so an unwritable state file
        # lands as a logged refusal and the machine line still prints.
        try:
            write_state(
                config.KOKORO_DIR,
                {
                    "flavor": flavor,
                    "wheels": wheel_specs(flavor),
                    "verified_at": datetime.now().astimezone().isoformat(),
                    "provider": provider,
                    "verified": verified,
                },
            )
        except ProvisionError as error:
            logger.error("%s", error)  # noqa: TRY400
    summarize(flavor, provider, verified=verified)
    return 0 if verified else 1
