"""The ydotool backend: the grid conversation without GNOME Shell.

Routes the grid conversation, computes cell bounds, and delegates rendering to
`_overlay.py` (a GTK4 layer-shell surface in a gi-capable interpreter) while
`ydotool` moves and clicks the pointer at kernel level. It is the backend that
makes the grid usable on compositors where no GNOME Shell can run (COSMIC,
sway, KDE Wayland, Hyprland).

A startup gate decides whether this backend may claim the grid words at all:
it is active only where a layer-shell-capable compositor AND a functional
injector are both present, and fails closed — a grid that takes the words
without being able to click is worse than one that stays with the extension
backend. Scroll and drag are not part of this backend's surface: ydotool
0.1.8 has no wheel verb, and a hold-drag needs a timing design its
one-invocation press+release cannot express.
"""

import contextlib
import json
import logging
import os
import select
import shutil
import socket
import stat
import subprocess
import threading
import time
from pathlib import Path

from easyspeak.core.i18n import translator

# Module-scope import is safe: `_overlay` imports only stdlib at its own module
# scope (gi is imported inside its functions), so the daemon's gi-less venv can
# import the backend. The explicit binding is what `helper_env` reads for the
# LD_PRELOAD probe below — a `from . import _overlay as alias` form would leave
# the plain name working only through the import machinery's implicit
# package-attribute side effect, which reads like a typo.
from . import _overlay
from ._common import (
    AGAIN_WORDS,
    CLICK_REPLIES,
    EXTENSION_ONLY_WORDS_BEFORE_CLICKS,
    GRID_TRIGGERS,
    SHOW_BLOCK_WORDS,
    ZONE_MAP,
    center,
    click_kind,
    dismiss_match,
    parse_direction,
    parse_number_sequence,
    subdivide,
)

logger = logging.getLogger(__name__)

_ = translator(__file__)

KIND = "ydotool"

# The gate's probes run inside resolve_active(), during daemon startup, where a
# hang is worse than a failure: the loader guards setup() with
# try/except Exception (core/main.py), which catches a raise but not a wait.
PROBE_TIMEOUT = 5.0
INJECT_TIMEOUT = 2.0
REAP_GRACE = 2.0
# The first-frame wait after `ready`: usually answered in milliseconds (the
# surface maps right away), bounded so a compositor that never frames cannot
# stall the session open.
PRESENT_TIMEOUT = 2.0
# The per-injection rediscovery bound: a daemon that is alive but wedged must
# cost a fraction of a second between a move and its click, not the startup
# bound (which stays at PROBE_TIMEOUT, where hanging is invisible).
PROBE_TIMEOUT_PER_USE = 0.25
YDTOOL_SOCKET = "/tmp/.ydotool_socket"  # noqa: S108 -- 0.1.8's hardcoded path
YDTOOL_SOCKET_NAME = ".ydotool_socket"  # 1.0.x defaults to $XDG_RUNTIME_DIR/that
# What the two daemons speak: 0.1.8's ydotoold listens on a stream socket,
# 1.0.x's on a datagram one. Connecting with the wrong type answers EPROTOTYPE
# rather than ECONNREFUSED, which would read as "no daemon" on a host that
# runs one.
YDTOOL_SOCKET_TYPES = (socket.SOCK_STREAM, socket.SOCK_DGRAM)
# `unrecognized option` is in here because a rejected argv is not an emission:
# 1.0.x's client prints `click: unrecognized option '--delay'` and still exits
# 0, which would otherwise be read as `ran` by a seam that trusts the exit
# code. `mousemove` with the same argv aborts instead (SIGABRT after the same
# line).
ERROR_SIGNATURES = (
    "error:",
    "Which coordinate",
    "Unknown tool",
    "failed to",
    "unrecognized option",
)
FALLBACK_NOTICE = "backend unavailable"
# The verbs the argv is allowed to use, read off the binary's own list:
# `mousemove` and `click` are the injections, and `type` is the probe's no-op.
# Ubuntu 25.10's 0.1.8 build offers exactly {type, recorder, mousemove, key,
# click} — no `mousemove_relative` — so a hard-coded verb gates the backend off
# there; 26.04's 1.0.4 adds debug and bakers to the same five.
YDTOOL_VERBS = ("mousemove", "click", "type")

# The two argv dialects ydotool has shipped, and how each one is recognised.
#
# 0.1.8 (Ubuntu 25.10) reads the position as positional arguments and has its
# own `--delay` flag: `mousemove 100 200 --delay 0`, `click 1` (1 = left, 2 =
# right, 3 = middle). With no daemon answering it builds a device for that one
# invocation and says so on stderr — a measured working path, hence a mode.
#
# 1.0.x (Ubuntu 26.04) dropped `--delay`, made the position explicit options
# (`mousemove --absolute -x 100 -y 200`, where `-x`/`-y` alone are
# *relative*), and spells buttons as hex selectors plus press/release mask
# bits: `0xC0` is a left click, `0xC1` right, `0xC2` middle, and `click 1` —
# 0.1.8's left click — is a right *selector* with no mask, which emits nothing
# at all. It also removed the per-invocation fallback: with no daemon socket
# the client exits 2 with "failed to connect socket" and injects nothing, so
# on that dialect the daemon is a capability, not a mode.
#
# The dialect is read from the binary: 1.0.x's own `mousemove --help` names
# `--absolute`, and 0.1.8's offers no such option. Anything else — an
# unreadable help, a build this backend has never met — keeps the legacy argv,
# which is the argv this backend shipped first.
YDTOOL_DIALECT_MODERN = "modern"
YDTOOL_DIALECT_LEGACY = "legacy"
YDTOOL_ABSOLUTE_FLAG = "--absolute"
YDTOOL_NOOP_LEGACY = ("ydotool", "type", "", "--delay", "0")
YDTOOL_NOOP_MODERN = ("ydotool", "type", "")

_active = False
_bounds = None
_monitor_origin = (0, 0)
_last_bounds = None
_helper = None
_dialect = None

# --- Injector plumbing (backend-agnostic) -----------------------------------
#
# The ydotool-facing helpers in this file — `_probe_dialect`, `dialect`,
# `ydotool_socket_candidates`, `_socket_owned`, `_socket_env_key`,
# `injector_socket`, `_client_env`, `_spawn`, `_run_bounded`,
# `run_ydotool`, `_socket_accepts`, `parse_tool_list`, `_probe_tools`,
# `_probe_injector`, and `noop_argv` — speak ydotool dialects, sockets
# and bounded runs, not the mouse grid. They are earmarked for
# extraction into core by the compositor-agnostic key-injection
# follow-up (docs/superpowers/specs/2026-10-17-compositor-agnostic-
# typing-for-easyspeak-design.md, section 4.3), which parameterizes the
# probe's verb surface (`YDTOOL_VERBS` is the grid's) and adds key and
# chord synthesis. The pointer verbs, overlay helper plumbing, gate
# policy (`activate` / `resolve_active`), and conversation below stay
# grid-owned.


def _probe_dialect():
    """Read the installed client's argv dialect from the client itself.

    `ydotool mousemove --help` is the binary's own answer about the move verb:
    1.0.x's usage line names `--absolute`, 0.1.8's has no such option. A build
    that cannot answer at all keeps the legacy argv rather than guessing at the
    modern one — the legacy argv is what this backend shipped first, and the
    functional half of the gate still has to report `ran` before the gate
    opens.
    """
    try:
        result = _spawn(["ydotool", "mousemove", "--help"], PROBE_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.info("grid: `ydotool mousemove --help` did not answer: %s", exc)
        return YDTOOL_DIALECT_LEGACY
    if YDTOOL_ABSOLUTE_FLAG in result.stdout + result.stderr:
        return YDTOOL_DIALECT_MODERN
    return YDTOOL_DIALECT_LEGACY


def dialect():
    """Return the installed client's argv dialect, resolved once, on demand.

    On demand rather than in `resolve_active()` because the forced-backend path
    (`EASYSPEAK_GRID_BACKEND=uinput`) short-circuits the probes, and the argv
    the seam builds still has to match the client that will run it.
    """
    global _dialect
    if _dialect is None:
        _dialect = _probe_dialect()
    return _dialect


def ydotool_socket_candidates():
    """Return the paths a ydotool client may find its daemon on, best first.

    `YDOTOOL_SOCKET` is the client's own override and wins outright. Past that,
    the daemon's default path is build-dependent
    (`$XDG_RUNTIME_DIR/.ydotool_socket` for 1.0.x, `/tmp/.ydotool_socket` for
    0.1.8) and `XDG_RUNTIME_DIR` is not always the login session's: the grid
    runs inside whatever session started the daemon, and a nested compositor or
    a test harness repoints it. The login session's own `/run/user/<uid>` path
    is therefore always considered, with the old hardcoded path last so a 0.1.8
    daemon is still found.
    """
    candidates = []
    override = os.environ.get("YDOTOOL_SOCKET")
    if override:
        candidates.append(override)
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        candidates.append(str(Path(runtime) / YDTOOL_SOCKET_NAME))
    candidates.append(f"/run/user/{os.getuid()}/{YDTOOL_SOCKET_NAME}")
    candidates.append(YDTOOL_SOCKET)
    return list(dict.fromkeys(candidates))


def _socket_owned(path):
    """True when `path` is a socket this user owns, and safe to talk to.

    A connectable socket is not automatically our daemon: every candidate but
    the `XDG_RUNTIME_DIR` and `/run/user` ones lives in a directory other users
    can write, and the `/tmp` fallback is 0.1.8's hardcoded path in the
    world-writable one. A socket planted there by someone else would accept our
    connection, pass the gate, and receive every coordinate we inject while
    injecting nothing. Ownership is the cheap authentication a unix socket
    cannot do for itself, so a candidate that exists but is not our socket —
    wrong type, or owned by another uid — is skipped, never trusted.
    """
    try:
        st = Path(path).stat()
    except OSError:
        return False
    if not stat.S_ISSOCK(st.st_mode):
        return False
    if st.st_uid != os.getuid():
        logger.warning(
            "grid: skipping %s (a socket owned by uid %s, not ours)",
            path,
            st.st_uid,
        )
        return False
    return True


# The candidate that answered last time, under the resolution environment it
# answered for. Probing it first keeps the per-use rediscovery honest (a
# daemon that stopped is not an injector any more) while sparing the common
# path the full four-path, two-socket-type fan-out on every injection — and
# keying the entry to `YDOTOOL_SOCKET`/`XDG_RUNTIME_DIR` keeps an env repoint
# (a nested compositor, the harness) in charge of priority: the override
# candidate is probed before any still-alive default.
_socket_last_good = None
_socket_last_good_env = None
# A full fan-out that answered nothing is remembered this long, keyed by the
# resolution environment it failed under: one click utterance calls
# `injector_socket` up to four times (the move's delay args and client env,
# then the click's), and a stale socket that accepts but never serves would
# otherwise tax every one of those calls with the full walk — the per-use
# bound per candidate, ~2 s of silent voice-thread stall between a move and
# its click. Within the window the answer "none" is shared; past it the walk
# runs again, so a daemon that starts (or moves) is found on the next
# utterance without help.
REDISCOVERY_COOLDOWN = 1.0
_socket_search_failed = None


def _socket_env_key():
    return (
        os.environ.get("YDOTOOL_SOCKET"),
        os.environ.get("XDG_RUNTIME_DIR"),
    )


def injector_socket(timeout=PROBE_TIMEOUT):
    """Return the daemon socket that answers, or None when none does.

    Asked afresh before each use rather than cached blindly: a daemon that
    stopped is not an injector any more, and one that started is, and the
    answer is what decides both the gate's mode line and whether the gate
    opens at all on a client that cannot inject without one. The last path
    that answered — under the same resolution environment — is re-probed
    first, so the steady state costs one connect instead of the full fan-out.

    `timeout` bounds each connect. The per-injection callers pass the short
    per-use bound: a daemon that is alive but wedged answers no connect, and
    the voice thread must not sit through the startup bound between a move and
    its click. A full walk that answered nothing is remembered for
    `REDISCOVERY_COOLDOWN` — per environment, so a changed
    `YDOTOOL_SOCKET`/`XDG_RUNTIME_DIR` always forces a fresh walk — and the
    per-injection calls inside that window share the one failed walk instead
    of repeating it.
    """
    global _socket_last_good, _socket_last_good_env, _socket_search_failed
    candidates = ydotool_socket_candidates()
    env_key = _socket_env_key()
    if (
        _socket_last_good
        and _socket_last_good_env == env_key
        and _socket_last_good in candidates
    ):
        if _socket_owned(_socket_last_good) and _socket_accepts(
            _socket_last_good, timeout
        ):
            return _socket_last_good
        _socket_last_good = None
    elif (
        _socket_search_failed is not None
        and _socket_search_failed[0] == env_key
        and time.monotonic() - _socket_search_failed[1] < REDISCOVERY_COOLDOWN
    ):
        # No path answered inside the window and the environment has not
        # changed since: repeating the walk would spend the per-use bound per
        # candidate to re-learn "none". The startup probe never lands here —
        # its first call finds no failure to remember.
        return None
    for candidate in candidates:
        if _socket_owned(candidate) and _socket_accepts(candidate, timeout):
            _socket_last_good = candidate
            _socket_last_good_env = env_key
            _socket_search_failed = None
            return candidate
    _socket_search_failed = (env_key, time.monotonic())
    return None


def _client_env():
    """The environment a ydotool client needs to reach the injector it must use.

    `None` inherits this process's environment, which is right while no socket
    answers (0.1.8 then builds its own device, and 1.0.x refuses on its own).
    When one does answer, the path is exported explicitly, because the client's
    own discovery is relative to `XDG_RUNTIME_DIR` and this process may be
    looking at a different one than the daemon's owner. The probe uses the
    short per-use bound: this runs between the move and the click of every
    utterance, and a wedged daemon must cost a fraction of a second, not the
    startup bound.
    """
    path = injector_socket(timeout=PROBE_TIMEOUT_PER_USE)
    if path is None:
        return None
    return {**os.environ, "YDOTOOL_SOCKET": path}


def _spawn(cmd, timeout):
    """The only place a ydotool process is started; tests patch this."""
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=_client_env(),
    )


def _run_bounded(args, timeout=INJECT_TIMEOUT):
    """Run one ydotool invocation and return its outcome, never its exit code.

    `MouseMove::Exec` and `Click::Exec` do `return argc`, but the 0.1.8 client
    discards that value in `main()`: a dispatched tool exits **0** whatever its
    argv length (measured on Ubuntu 25.10 — `ydotool click 1` exits 0). The
    seam therefore reads a zero exit with a clean stderr as `ran`, and still
    accepts the argv-shaped code for a build that forwards Exec's return. The
    three outcomes are what the rest of the module reasons about.

    "Clean output" is what makes that reading safe, which is why a rejected
    argv is an error signature: 1.0.4 answers `click: unrecognized option
    '--delay'` on stderr, emits nothing, and exits 0, so a seam reading only
    the code would call a no-op `ran` — and the same argv on `mousemove` dies
    with SIGABRT (134) instead. Both streams are scanned, like the probe seams,
    so a build that moves its refusals cannot silence them. `--delay 0` was
    0.1.8's flag; see the dialect block above.

    `timeout` bounds the process, which is what keeps a wedged ydotool (or
    ydotoold) from freezing the modal loop with the overlay on screen.
    """
    if os.environ.get("EASYSPEAK_GRID_DRY_RUN"):
        logger.info("dry run: %s", " ".join(args))
        return "ran"
    try:
        result = _spawn(args, timeout)
    except subprocess.TimeoutExpired:
        logger.warning("ydotool timed out after %ss: %s", timeout, " ".join(args))
        return "unknown"
    except OSError as exc:
        logger.warning("ydotool could not start: %s", exc)
        return "unknown"
    # Both streams are scanned, matching the probe seams: a build that moves a
    # refusal from stderr to stdout must not turn a rejection into a `ran`.
    output = f"{result.stdout or ''}\n{result.stderr or ''}"
    if any(sig in output for sig in ERROR_SIGNATURES):
        logger.warning("ydotool refused: %s", output.strip())
        return "errored"
    if FALLBACK_NOTICE in output:
        # 0.1.8 with no daemon: the client built a device for this invocation
        # and said so. The VM measured that path working — the notice names a
        # latency caveat, not a capability gap — so the invocation still
        # counts, and this line states which mode was in use. 1.0.x has no such
        # mode, and says so with "failed to connect socket" instead, which is
        # an error signature.
        logger.info("grid: per-invocation device (ydotoold unavailable)")
    # The argv-shaped code is what Exec returns and what a build forwarding it
    # would report — measured both ways on the draft's own table (`type ""`
    # forwarding reports the full argc, `click 1` reports one less), so the
    # legacy tolerance accepts either. The 0.1.8 client discards the value, so
    # the zero is the measured success code. The argv-shaped acceptance is
    # legacy-only: on the modern dialect exit 2 is `failed to connect socket`
    # — a real failure — and a click argv's length minus one is also 2, so
    # accepting the shape there would call a daemon-less click `ran` the
    # moment a signature drifts.
    if result.returncode == 0 or (
        dialect() == YDTOOL_DIALECT_LEGACY
        and result.returncode in (len(args) - 1, len(args))
    ):
        return "ran"
    if result.returncode < 0:
        logger.warning("ydotool was killed by signal %s", -result.returncode)
        return "unknown"
    return "errored"


def run_ydotool(args):
    """Run an injection, logging whatever it was that happened."""
    outcome = _run_bounded(args)
    if outcome != "ran":
        logger.warning("injection outcome: %s", outcome)
    return outcome


BUTTONS = {"click": 1, "right": 2, "middle": 3}
# 1.0.x button codes: the selector nibble picks the button (0x00 left, 0x01
# right, 0x02 middle) and 0xC0 is both mask bits — press and release — where a
# bare selector emits nothing at all. Measured in the VM against a GTK window:
# 0xC0 arrives as button 1, 0xC1 as button 3, 0xC2 as button 2, and 0x01/1 as
# no event whatsoever.
MODERN_BUTTONS = {"click": "0xC0", "right": "0xC1", "middle": "0xC2"}


def legacy_delay_args():
    """Return the legacy dialect's delay arguments, or nothing when daemonless.

    ydotool 0.1.8 sleeps `--delay` ms before emitting anything (MouseMove.cpp:
    `usleep(time_delay * 1000)`, and a delay of 0 skips even that), while
    daemonless mode creates a fresh uinput device per invocation: with
    `--delay 0` the events are written into a device the compositor has not
    yet enumerated and are simply lost — kernel uinput.rst documents the
    ordering requirement, and a live COSMIC session measured it (delay 0
    delivers nothing; the default 100ms delivers). The daemon path holds one
    persistent device, so there `--delay 0` stays: a double-click pair needs
    the saved sleeps to stay inside the desktop's double-click window.
    """
    if injector_socket(timeout=PROBE_TIMEOUT_PER_USE) is None:
        return ()
    return ("--delay", "0")


def move_to(x, y):
    """Move the pointer to a monitor-local point.

    The move is issued in the global space ydotool works in, in whichever argv
    the installed client understands: positional on 0.1.8 (with the daemonless
    settle delay from [`legacy_delay_args`][_ydotool.legacy_delay_args]),
    `--absolute -x/-y` on 1.0.x, where bare `-x`/`-y` would move *relatively*
    from wherever the pointer happens to be.
    """
    global_x, global_y = _monitor_origin[0] + x, _monitor_origin[1] + y
    if dialect() == YDTOOL_DIALECT_MODERN:
        return run_ydotool(
            [
                "ydotool",
                "mousemove",
                YDTOOL_ABSOLUTE_FLAG,
                "-x",
                str(global_x),
                "-y",
                str(global_y),
            ]
        )
    return run_ydotool(
        ["ydotool", "mousemove", str(global_x), str(global_y), *legacy_delay_args()]
    )


def click(button="click"):
    """Click a button at the current pointer position."""
    if dialect() == YDTOOL_DIALECT_MODERN:
        return run_ydotool(["ydotool", "click", MODERN_BUTTONS[button]])
    return run_ydotool(["ydotool", "click", str(BUTTONS[button]), *legacy_delay_args()])


def double_click():
    """Two sequential left clicks, with no sleeps between them.

    Each click is one invocation, as on 0.1.8: the pair must stay inside the
    desktop's double-click window, and `--delay 0` — or 1.0.x's argv, which has
    no delay to spend — is what keeps it there. The pair carries the worst
    outcome by rank — `errored` if either half refused, `ran` only when both
    ran — so a refused double speaks the definite line, as a refused single
    already does.
    """
    first = click("click")
    second = click("click")
    if "errored" in (first, second):
        return "errored"
    if first == second == "ran":
        return "ran"
    return "unknown"


GRID_PYTHON_CANDIDATES = ("python3", "/usr/bin/python3", "/usr/bin/python")
HELPER = str(Path(__file__).with_name("_overlay.py"))
HELPER_PROBE = (
    "import gi; gi.require_version('Gtk', '4.0'); "
    "gi.require_version('Gtk4LayerShell', '1.0'); "
    "from gi.repository import Gtk, Gtk4LayerShell"
)
# The two search paths a gtk4-layer-shell build tree has to be exported through:
# `GI_TYPELIB_PATH` for `gi` to find the typelib, `LD_LIBRARY_PATH` for the
# dynamic loader to find the shared object next to it.
TYPELIB_PATH_VARS = ("GI_TYPELIB_PATH", "LD_LIBRARY_PATH")


def helper_env(base=None):
    """Return the environment the helper and every probe leading to it runs in.

    `EASYSPEAK_GRID_TYPELIB` names the `src` directory of an uninstalled
    gtk4-layer-shell build — the documented fallback where no distro packages
    the layer-shell stack — but neither `gi` nor the dynamic loader understands
    that name. It is translated here into the two paths they do read, each
    prepended to whatever this process already carries, exactly as the
    integration fixture does. The same environment is handed to the interpreter
    probe, the helper's `--probe` and the helper spawn alike: a resolver that
    cannot see the build tree reports the very interpreter the override was set
    for as unsupported, and the gate then fails closed on a box the build tree
    would have served.

    `base` defaults to this process's environment; passing a mapping makes the
    construction a function of its input alone. The layer-shell library is
    exported last, and when an uninstalled build tree is configured its soname
    is resolved inside that tree: this process's loader fixed its search path
    at start, so a probe here could never see the `LD_LIBRARY_PATH` being
    constructed for the child.
    """
    env = dict(os.environ if base is None else base)
    build = env.get("EASYSPEAK_GRID_TYPELIB")
    if build:
        for name in TYPELIB_PATH_VARS:
            existing = env.get(name, "")
            env[name] = f"{build}{os.pathsep}{existing}" if existing else build
    preload = _overlay.layer_shell_lib_path(build)
    if preload:
        existing = env.get("LD_PRELOAD", "")
        env["LD_PRELOAD"] = f"{preload}:{existing}" if existing else preload
    return env


# The interpreter the gate's probe found, the override it was resolved under,
# and whether one was found at all. A `None` answer is never cached: the probe
# costs a fresh interpreter import each call (100-500 ms on the interactive
# open path), so a positive is remembered for the daemon's lifetime, while a
# negative keeps re-probing in case the box grows a working interpreter later.
# The cached value is only valid for the override it was found under — an env
# repoint invalidates it rather than silently answering with the old answer.
_grid_python = None
_grid_python_override = None
_grid_python_found = False


def grid_python():
    """Return an interpreter that can run the helper, or None.

    Mirrors dictation's AT-SPI probe: the helper needs PyGObject and the
    layer-shell typelib, which the daemon's venv does not have, so each
    candidate is probed with the helper's own import chain. The probe runs in
    `helper_env()`, so an interpreter that only finds the typelib through
    `EASYSPEAK_GRID_TYPELIB` counts. Bounded, because a startup hang is
    invisible in a way an exception is not. The first candidate that answers is
    cached under the override that produced it — the answer does not go stale
    the way a socket does, and every grid open would otherwise pay the import
    probe again.
    """
    global _grid_python, _grid_python_override, _grid_python_found
    override = os.environ.get("EASYSPEAK_GRID_PYTHON")
    if _grid_python_found and _grid_python_override == override:
        return _grid_python
    candidates = (override,) if override else GRID_PYTHON_CANDIDATES
    for candidate in candidates:
        try:
            probe = subprocess.run(
                [candidate, "-c", HELPER_PROBE],
                capture_output=True,
                check=False,
                timeout=PROBE_TIMEOUT,
                env=helper_env(),
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if probe.returncode == 0:
            _grid_python = candidate
            _grid_python_override = override
            _grid_python_found = True
            return candidate
    return None


def _probe_overlay():
    """True when an interpreter can run the helper and layer-shell is supported.

    The helper answers the layer-shell question in --probe mode, under
    `helper_env()` so a build-tree override reaches the probe as well.
    """
    python = grid_python()
    if python is None:
        logger.info("grid: no interpreter with PyGObject + Gtk4LayerShell")
        return False
    try:
        probe = subprocess.run(
            [python, HELPER, "--probe"],
            capture_output=True,
            check=False,
            timeout=PROBE_TIMEOUT,
            env=helper_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        logger.info("grid: the helper probe did not answer in time")
        return False
    if probe.returncode != 0:
        logger.info("grid: layer-shell unsupported here (%s)", probe.stdout.strip())
        return False
    return True


def _socket_accepts(sock_path=YDTOOL_SOCKET, timeout=PROBE_TIMEOUT):
    """True when the ydotoold socket at `sock_path` takes a connection.

    Both socket types are tried, in this order: 1.0.x's daemon speaks
    `SOCK_DGRAM` while 0.1.8's speaks `SOCK_STREAM`, and connecting with the
    other type fails with `EPROTOTYPE` ("Protocol wrong type for socket") — a
    reading that would say "no daemon" on a box where one is running. On 1.0.x
    that reading decides whether the gate opens at all, so it has to be a real
    one. A stale path cannot hide behind the datagram half: the daemon is only
    trusted once the functional probe has also reported `ran` through it.

    No injection, no side effect. The daemon holds an already-recognised
    device, so injections through it carry no per-invocation latency caveat —
    which is the whole difference on 0.1.8, and the only working path on 1.0.x.

    `timeout` bounds each connect. The startup probes keep the full
    `PROBE_TIMEOUT`; the per-injection path passes the short per-use bound,
    because a daemon that is alive but wedged would otherwise hold the voice
    thread for the full bound on every move and click.
    """
    for sock_type in YDTOOL_SOCKET_TYPES:
        conn = socket.socket(socket.AF_UNIX, sock_type)
        try:
            conn.settimeout(timeout)
            conn.connect(sock_path)
        except OSError:
            continue
        finally:
            conn.close()
        return True
    return False


def parse_tool_list(text):
    """Return the verbs named by a `ydotool help` output.

    The list is the indented lines after the "Available commands:" header, one
    verb per line; the usage line before it is not a verb, and neither is the
    trailing sentence 1.0.4 prints after the list ("Use environment variable
    YDOTOOL_SOCKET ..."). Capability is read from this list because the verb
    set is build-dependent: Ubuntu 25.10's ydotool 0.1.8 offers `type`,
    `recorder`, `mousemove`, `key` and `click` — and no `mousemove_relative`
    at all.
    """
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if "Available commands:" in line:
            start = index
            break
    if start is None:
        return set()
    return {
        # The verb is the line's first token: some builds append a per-verb
        # description on the same line, and a whole-line entry would never
        # match the verbs this backend needs.
        line.split()[0]
        for line in lines[start + 1 :]
        if line.strip() and line[:1] in (" ", "\t")
    }


def _probe_tools():
    """Return the verbs `ydotool help` offers, or None when it cannot answer.

    The help text goes to stderr and the process exits 1 by design (ShowHelp
    then exit(1)), so this reads the output rather than the code; both streams
    are consulted so a build that moves the list to stdout still parses.
    """
    try:
        result = _spawn(["ydotool", "help"], PROBE_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.info("grid: `ydotool help` did not answer: %s", exc)
        return None
    return parse_tool_list(result.stdout + result.stderr)


def _probe_injector():
    """True when ydotool offers the verbs and a no-op reports `ran`.

    Capability is read from the binary's own tool list, never assumed: Ubuntu
    25.10's ydotool 0.1.8 has no `mousemove_relative`, so a probe built on that
    verb could never pass there. The functional half is `type ""` — the only
    side-effect-free verb of the five, where `mousemove 0 0` would move the
    pointer and `click 0` is a real left click — built in the dialect the same
    binary reported for itself, so what the probe exercises is exactly the argv
    the seam will later emit.

    The daemon decides on 1.0.x what it only described on 0.1.8. 0.1.8 falls
    back to a per-invocation uinput device and calls that a latency caveat, so
    there the socket is the mode this line logs, not a condition. 1.0.x removed
    the fallback: with no socket it exits 2 with "failed to connect socket" and
    emits nothing at all, so on that dialect "no daemon answering" means "no
    injector", and the probe fails closed — the words stay with the extension
    backend rather than a grid that cannot click. Every other half still fails
    closed the same way: no binary, no verbs, or a probe that does not report
    `ran`.

    The verb check compares against `YDTOOL_VERBS`, which is the mouse grid's
    surface. A consumer with a different verb set — the compositor-agnostic
    key-injection follow-up and its `key` verb — parameterizes that list and
    keeps the rest of this probe (binary presence, dialect, socket, no-op)
    exactly as it stands.
    """
    if shutil.which("ydotool") is None:
        logger.info("grid: ydotool is not installed")
        return False
    tools = _probe_tools()
    if tools is None:
        return False
    missing = [verb for verb in YDTOOL_VERBS if verb not in tools]
    if missing:
        logger.info(
            "grid: ydotool offers no %s (has: %s)",
            ", ".join(missing),
            ", ".join(sorted(tools)) or "nothing",
        )
        return False
    path = injector_socket()
    if path is not None:
        logger.info("grid: ydotoold answers on %s; injections use the daemon", path)
    elif dialect() == YDTOOL_DIALECT_MODERN:
        logger.info(
            "grid: no ydotoold on any of %s and this ydotool (%s) builds no device "
            "without one, so there is no injector here",
            ", ".join(ydotool_socket_candidates()),
            YDTOOL_DIALECT_MODERN,
        )
        return False
    else:
        logger.info(
            "grid: no ydotoold on %s; injections build a per-invocation device "
            "(latency caveat, not a capability gap)",
            YDTOOL_SOCKET,
        )
    outcome = _run_bounded(noop_argv())
    if outcome != "ran":
        logger.info("grid: the injector probe reported %s", outcome)
        return False
    return True


def noop_argv():
    """Return the probe's no-op invocation in the installed client's dialect.

    `type ""` types nothing, which is why it is the probe's verb; 0.1.8 spells
    its delay flag out on the argv and 1.0.x has no such flag at all.
    """
    if dialect() == YDTOOL_DIALECT_MODERN:
        return YDTOOL_NOOP_MODERN
    return YDTOOL_NOOP_LEGACY


def activate():
    """Force the backend active without probing.

    A deliberate override: asking for this backend explicitly through
    `EASYSPEAK_GRID_BACKEND=uinput` is the one case where a probe's answer is
    not the point (the harness uses it to observe the overlay without a daemon
    and without a real injector).
    """
    global _active
    _active = True
    logger.info("grid: forced active by EASYSPEAK_GRID_BACKEND=uinput")


def resolve_active():
    """Resolve the gate once, at daemon startup; True when both halves pass.

    The two probes are independent until the conjunction, so they run side by
    side: one common deadline covers both, and a host where both would hang
    pays the longest probe bound once, not the serial sum, at daemon startup.
    Both always run when nothing is forced — skipping the injector probe on an
    overlay failure would save one bounded connect and cost the concurrency.

    The deadline is sized to the larger worst case: the overlay probe may try
    three interpreter candidates plus the helper probe. The injector probe's
    own worst case is not fully accountable (a wedged ydotoold socket burns
    its settimeout per connect, per candidate, per type), so overshoot fails
    closed by design: past the deadline the gate shuts even though the probe
    would still answer. The threads are daemons so a wedged probe can never
    hold the daemon shut-down hostage; a late result lands in `outcome`
    unread.
    """
    global _active
    outcome = {}

    def _run(name, probe):
        outcome[name] = probe()

    threads = [
        threading.Thread(
            target=_run,
            args=(name, probe),
            name=f"grid-probe-{name}",
            daemon=True,
        )
        for name, probe in (
            ("overlay", _probe_overlay),
            ("injector", _probe_injector),
        )
    ]
    deadline = time.monotonic() + (len(GRID_PYTHON_CANDIDATES) + 1) * PROBE_TIMEOUT
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))
    overlay = bool(outcome.get("overlay"))
    injector = bool(outcome.get("injector"))
    _active = overlay and injector
    logger.info("grid backend %s", "active" if _active else "inert")
    return _active


# --- Grid conversation: session, overlay lifecycle, pointer verbs -----------


def _dismiss():
    """Hide the grid and end whatever session is open."""
    global _bounds
    _close_session()
    _bounds = None


def _open_session(core, bounds=None):
    """Open the overlay, take its geometry, and drive the mode until it ends.

    `bounds` is the cell to reopen at (the "again" path) and defaults to the
    whole output. Every outcome is spoken here, so the caller needs nothing
    back from this function.
    """
    global _monitor_origin, _bounds
    geometry = _start_helper()
    if geometry is None:
        core.speak(_("I couldn't show the grid."))
        return
    _monitor_origin = (geometry[0], geometry[1])
    if bounds:
        left, top, width, height = bounds
        fits = (
            left >= 0
            and top >= 0
            and left + width <= geometry[2]
            and top + height <= geometry[3]
        )
        if not fits:
            # The remembered cell came from a previous session's geometry: a
            # resolution change or a dock swap between sessions would draw it
            # clipped and aim its clicks at the edge of the output. The fresh
            # full rectangle is the only shape the containment invariant
            # guarantees, so a cell that no longer fits reopens as one.
            logger.info("grid: the remembered cell does not fit; reopening full")
            bounds = None
    _bounds = tuple(bounds) if bounds else (0, 0, geometry[2], geometry[3])
    # Everything from the first show on runs with a live helper holding the
    # overlay on screen, so it is all inside the try: a raise in the
    # announcement read or the announcement speak (route_command swallows
    # those per plugin, so the daemon would keep running) must not leave the
    # grid drawn with nobody left to close it. `_close_session` is safe to
    # call twice, which is also what makes the show-refusal path below —
    # stop_helper, speak, return — fall out through the finally for free.
    try:
        # The first show goes out before the mode starts listening: without it
        # the grid is never drawn and the session looks like a dead daemon.
        _redraw(_bounds)
        # Consume the `presented` announcement so the protocol's promise is
        # kept. It can only arrive HERE: `_draw` announces the first frame
        # once it has bounds to draw, and bounds exist only after the show
        # above — waiting in the ready handshake would expire every time and
        # stall each open by the full bound. A compositor that never frames
        # costs the bound once here and only lowers the log's confidence.
        announcement = read_until(_helper.stdout, time.monotonic() + PRESENT_TIMEOUT)
        if announcement and announcement.get("event") == "presented":
            logger.info("grid: first frame on screen")
        elif announcement and announcement.get("event") == "error":
            # The same read is the first consumer of a show-triggered refusal:
            # the helper emits `error` and quits when the surface went up but
            # the click-through region could not be applied. Mirroring
            # `_start_helper`'s refusal path keeps the helper's contract whole
            # on this side too.
            logger.warning(
                "grid: helper refused the show: %s", announcement.get("message")
            )
            stop_helper("show refused")
            core.speak(_("I couldn't show the grid."))
            return
        elif announcement and announcement.get("event") == "_eof":
            # The same read's EOF answer: the helper is gone without having
            # presented a frame, so the grid is provably not on screen —
            # mirroring the refusal arm keeps the user from hearing "Grid"
            # for a surface that will never appear (the mode's own death on
            # the next poll is silent, so the fall-through would leave exactly
            # that).
            logger.warning("grid: the helper exited right after ready")
            stop_helper("died after ready")
            core.speak(_("I couldn't show the grid."))
            return
        else:
            logger.debug("grid: no presented announcement inside PRESENT_TIMEOUT")
        core.speak(_("Grid"))
        _run_mode(core)
    finally:
        _close_session()


def handle(cmd, core):
    """Claim the grid words when the gate passed, and only then.

    Returns None when inert or when the utterance is not ours; True whenever
    the phrase was claimed and answered, failures included, because the
    backend has already spoken by then. Which backend serves the words was
    decided once at setup: an inert gate here means setup selected the
    extension backend, not that this module delegates mid-conversation.
    """
    global _bounds, _last_bounds
    if not _active:
        return None
    words = cmd.lower().strip().split()
    if not words:
        return None

    if any(word in words for word in AGAIN_WORDS) and _last_bounds:
        # Reopen on the remembered cell. It is passed in rather than assigned
        # to the global first: _open_session overwrites the bounds with the
        # whole output otherwise, which is what a fresh open wants and a
        # reopen does not.
        _open_session(core, bounds=_last_bounds)
        return True

    # The show guard mirrors the extension backend's exactly ("close"/"hide",
    # nothing more): one utterance must land the same on whichever backend
    # answers, so a phrase like "grid quit" opens here when the gate passed
    # and there when it did not. Dismissals live inside an open session's
    # loop, where the mode owns the microphone.
    if any(word in words for word in GRID_TRIGGERS) and not (
        SHOW_BLOCK_WORDS & set(words)
    ):
        _bounds = None
        _open_session(core)
        return True

    return None


def _redraw(bounds):
    """Tell the helper to redraw the numbered grid over these bounds."""
    _send({"cmd": "show", "bounds": list(bounds)})


def _run_mode(core):
    """Dispatch one utterance per round until the mode ends.

    Core owns the loop (see listen_modal) so the tray stays live and an
    unattended grid times out instead of holding the microphone for ever. Each
    round first checks the helper is still alive: a helper that died with the
    grid open ends the mode before this utterance can aim a click at geometry
    that no longer exists.
    """
    global _bounds, _last_bounds
    for spoken in core.listen_modal(
        "grid",
        prompt=(
            "one two three four five six seven eight nine click double "
            "right close cancel"
        ),
        timeout=10,
        idle_timeout=30,
    ):
        if _helper is not None and _helper.poll() is not None:
            # The surface is gone (helper crash, compositor restart, monitor
            # unplugged). A click is never injected against geometry that no
            # longer exists: end the mode through the dismissal path, which
            # discards the bounds too. No speech - the spec asks for the log
            # line and the end of the mode, not a new reply string. The
            # helper's last words, though, are read: a refusal that arrived
            # mid-mode (the click-through region failed on a redraw, say) is
            # the diagnostic for the vanish, and EOF answers immediately.
            last_words = read_until(_helper.stdout, time.monotonic() + PRESENT_TIMEOUT)
            if last_words and last_words.get("event") == "error":
                logger.warning(
                    "grid: the helper's last words: %s", last_words.get("message")
                )
            logger.warning(
                "grid: the helper exited with the grid open; ending the mode"
            )
            _dismiss()
            return

        text = spoken.lower()
        logger.debug("grid: heard %r", spoken)

        if dismiss_match(text):
            _dismiss()
            core.speak(_("Grid closed"))
            return

        # Extension-only verbs are named instead of silently swallowed: a
        # user who says "scroll down" must be able to learn where the
        # boundary is. Each group is checked where the extension loop would
        # have honoured it (`_extension._run_grid_mode`: mark, drag, scroll
        # BEFORE the click words, nudge AFTER), not at this loop's tail — a
        # compound utterance like "scroll down 3" or "scroll click" must
        # classify as the verb, the extension's answer, rather than as a
        # zone zoom or a real click.
        if any(word in text for word in EXTENSION_ONLY_WORDS_BEFORE_CLICKS):
            core.speak(_("That needs the GNOME extension."))
            continue

        kind = click_kind(text)
        if kind:
            _fire_click(kind, core)
            return

        # Bare directions are the extension's nudge grammar — its COMMANDS
        # line advertises "up/down/left/right [N]", verb word optional — and
        # the extension honours them here, before the zone numbers. This
        # backend has no nudge to serve them with, so it names the boundary
        # instead: "up 5" must not zoom into zone 5.
        if "nudge" in text or parse_direction(text):
            core.speak(_("That needs the GNOME extension."))
            continue

        zones = parse_number_sequence(text)
        if zones and _bounds:
            applied = False
            for zone in zones:
                if zone not in ZONE_MAP:
                    # A parsed "digit" outside the 1-9 zones is the
                    # extension's silent no-op (`update_grid` returns False
                    # at its own ZONE_MAP guard), not a crash: a fullwidth
                    # zero passes `isdecimal` exactly like a fullwidth three
                    # does, and letting it reach `subdivide` killed this
                    # backend's session on an utterance the extension shrugs
                    # off.
                    continue
                _bounds = subdivide(_bounds, zone)
                applied = True
            if applied:
                _redraw(_bounds)
            continue


def _fire_click(kind, core):
    """Move to the cell centre, click, remember the cell, and hide the grid.

    The cell is remembered here rather than on every subdivision, mirroring
    the extension backend: "again" means "back to where I last clicked", not
    "back to the last cell I walked past".
    """
    global _last_bounds
    if not _bounds:
        return
    x, y = center(_bounds)
    _last_bounds = _bounds
    moved = move_to(x, y)
    clicked = None
    if moved == "ran":
        # `ran` is the only positive signal the seam can produce: the move was
        # emitted through an already-recognised device. A move left `unknown`
        # leaves the pointer's position no more proven than a refusal, and a
        # click lands wherever the pointer happens to be — so it is not fired.
        clicked = double_click() if kind == "double" else click(kind)
    _dismiss()
    # The click's outcome is spoken first: once the move ran, a click failure
    # reported as "couldn't move the pointer" would name an action that
    # succeeded and hide the one that didn't.
    if clicked == "errored":
        core.speak(_("I couldn't click."))
    elif clicked == "unknown":
        core.speak(_("I tried, but I'm not sure it worked."))
    elif moved == "errored":
        core.speak(_("I couldn't move the pointer."))
    elif moved == "unknown":
        core.speak(_("I tried, but I'm not sure it worked."))
    else:
        # The success reply, the same word the extension backend speaks: the
        # overlay vanishing is the only other cue, and it says nothing about
        # what was done — a silent vanish is indistinguishable from an idle
        # timeout.
        core.speak(CLICK_REPLIES[kind])


def _start_helper():
    """Spawn the helper, take its geometry, and return it or None.

    The helper is spawned with `Popen`, not `run`: `run` would only return once
    the process exits, and this process must stay up and keep rendering. It
    runs under `helper_env()`, which is where a gtk4-layer-shell build tree
    named by `EASYSPEAK_GRID_TYPELIB` becomes visible to the helper. The
    `ready` wait is a read on a live child's pipe, so it is bounded by a
    `select` deadline rather than a subprocess timeout, which cannot reach a
    pipe read. A helper that stays alive and writes nothing is the case that
    distinction exists for.
    """
    global _helper
    python = grid_python()
    if python is None:
        return None
    try:
        _helper = subprocess.Popen(
            [python, HELPER],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=helper_env(),
        )
    except OSError as exc:
        logger.warning("grid: the helper could not start: %s", exc)
        _helper = None
        return None

    deadline = time.monotonic() + PROBE_TIMEOUT
    while True:
        message = read_until(_helper.stdout, deadline)
        if message is None:
            logger.warning("grid: the helper never reported ready (deadline)")
            stop_helper("no ready inside PROBE_TIMEOUT")
            return None
        event = message.get("event")
        if event == "_eof":
            logger.warning("grid: the helper exited before reporting ready")
            stop_helper("helper exited before ready")
            return None
        if event == "ready":
            logger.info(
                "grid: ready on %s (scale %s)",
                message.get("monitor"),
                message.get("scale"),
            )
            break
        if event == "error":
            logger.warning("grid: helper refused: %s", message.get("message"))
            stop_helper("helper error")
            return None
        logger.debug("grid: %s", event)

    monitor = message.get("monitor")
    if (
        not monitor
        or len(monitor) != 4
        or not all(
            isinstance(value, int) and not isinstance(value, bool) for value in monitor
        )
        or monitor[2] <= 0
        or monitor[3] <= 0
    ):
        # Length alone is not sanity: a broken compositor report with a zero or
        # negative width would pass the length check and later aim every click
        # at (0, 0) or off the output, spoken as success.
        logger.warning("grid: the ready event carried no usable geometry")
        stop_helper("bad geometry")
        return None
    return tuple(monitor)


def read_until(stream, deadline):
    """Read one JSON line from `stream`, or None when the deadline passes.

    The bound is a mechanism here, not a property: `select` is what lets a
    blocking read give up. The line is assembled from single bytes off the
    descriptor rather than read back with `stream.readline()`, whose text layer
    reads ahead: a line that layer holds is invisible to `select`, and a chunk
    read here would strand every line after the one returned. One byte at a
    time is what leaves the unread protocol in the one place `select` can see
    it. Anything that does not parse — or parses to something that is not an
    object — is logged and skipped: a bare JSON number or string is valid
    JSON but not an event, and returning it would hand every caller, which
    asks `.get("event")`, an AttributeError instead of a protocol answer. EOF
    returns the `_eof` event rather than None — a helper that died instantly
    and a helper that said nothing are different failures, and the callers
    log them differently.
    """
    pending = b""
    while True:
        if pending.endswith(b"\n"):
            line = pending.decode("utf-8", "replace")
            pending = b""
            try:
                message = json.loads(line)
            except ValueError:
                logger.warning(
                    "grid: ignoring unparsable protocol line: %r", line[:120]
                )
            else:
                if isinstance(message, dict):
                    return message
                logger.warning(
                    "grid: ignoring non-object protocol line: %r", line[:120]
                )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        try:
            ready, _, _ = select.select([stream], [], [], remaining)
        except (OSError, ValueError):
            return None
        if not ready:
            return None
        chunk = os.read(stream.fileno(), 1)
        if not chunk:
            return {"event": "_eof"}
        pending += chunk


def _send(payload):
    """Write one protocol line to the helper, if one is running."""
    if _helper is None or _helper.stdin is None:
        return False
    try:
        _helper.stdin.write(json.dumps(payload) + "\n")
        _helper.stdin.flush()
    except (BrokenPipeError, ValueError):
        logger.warning("grid: the helper is gone; dropping %s", payload.get("cmd"))
        # Dispose of the dead stream now: a wrapper that still holds the
        # undelivered line retries the flush when it is collected, and Python
        # reports the retried BrokenPipeError as an ignored exception on stderr.
        with contextlib.suppress(OSError, ValueError):
            _helper.stdin.close()
        return False
    return True


def stop_helper(reason):
    """Stop and reap the helper, escalating when it will not go.

    `terminate()`, a bounded wait, then `kill()`, logging which rung was
    needed: an unbounded `wait()` would freeze the mode at exactly the point
    this function exists to make safe, and a process that cannot be scheduled
    to handle SIGTERM still takes a kill from the kernel.
    """
    global _helper
    helper, _helper = _helper, None
    if helper is None or helper.poll() is not None:
        return
    helper.terminate()
    try:
        helper.wait(timeout=REAP_GRACE)
        logger.debug("grid: helper stopped (%s)", reason)
    except subprocess.TimeoutExpired:
        logger.warning("grid: helper ignored SIGTERM (%s); killing", reason)
        helper.kill()
        try:
            helper.wait(timeout=REAP_GRACE)
        except subprocess.TimeoutExpired:
            # A helper in uninterruptible sleep (D-state) ignores SIGKILL for
            # a while. Raising here would replace whatever was in flight
            # through the mode's finally, and print a traceback at atexit —
            # the one teardown path whose purpose is "cannot freeze" must not
            # be the one that can raise. The corpse stays a zombie of THIS
            # process until the daemon exits — init reaps orphans only, and
            # the daemon is the parent — so one zombie PID per occurrence is
            # the accepted price of teardown that can neither freeze nor
            # raise.
            logger.warning(
                "grid: helper survived SIGKILL (%s); zombie until daemon exit",
                reason,
            )


def cleanup():
    """Backend teardown for the plugin's exit path; delegates to the session."""
    _close_session()


def _close_session():
    """Tear the surface down and reap the helper; safe to call twice."""
    _send({"cmd": "hide"})
    stop_helper("session closed")
