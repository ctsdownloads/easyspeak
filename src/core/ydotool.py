"""The ydotool run seam: dialects, sockets, bounded runs, and capability probes.

Compositor-agnostic: it knows the ydotool client, not any caller. Extracted
verbatim from the mouse grid's backend (`easyspeak.plugins.mousegrid._ydotool`),
which re-imports everything here so its own namespace and its tests stay put.
Dry-run is a parameter, never an env read: the grid passes its own debug flag
down at its call sites, so a future consumer of this seam (key injection)
cannot inherit a grid-debug silent-ran switch by accident.
"""

import logging
import os
import socket
import stat
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)


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


_dialect = None


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
        logger.info("ydotool: `ydotool mousemove --help` did not answer: %s", exc)
        return YDTOOL_DIALECT_LEGACY
    if YDTOOL_ABSOLUTE_FLAG in result.stdout + result.stderr:
        return YDTOOL_DIALECT_MODERN
    return YDTOOL_DIALECT_LEGACY


def dialect():
    """Return the installed client's argv dialect, resolved once, on demand.

    On demand rather than in `resolve_active()` because the grid's
    forced-backend override short-circuits the probes, and the argv
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
            "ydotool: skipping %s (a socket owned by uid %s, not ours)",
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


def _run_bounded(args, timeout=INJECT_TIMEOUT, dry_run=None):
    """Run one ydotool invocation and return its outcome, never its exit code.

    `dry_run` short-circuits to "ran" without spawning the client. It is a
    parameter, deliberately not an env read: the grid passes its own debug
    flag here, and no other consumer can inherit a silent no-op by accident.

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
    if dry_run:
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
        logger.info("ydotool: per-invocation device (ydotoold unavailable)")
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


def run_ydotool(args, timeout=INJECT_TIMEOUT, dry_run=None):
    """Run an injection, logging whatever it was that happened."""
    outcome = _run_bounded(args, timeout=timeout, dry_run=dry_run)
    if outcome != "ran":
        logger.warning("injection outcome: %s", outcome)
    return outcome


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
        logger.info("ydotool: `ydotool help` did not answer: %s", exc)
        return None
    return parse_tool_list(result.stdout + result.stderr)


def noop_argv():
    """Return the probe's no-op invocation in the installed client's dialect.

    `type ""` types nothing, which is why it is the probe's verb; 0.1.8 spells
    its delay flag out on the argv and 1.0.x has no such flag at all.
    """
    if dialect() == YDTOOL_DIALECT_MODERN:
        return YDTOOL_NOOP_MODERN
    return YDTOOL_NOOP_LEGACY


# --- the key verb -----------------------------------------------------------
#
# Synthesis for `key`, per dialect. The grammars are the Task 0 fixtures'
# content, not our invention — tests/unit/core/fixtures/ydotool_key_usage_
# legacy.txt (0.1.8, live VM capture) and ..._modern.txt (1.0.x, captured from
# the client's own sources) are the oracle, and every argv shape below cites
# the fixture lines it came from. The legacy fixture's crash-probe transcript
# (`ydotool key 29:1 29:0`, its lines 73-75) documents a client abort, not a
# grammar, and feeds nothing here.

KEY_PER_REPEAT_BUDGET = 0.05  # s; PROVISIONAL — Task 7 calibrates it on the VM

# evdev keycode -> 0.1.8 combo NAME, reversed from the repo's two name->code
# tables: `core.mediakeys.KEYS` (spoken key names) and the dictation plugin's
# `KEYCODES` (paste-chord names). This is a literal, not a programmatic
# reverse of those tables: core cannot import the plugin (plugins import
# core), and key injection will make mediakeys import from here, so either
# import would close a cycle. Case is the client's problem, not ours — it
# uppercases names before lookup (upstream v0.1.8 Key.cpp, cited by the
# legacy fixture's corroboration section), and the fixture's own examples mix
# cases ("CTRL+alt+f3", "ctrl+Backspace", its lines 22 and 105). We emit
# lowercase for determinism.
#
# Deliberately absent: codes 104 and 109. Their repo names are the two-word
# spoken forms "page up"/"page down", and a space is not a combo name — the
# 0.1.8 resolver would fall through to its single-letter table and silently
# press `P` instead (the abort the fixture documents at its lines 25-27 only
# covers unknown single names). Upstream's full name table is unreachable
# (the evdevPlus repo 404s), so rather than guess a spelling no grounded
# source documents, these codes raise; Task 7's VM calibration can ground the
# real names (`strings /usr/bin/ydotool`) and extend this table.
KEY_LEGACY_NAMES = {
    28: "enter",  # mediakeys.KEYS["enter"]
    15: "tab",  # mediakeys.KEYS["tab"]
    1: "escape",  # mediakeys.KEYS["escape"]
    14: "backspace",  # mediakeys.KEYS["backspace"]; fixture lines 22/105
    103: "up",  # mediakeys.KEYS["up"]
    108: "down",  # mediakeys.KEYS["down"]
    105: "left",  # mediakeys.KEYS["left"]
    106: "right",  # mediakeys.KEYS["right"]
    102: "home",  # mediakeys.KEYS["home"]
    107: "end",  # mediakeys.KEYS["end"]
    29: "ctrl",  # dictation.KEYCODES["ctrl"]; fixture lines 22/105
    42: "shift",  # dictation.KEYCODES["shift"]; fixture line 106 ("Shift+#")
    56: "alt",  # dictation.KEYCODES["alt"]; fixture lines 22/105
    125: "super",  # dictation.KEYCODES["super"]
    110: "insert",  # dictation.KEYCODES["insert"]
    47: "v",  # dictation.KEYCODES["v"]; letters per the client's "alt+r", line 22
}


def key_timeout(repeats, floor=None, per_repeat=KEY_PER_REPEAT_BUDGET):
    """Upper bound for one batched `key` invocation; grows with `repeats`.

    A batched argv spends the client's key-delay pacing between keystrokes
    (12ms by default in both dialects — legacy fixture line 101, modern
    fixture line 85), so "backspace ten" cannot share the fixed
    `INJECT_TIMEOUT` a single keystroke uses. The bound scales with the batch
    and keeps `INJECT_TIMEOUT` as the floor.
    """
    return (floor if floor is not None else INJECT_TIMEOUT) + repeats * per_repeat


def key_argv(chord, repeats=1):
    """One batched `key` invocation pressing `chord` `repeats` times.

    Chord order mirrors `mediakeys.tap_chord`: keys go down in the order
    given and come up in reverse, per repeat. The whole batch is ONE
    invocation — daemonless 0.1.8 pays a fresh uinput device plus its settle
    delay per invocation, so "backspace ten" must be one call, not ten.

    The dialects disagree about the grammar itself (fixtures are the oracle):
    1.0.x takes raw `KEYCODE:PRESSED` tokens and has no repeat flag at all
    (modern fixture lines 25-35), so repeats are consecutive down/up cycles;
    0.1.8 takes ONE name combo joined with '+' plus a `--repeat <times>` flag
    (legacy fixture lines 18-27), so the flag does the repeating.
    """
    if dialect() == YDTOOL_DIALECT_MODERN:
        tokens = []
        for _ in range(repeats):
            tokens.extend(f"{code}:1" for code in chord)
            tokens.extend(f"{code}:0" for code in reversed(chord))
        return ("ydotool", "key", *tokens)
    return key_legacy_argv(chord, repeats=repeats)


def key_legacy_argv(chord, repeats=1):
    """The 0.1.8 `key` argv for one combo: `ctrl+v`, or `--repeat N ctrl+v`.

    Per the legacy fixture's usage line (its lines 18-19 and 93): options
    first, then ONE `<key sequence>` — NAMES joined with '+' (lines 21-22),
    each combo emitted by the client as a full press+release, up in reverse
    (corroboration section, line 120). `--repeat <times>` (line 102) repeats
    that sequence inside the same invocation. The other flags stay off
    because their documented defaults already serve: `--repeat-delay` is 0ms
    (line 103) and `--key-delay` is the client's own 12ms pacing (line 101).
    """
    combo = "+".join(_legacy_combo_name(code) for code in chord)
    argv = ["ydotool", "key"]
    if repeats > 1:
        argv.extend(("--repeat", str(repeats)))
    argv.append(combo)
    return tuple(argv)


def _legacy_combo_name(code):
    """The 0.1.8 combo NAME for an evdev keycode, or a loud error.

    The legacy fixture is explicit that an unknown NAME aborts the client
    ("no matching keycode", its lines 25-27), and its resolver's fallback
    would turn a wrong name into a silently wrong keypress. A code outside
    the grounded table therefore raises here, before any process is spawned.
    """
    try:
        return KEY_LEGACY_NAMES[code]
    except (KeyError, TypeError):
        raise ValueError(
            f"no legacy combo name for evdev code {code!r}: the 0.1.8 key "
            "verb takes names, not codes (ydotool_key_usage_legacy.txt "
            "lines 21-27)"
        ) from None
