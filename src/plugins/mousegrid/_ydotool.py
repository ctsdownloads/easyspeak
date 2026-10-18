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
import subprocess
import threading
import time
from pathlib import Path

from easyspeak.core.i18n import translator

# The ydotool run seam — dialects, sockets, bounded runs, and the capability
# probes — lives in `easyspeak.core.ydotool` (compositor-agnostic: it knows
# the client, not any caller) and is re-exported here so the grid's namespace,
# and its tests, keep working unchanged. The moved functions resolve their own
# internal calls in core's module globals, so tests stub them THERE; patching
# these re-exports goes blind.
from easyspeak.core.ydotool import (  # noqa: F401 — re-exported for the grid
    ERROR_SIGNATURES,
    FALLBACK_NOTICE,
    INJECT_TIMEOUT,
    PRESENT_TIMEOUT,
    PROBE_TIMEOUT,
    PROBE_TIMEOUT_PER_USE,
    REAP_GRACE,
    YDTOOL_ABSOLUTE_FLAG,
    YDTOOL_DIALECT_LEGACY,
    YDTOOL_DIALECT_MODERN,
    YDTOOL_NOOP_LEGACY,
    YDTOOL_NOOP_MODERN,
    YDTOOL_SOCKET,
    YDTOOL_SOCKET_NAME,
    YDTOOL_SOCKET_TYPES,
    _client_env,
    _probe_dialect,
    _probe_tools,
    _run_bounded,
    _socket_accepts,
    _socket_env_key,
    _socket_owned,
    _spawn,
    dialect,
    injector_socket,
    noop_argv,
    parse_tool_list,
    run_ydotool,
    ydotool_socket_candidates,
)

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

# The verbs the argv is allowed to use, read off the binary's own list:
# `mousemove` and `click` are the injections, and `type` is the probe's no-op.
# Ubuntu 25.10's 0.1.8 build offers exactly {type, recorder, mousemove, key,
# click} — no `mousemove_relative` — so a hard-coded verb gates the backend off
# there; 26.04's 1.0.4 adds debug and bakers to the same five.
YDTOOL_VERBS = ("mousemove", "click", "type")


def _grid_dry_run():
    """The grid's dry-run debug flag, handed to the seam as its parameter.

    The env read stays grid-side on purpose: core reads no `EASYSPEAK_GRID_*`
    variable of its own, so a future consumer of the seam (key injection)
    cannot inherit this silent-ran switch by accident.
    """
    return bool(os.environ.get("EASYSPEAK_GRID_DRY_RUN"))


_active = False
_bounds = None
_monitor_origin = (0, 0)
_last_bounds = None
_helper = None


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
            ],
            dry_run=_grid_dry_run(),
        )
    return run_ydotool(
        [
            "ydotool",
            "mousemove",
            str(global_x),
            str(global_y),
            *legacy_delay_args(),
        ],
        dry_run=_grid_dry_run(),
    )


def click(button="click"):
    """Click a button at the current pointer position."""
    if dialect() == YDTOOL_DIALECT_MODERN:
        return run_ydotool(
            ["ydotool", "click", MODERN_BUTTONS[button]], dry_run=_grid_dry_run()
        )
    return run_ydotool(
        ["ydotool", "click", str(BUTTONS[button]), *legacy_delay_args()],
        dry_run=_grid_dry_run(),
    )


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
    surface. A consumer with a different verb set would parameterize that
    list and keep the rest of this probe (binary presence, dialect, socket,
    no-op) exactly as it stands — in practice the key-injection consumer
    landed with its own gate (core.mediakeys) and asserts capability at
    injection time instead of reusing this probe.
    """
    if shutil.which("ydotool") is None:
        logger.info("grid: ydotool is not installed")
        return False
    # The socket question comes FIRST, under the full startup bound: this must
    # be the process's first discovery call. _probe_tools's spawn reaches
    # _client_env, whose walk runs at the short per-use bound — if that walked
    # first and failed (a just-starting ydotoold needs >0.25s to accept), the
    # failure memory would make the startup call below share the "none" answer
    # instead of re-walking, and the gate would fail closed on a daemon that
    # was half a second late.
    path = injector_socket()
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
    # Direct `_run_bounded`, not `run_ydotool`: a failed probe is silent today
    # (the outcome is logged at INFO below), and routing through the runner
    # would add an undisclosed WARNING per failed probe.
    outcome = _run_bounded(noop_argv(), dry_run=_grid_dry_run())
    if outcome != "ran":
        logger.info("grid: the injector probe reported %s", outcome)
        return False
    return True


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
